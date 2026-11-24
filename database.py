import atexit
import base64
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from chem_data import (
    BASE_COLS,
    FAST_DENSITY_MAP,
    LABO_FILES_DIR,
    clean_val,
    get_known_density,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "chimie_db.sqlite")

PBKDF2_ITERATIONS = 120_000
MAX_AUTH_FAILS = 5
LOCKOUT_SECONDS = 60
SYNC_DEBOUNCE_SECONDS = 3.0

_AUTH_ATTEMPTS: dict[str, dict[str, Any]] = {}
_SYNC_LOCK = threading.Lock()
_SYNC_TIMER_LOCK = threading.Lock()
_SYNC_TIMER: threading.Timer | None = None

GITHUB_SYNC_STATUS: dict[str, Any] = {
    "configured": bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO")),
    "repo": os.environ.get("GITHUB_REPO", ""),
    "last_sync": "Aucune synchronisation sur cette session",
    "last_ok": None,
    "pending": False,
    "message": (
        "Prêt pour la sauvegarde asynchrone sur GitHub."
        if (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO"))
        else "Mode local uniquement (GITHUB_TOKEN / GITHUB_REPO non configurés)."
    ),
}


def hash_password(plain_password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        bytes.fromhex(salt),
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${dk.hex()}"


def verify_password(plain_password: str, stored_value: str) -> bool:
    if not stored_value:
        return False
    if stored_value.startswith("pbkdf2_sha256$"):
        try:
            _algo, iters_s, salt_hex, hash_hex = stored_value.split("$", 3)
            dk = hashlib.pbkdf2_hmac(
                "sha256",
                plain_password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iters_s),
            )
            return hmac.compare_digest(dk.hex(), hash_hex)
        except Exception:
            return False
    return hmac.compare_digest(plain_password, stored_value)


def _check_rate_limit(bucket: str) -> int:
    rec = _AUTH_ATTEMPTS.get(bucket)
    if not rec:
        return 0
    now = time.time()
    locked_until = float(rec.get("locked_until", 0.0))
    if now < locked_until:
        return int(locked_until - now) + 1
    if locked_until > 0 and now >= locked_until:
        _AUTH_ATTEMPTS.pop(bucket, None)
    return 0


def _record_auth_fail(bucket: str) -> int:
    now = time.time()
    rec = _AUTH_ATTEMPTS.get(bucket) or {"fails": 0, "locked_until": 0.0}
    rec["fails"] = int(rec.get("fails", 0)) + 1
    if rec["fails"] >= MAX_AUTH_FAILS:
        rec["locked_until"] = now + LOCKOUT_SECONDS
        rec["fails"] = 0
        _AUTH_ATTEMPTS[bucket] = rec
        return LOCKOUT_SECONDS
    _AUTH_ATTEMPTS[bucket] = rec
    return 0


def _clear_auth_fail(bucket: str):
    _AUTH_ATTEMPTS.pop(bucket, None)


def get_github_sync_status() -> dict[str, Any]:
    GITHUB_SYNC_STATUS["configured"] = bool(os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_REPO"))
    GITHUB_SYNC_STATUS["repo"] = os.environ.get("GITHUB_REPO", "")
    return dict(GITHUB_SYNC_STATUS)


def get_db_backup_bytes() -> bytes:
    if not os.path.exists(DB_FILE):
        return b""
    with open(DB_FILE, "rb") as f:
        return f.read()


def sync_db_to_github():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo or not os.path.exists(DB_FILE):
        GITHUB_SYNC_STATUS["configured"] = False
        GITHUB_SYNC_STATUS["pending"] = False
        return
    GITHUB_SYNC_STATUS["configured"] = True
    GITHUB_SYNC_STATUS["repo"] = repo

    with _SYNC_LOCK:
        try:
            url = f"https://api.github.com/repos/{repo}/contents/chimie_db.sqlite"
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "ChemBase-v2",
                "Content-Type": "application/json",
            }
            sha = None
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as r:
                    sha = json.loads(r.read().decode("utf-8")).get("sha")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    GITHUB_SYNC_STATUS["last_ok"] = False
                    GITHUB_SYNC_STATUS["pending"] = False
                    GITHUB_SYNC_STATUS["message"] = f"Erreur HTTP {e.code} lors de la lecture GitHub."
                    return
            with open(DB_FILE, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            payload: dict[str, Any] = {
                "message": f"Auto-save DB ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
                "content": b64,
            }
            if sha:
                payload["sha"] = sha
            urllib.request.urlopen(
                urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT"),
                timeout=15,
            )
            GITHUB_SYNC_STATUS["last_sync"] = datetime.now().strftime("%d/%m/%Y à %H:%M:%S")
            GITHUB_SYNC_STATUS["last_ok"] = True
            GITHUB_SYNC_STATUS["pending"] = False
            GITHUB_SYNC_STATUS["message"] = "Base SQLite synchronisée sur GitHub (arrière-plan)."
        except Exception as ex:
            GITHUB_SYNC_STATUS["last_ok"] = False
            GITHUB_SYNC_STATUS["pending"] = False
            GITHUB_SYNC_STATUS["message"] = f"Échec synchro GitHub : {ex}"


def _run_background_sync():
    global _SYNC_TIMER
    with _SYNC_TIMER_LOCK:
        _SYNC_TIMER = None
    sync_db_to_github()


def schedule_github_sync():
    """Déclenche une synchro GitHub non bloquante après un regroupement de 3 s."""
    global _SYNC_TIMER
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo or not os.path.exists(DB_FILE):
        GITHUB_SYNC_STATUS["configured"] = False
        return
    with _SYNC_TIMER_LOCK:
        if _SYNC_TIMER is not None:
            _SYNC_TIMER.cancel()
        GITHUB_SYNC_STATUS["configured"] = True
        GITHUB_SYNC_STATUS["repo"] = repo
        GITHUB_SYNC_STATUS["pending"] = True
        GITHUB_SYNC_STATUS["message"] = "Modifications en file d'attente (envoi GitHub sous 3 s)..."
        t = threading.Timer(SYNC_DEBOUNCE_SECONDS, _run_background_sync)
        t.daemon = True
        t.start()
        _SYNC_TIMER = t


def _flush_sync_on_exit():
    global _SYNC_TIMER
    should_flush = False
    with _SYNC_TIMER_LOCK:
        if _SYNC_TIMER is not None:
            _SYNC_TIMER.cancel()
            _SYNC_TIMER = None
            should_flush = True
    if should_flush:
        sync_db_to_github()


atexit.register(_flush_sync_on_exit)


class SyncedConnection(sqlite3.Connection):
    def commit(self):
        super().commit()
        schedule_github_sync()


def get_connection(sync: bool = True):
    conn = sqlite3.connect(DB_FILE, timeout=15, factory=SyncedConnection if sync else sqlite3.Connection)
    conn.row_factory = sqlite3.Row
    return conn


def _log_activity_conn(
    conn: sqlite3.Connection,
    username: str,
    category: str,
    action: str,
    details: str = "",
    role: str = "",
):
    uname = clean_val(username) or "système"
    r_val = clean_val(role)
    if not r_val and uname != "système":
        urow = conn.execute("SELECT role FROM users WHERE LOWER(username) = ?", (uname.lower(),)).fetchone()
        if urow:
            r_val = clean_val(urow["role"])
    conn.execute(
        "INSERT INTO activity_logs (timestamp, username, role, category, action, details) VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            uname,
            r_val or "chercheur",
            category.upper(),
            action,
            details,
        ),
    )


def log_activity(username: str, category: str, action: str, details: str = "", role: str = ""):
    with get_connection(sync=False) as conn:
        _log_activity_conn(conn, username, category, action, details, role)
        conn.commit()


def get_activity_logs(username_filter: str = "", category_filter: str = "", limit: int = 120) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if clean_val(username_filter) and username_filter != "Tous":
        clauses.append("LOWER(username) = ?")
        params.append(clean_val(username_filter).lower())
    if clean_val(category_filter) and category_filter != "Toutes":
        clauses.append("UPPER(category) = ?")
        params.append(clean_val(category_filter).upper())
    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(int(limit))
    with get_connection(sync=False) as conn:
        rows = conn.execute(
            f"SELECT * FROM activity_logs {where_sql} ORDER BY id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [dict(r) for r in rows]


def get_activity_usernames() -> list[str]:
    with get_connection(sync=False) as conn:
        rows = conn.execute(
            "SELECT DISTINCT username FROM activity_logs WHERE TRIM(COALESCE(username, '')) != '' ORDER BY username ASC"
        ).fetchall()
        return [str(r["username"]) for r in rows]


def sync_inventory_with_syntheses(conn: sqlite3.Connection):
    cur = conn.cursor()
    rows = [dict(r) for r in cur.execute("SELECT * FROM syntheses").fetchall()]
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    cas_by_prod: dict[str, str] = {}

    for r in rows:
        p_name = clean_val(r.get("Produit final"))
        cas_p = clean_val(r.get("Numéro CAS"))
        if p_name:
            cas_by_prod[p_name.lower()] = cas_p.lower()
            unite_p = "mL" if "liquide" in clean_val(r.get("État physique")).lower() else "g"
            loc_p = clean_val(r.get("Conditions de stockage")) or "Armoire ventilée"
            dens_p = get_known_density(cas_p, get_known_density(p_name, 0.95))
            cur.execute(
                "INSERT OR IGNORE INTO inventory (nom_substance, categorie, quantite, unite, seuil_alerte, emplacement, derniere_maj, densite) "
                "VALUES (?, 'Produit synthétisé', 50.0, ?, 15.0, ?, ?, ?)",
                (p_name, unite_p, loc_p, now_s, dens_p),
            )
        for i in range(1, 5):
            rea_name = clean_val(r.get(f"Réactifs {i}"))
            if rea_name:
                dens_r = get_known_density(rea_name, 1.0)
                cur.execute(
                    "INSERT OR IGNORE INTO inventory (nom_substance, categorie, quantite, unite, seuil_alerte, emplacement, derniere_maj, densite) "
                    "VALUES (?, 'Réactif / Matière 1ère', 250.0, 'g', 50.0, 'Magasin réactifs', ?, ?)",
                    (rea_name, now_s, dens_r),
                )

    for row in cur.execute("SELECT id, nom_substance, densite FROM inventory").fetchall():
        r_id, sub_n, cur_d = row["id"], row["nom_substance"], row["densite"]
        if cur_d is None or float(cur_d) in (1.0, 0.95):
            sub_l = str(sub_n).strip().lower()
            real_d = FAST_DENSITY_MAP.get(cas_by_prod.get(sub_l, "")) or FAST_DENSITY_MAP.get(sub_l)
            if real_d and float(real_d) != float(cur_d or 1.0):
                cur.execute("UPDATE inventory SET densite = ? WHERE id = ?", (float(real_d), r_id))


def init_db():
    with get_connection(sync=False) as conn:
        cur = conn.cursor()
        cols_sql = ", ".join([f"[{c}] TEXT" for c in BASE_COLS])
        cur.execute(f"CREATE TABLE IF NOT EXISTS syntheses (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols_sql}, [Image_Path] TEXT, [Molecule_Image_Path] TEXT)")
        cur.execute(f"CREATE TABLE IF NOT EXISTS syntheses_pending (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols_sql}, [Temp_Image_Path] TEXT, [Temp_Molecule_Image_Path] TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS admin_audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, admin_username TEXT, action_type TEXT, product_name TEXT, full_details TEXT, payload_json TEXT, reverted INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, query_text TEXT, filter_produit TEXT, filter_reaction TEXT, filter_reactif TEXT, results_count INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT, warnings INTEGER DEFAULT 0, warning_acknowledged INTEGER DEFAULT 1, is_root INTEGER DEFAULT 0)")
        cur.execute("CREATE TABLE IF NOT EXISTS password_resets (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, requested_at TEXT, status TEXT DEFAULT 'pending')")
        cur.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, product_name TEXT, UNIQUE(username, product_name))")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS lab_notebook ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, date_essai TEXT, operateur TEXT, produit_cible TEXT, "
            "quantites_engagees TEXT, masse_theorique REAL, masse_obtenue REAL, rendement_reel REAL, "
            "rendement_theorique TEXT, statut TEXT, observations TEXT, attachment_path TEXT, "
            "attachment_name TEXT, attachment_mime TEXT, attachment_data BLOB)"
        )
        cur.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, nom_substance TEXT UNIQUE, categorie TEXT, quantite REAL, unite TEXT, seuil_alerte REAL, emplacement TEXT, derniere_maj TEXT, densite REAL DEFAULT 1.0)")
        cur.execute("CREATE TABLE IF NOT EXISTS stock_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, nom_substance TEXT, alert_level TEXT, quantite REAL, unite TEXT, seuil REAL, is_read INTEGER DEFAULT 0)")
        cur.execute(
            "CREATE TABLE IF NOT EXISTS stock_movements ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, nom_substance TEXT, "
            "delta REAL, unite TEXT, quantite_apres REAL, operateur TEXT, motif TEXT)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS activity_logs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, username TEXT, role TEXT, "
            "category TEXT, action TEXT, details TEXT)"
        )
        cur.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")

        for alter_sql in (
            "ALTER TABLE lab_notebook ADD COLUMN attachment_path TEXT",
            "ALTER TABLE lab_notebook ADD COLUMN attachment_name TEXT",
            "ALTER TABLE lab_notebook ADD COLUMN attachment_mime TEXT",
            "ALTER TABLE lab_notebook ADD COLUMN attachment_data BLOB",
            "ALTER TABLE inventory ADD COLUMN densite REAL DEFAULT 1.0",
            "ALTER TABLE admin_audit_logs ADD COLUMN payload_json TEXT",
            "ALTER TABLE admin_audit_logs ADD COLUMN reverted INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN warnings INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN warning_acknowledged INTEGER DEFAULT 1",
            "ALTER TABLE users ADD COLUMN is_root INTEGER DEFAULT 0",
        ):
            try:
                cur.execute(alter_sql)
            except Exception:
                pass

        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('lab_access_code', 'CHEM-2026')")
        cur.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES ('registration_open', '1')")
        cur.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES ('chemstudio_api_key', ?)",
            (f"cb_{secrets.token_urlsafe(24)}",),
        )

        if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            cur.executemany(
                "INSERT INTO users (username, password, role, warnings, warning_acknowledged, is_root) VALUES (?, ?, ?, 0, 1, ?)",
                [
                    ("superadmin", hash_password("super2026"), "superadmin", 1),
                    ("admin", hash_password("chimie2026"), "admin", 0),
                ],
            )
        else:
            for urow in cur.execute("SELECT id, password FROM users").fetchall():
                pwd = urow["password"] or ""
                if pwd and not pwd.startswith("pbkdf2_sha256$"):
                    cur.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(pwd), urow["id"]))

            has_root = cur.execute("SELECT COUNT(*) FROM users WHERE is_root = 1").fetchone()[0]
            if has_root == 0:
                orig = cur.execute("SELECT id FROM users WHERE LOWER(username) = 'superadmin' LIMIT 1").fetchone()
                if not orig:
                    orig = cur.execute("SELECT id FROM users WHERE role = 'superadmin' ORDER BY id ASC LIMIT 1").fetchone()
                if orig:
                    cur.execute("UPDATE users SET is_root = 1, role = 'superadmin' WHERE id = ?", (orig["id"],))

        sync_inventory_with_syntheses(conn)
        conn.commit()


# ------------------------------------------------------------------
# PARAMÈTRES SYSTÈME (CODE LABO & CLÉ API CHEMSTUDIO)
# ------------------------------------------------------------------
def get_lab_registration_settings() -> dict[str, Any]:
    with get_connection(sync=False) as conn:
        rows = conn.execute("SELECT key, value FROM app_settings WHERE key IN ('lab_access_code', 'registration_open')").fetchall()
        mp = {str(r["key"]): str(r["value"]) for r in rows}
        return {
            "code": mp.get("lab_access_code", "CHEM-2026"),
            "open": mp.get("registration_open", "1") == "1",
        }


def update_lab_registration_settings(new_code: str, is_open: bool, actor_username: str) -> tuple[bool, str]:
    code_clean = clean_val(new_code)
    if len(code_clean) < 4:
        return False, "Le Code Laboratoire doit contenir au moins 4 caractères."
    with get_connection(sync=True) as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('lab_access_code', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (code_clean,),
        )
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('registration_open', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if is_open else "0",),
        )
        _log_activity_conn(
            conn,
            actor_username,
            "ADMIN",
            "Code Laboratoire mis à jour",
            f"Inscriptions {'ouvertes' if is_open else 'fermées'} (code modifié)",
        )
        conn.commit()
    return True, f"Paramètres d'inscription enregistrés ({'ouvertes' if is_open else 'fermées'})."


def get_api_key() -> tuple[str, bool]:
    """Retourne (api_key, from_env). La variable Render CHEMSTUDIO_API_KEY est prioritaire."""
    env_key = clean_val(os.environ.get("CHEMSTUDIO_API_KEY"))
    if env_key:
        return env_key, True
    with get_connection(sync=False) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'chemstudio_api_key'").fetchone()
        if row and clean_val(row["value"]):
            return clean_val(row["value"]), False
    new_key = f"cb_{secrets.token_urlsafe(24)}"
    with get_connection(sync=True) as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('chemstudio_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (new_key,),
        )
        conn.commit()
    return new_key, False


def rotate_api_key(actor_username: str) -> tuple[bool, str]:
    if clean_val(os.environ.get("CHEMSTUDIO_API_KEY")):
        return False, "La clé est définie par la variable d'environnement CHEMSTUDIO_API_KEY (modifiez-la dans Render)."
    new_key = f"cb_{secrets.token_urlsafe(24)}"
    with get_connection(sync=True) as conn:
        conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ('chemstudio_api_key', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (new_key,),
        )
        _log_activity_conn(conn, actor_username, "ADMIN", "Clé API ChemStudio régénérée", "Ancienne clé immédiatement révoquée")
        conn.commit()
    return True, "Nouvelle clé API générée (l'ancienne clé ne fonctionne plus)."


def _safe_count(cur: sqlite3.Cursor, query: str) -> int:
    try:
        row = cur.execute(query).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def read_db_status() -> dict[str, Any]:
    if not os.path.exists(DB_FILE):
        return {"connected": False, "molecules": 0, "inventory": 0, "low_stock": 0, "labo": 0, "pending": 0, "alerts": 0, "resets": 0}
    with get_connection(sync=False) as conn:
        cur = conn.cursor()
        return {
            "connected": True,
            "molecules": _safe_count(cur, "SELECT COUNT(*) FROM syntheses"),
            "inventory": _safe_count(cur, "SELECT COUNT(*) FROM inventory"),
            "low_stock": _safe_count(cur, "SELECT COUNT(*) FROM inventory WHERE quantite <= seuil_alerte"),
            "labo": _safe_count(cur, "SELECT COUNT(*) FROM lab_notebook"),
            "pending": _safe_count(cur, "SELECT COUNT(*) FROM syntheses_pending"),
            "alerts": _safe_count(cur, "SELECT COUNT(*) FROM stock_alerts WHERE is_read = 0"),
            "resets": _safe_count(cur, "SELECT COUNT(*) FROM password_resets WHERE status = 'pending'"),
        }


# ------------------------------------------------------------------
# CATALOGUE & FAVORIS
# ------------------------------------------------------------------
def get_all_syntheses() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM syntheses ORDER BY [Produit final] ASC").fetchall()]


def get_favorites(username: str) -> set[str]:
    with get_connection(sync=False) as conn:
        rows = conn.execute("SELECT product_name FROM favorites WHERE username = ?", (username,)).fetchall()
        return {str(r["product_name"]) for r in rows}


def toggle_favorite(username: str, product_name: str) -> bool:
    with get_connection(sync=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM favorites WHERE username = ? AND product_name = ?",
            (username, product_name),
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM favorites WHERE username = ? AND product_name = ?", (username, product_name))
            conn.commit()
            return False
        conn.execute("INSERT OR IGNORE INTO favorites (username, product_name) VALUES (?, ?)", (username, product_name))
        conn.commit()
        return True


def log_search(query_text: str, f_prod: str, f_rx: str, f_rea: str, results_count: int):
    q = clean_val(query_text)
    if not q:
        return
    with get_connection(sync=False) as conn:
        last = conn.execute("SELECT query_text FROM search_logs ORDER BY id DESC LIMIT 1").fetchone()
        if last and clean_val(last["query_text"]).lower() == q.lower():
            return
        conn.execute(
            "INSERT INTO search_logs (timestamp, query_text, filter_produit, filter_reaction, filter_reactif, results_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), q, f_prod, f_rx, f_rea, results_count),
        )
        conn.commit()


def insert_pending_synthese(values_16: list[str], author_username: str = "chercheur"):
    cols_str = ", ".join([f"[{c}]" for c in BASE_COLS])
    prod_name = clean_val(values_16[0]) if values_16 else "Nouvelle fiche"
    with get_connection(sync=True) as conn:
        conn.execute(
            f"INSERT INTO syntheses_pending ({cols_str}) VALUES ({', '.join(['?'] * 16)})",
            tuple(values_16),
        )
        _log_activity_conn(
            conn,
            author_username,
            "PROPOSITION",
            f"Proposition de fiche : {prod_name}",
            f"Envoyée en file de modération (CAS : {clean_val(values_16[10]) or 'N/A'})",
        )
        conn.commit()


def insert_direct_synthese(values_16: list[str], admin_username: str) -> int:
    cols_str = ", ".join([f"[{c}]" for c in BASE_COLS])
    snap = {c: clean_val(values_16[idx]) if idx < len(values_16) else "" for idx, c in enumerate(BASE_COLS)}
    prod_name = snap["Produit final"] or "Sans nom"
    with get_connection(sync=True) as conn:
        cur = conn.execute(
            f"INSERT INTO syntheses ({cols_str}) VALUES ({', '.join(['?'] * len(BASE_COLS))})",
            tuple(snap[c] for c in BASE_COLS),
        )
        new_id = int(cur.lastrowid or 0)
        sync_inventory_with_syntheses(conn)
        payload = json.dumps({"synth_id": new_id, "snapshot": snap}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'VALIDATION', ?, ?, ?, 0)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                admin_username,
                prod_name,
                f"Publication directe Super-Admin (CAS : {snap['Numéro CAS'] or 'N/A'})",
                payload,
            ),
        )
        _log_activity_conn(
            conn,
            admin_username,
            "CATALOGUE",
            f"Publication directe : {prod_name}",
            f"Fiche ajoutée au catalogue sans modération (CAS : {snap['Numéro CAS'] or 'N/A'})",
        )
        conn.commit()
        return new_id


# ------------------------------------------------------------------
# INVENTAIRE, TRAÇABILITÉ DES MOUVEMENTS & ALERTES STOCK
# ------------------------------------------------------------------
def get_inventory_map() -> dict[str, tuple[float, str, float, float]]:
    with get_connection(sync=False) as conn:
        rows = conn.execute("SELECT nom_substance, quantite, unite, seuil_alerte, densite FROM inventory").fetchall()
        return {
            str(r["nom_substance"]).strip().lower(): (
                float(r["quantite"] or 0.0),
                clean_val(r["unite"]) or "g",
                float(r["seuil_alerte"] or 0.0),
                float(r["densite"] or 1.0),
            )
            for r in rows
        }


def get_all_inventory() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM inventory ORDER BY CASE WHEN quantite <= 0 THEN 0 WHEN quantite <= seuil_alerte THEN 1 ELSE 2 END, nom_substance ASC"
            ).fetchall()
        ]


def _maybe_create_stock_alert(conn: sqlite3.Connection, nom: str, qty: float, unite: str, seuil: float):
    if qty <= seuil:
        level = "RUPTURE" if qty <= 0 else "SEUIL CRITIQUE"
        conn.execute(
            "INSERT INTO stock_alerts (timestamp, nom_substance, alert_level, quantite, unite, seuil, is_read) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), nom, level, round(qty, 2), unite, round(seuil, 2)),
        )


def _record_stock_movement(
    conn: sqlite3.Connection,
    nom: str,
    delta: float,
    unite: str,
    qty_after: float,
    operator: str = "chercheur",
    motif: str = "Ajustement manuel",
):
    op_clean = clean_val(operator) or "chercheur"
    motif_clean = clean_val(motif) or "Ajustement manuel"
    d_round = round(float(delta), 2)
    q_round = round(float(qty_after), 2)
    conn.execute(
        "INSERT INTO stock_movements (timestamp, nom_substance, delta, unite, quantite_apres, operateur, motif) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M"), nom, d_round, unite, q_round, op_clean, motif_clean),
    )
    sign = f"+{d_round:g}" if d_round >= 0 else f"{d_round:g}"
    _log_activity_conn(
        conn,
        op_clean,
        "STOCK",
        f"{nom} ({sign} {unite})",
        f"{motif_clean} · nouveau solde : {q_round:g} {unite}",
    )


def get_stock_movements(nom_substance: str = "", limit: int = 40) -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        if clean_val(nom_substance):
            rows = conn.execute(
                "SELECT * FROM stock_movements WHERE LOWER(nom_substance) = ? ORDER BY id DESC LIMIT ?",
                (clean_val(nom_substance).lower(), int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM stock_movements ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(r) for r in rows]


def upsert_inventory_item(
    nom: str,
    categorie: str,
    quantite: float,
    unite: str,
    seuil: float,
    emplacement: str,
    densite: float,
    item_id: int | None = None,
    operator: str = "chercheur",
):
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    qty_clean = max(0.0, round(float(quantite), 2))
    seuil_clean = max(0.0, round(float(seuil), 2))
    dens_clean = max(0.1, round(float(densite or 1.0), 3))
    with get_connection(sync=True) as conn:
        prev_qty = 0.0
        if item_id is not None:
            old = conn.execute("SELECT quantite FROM inventory WHERE id = ?", (int(item_id),)).fetchone()
            prev_qty = float(old["quantite"] or 0.0) if old else 0.0
            conn.execute(
                "UPDATE inventory SET nom_substance=?, categorie=?, quantite=?, unite=?, seuil_alerte=?, emplacement=?, derniere_maj=?, densite=? WHERE id=?",
                (nom.strip(), categorie, qty_clean, unite, seuil_clean, emplacement.strip(), now_s, dens_clean, int(item_id)),
            )
            delta = qty_clean - prev_qty
            if abs(delta) >= 0.01:
                _record_stock_movement(conn, nom.strip(), delta, unite, qty_clean, operator, "Édition fiche inventaire")
        else:
            existing = conn.execute("SELECT quantite FROM inventory WHERE LOWER(nom_substance) = ?", (nom.strip().lower(),)).fetchone()
            prev_qty = float(existing["quantite"] or 0.0) if existing else 0.0
            conn.execute(
                "INSERT INTO inventory (nom_substance, categorie, quantite, unite, seuil_alerte, emplacement, derniere_maj, densite) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(nom_substance) DO UPDATE SET categorie=excluded.categorie, quantite=excluded.quantite, unite=excluded.unite, "
                "seuil_alerte=excluded.seuil_alerte, emplacement=excluded.emplacement, derniere_maj=excluded.derniere_maj, densite=excluded.densite",
                (nom.strip(), categorie, qty_clean, unite, seuil_clean, emplacement.strip(), now_s, dens_clean),
            )
            _record_stock_movement(conn, nom.strip(), qty_clean - prev_qty, unite, qty_clean, operator, "Création référence" if not existing else "Mise à jour référence")
        _maybe_create_stock_alert(conn, nom.strip(), qty_clean, unite, seuil_clean)
        conn.commit()


def adjust_inventory_quantity(item_id: int, delta: float, operator: str = "chercheur", motif: str = "Ajustement rapide"):
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT nom_substance, quantite, unite, seuil_alerte FROM inventory WHERE id = ?", (int(item_id),)).fetchone()
        if not row:
            return
        old_qty = float(row["quantite"] or 0.0)
        new_qty = max(0.0, round(old_qty + float(delta), 2))
        real_delta = round(new_qty - old_qty, 2)
        unit = row["unite"] or "g"
        conn.execute("UPDATE inventory SET quantite = ?, derniere_maj = ? WHERE id = ?", (new_qty, now_s, int(item_id)))
        if abs(real_delta) >= 0.01:
            _record_stock_movement(conn, row["nom_substance"], real_delta, unit, new_qty, operator, motif)
        _maybe_create_stock_alert(conn, row["nom_substance"], new_qty, unit, float(row["seuil_alerte"] or 0.0))
        conn.commit()


def quick_stock_movement(
    nom_substance: str,
    amount: float,
    input_unit: str,
    is_addition: bool,
    operator: str = "chercheur",
    motif: str = "",
) -> tuple[bool, str]:
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_connection(sync=True) as conn:
        row = conn.execute(
            "SELECT id, nom_substance, quantite, unite, seuil_alerte, densite FROM inventory WHERE LOWER(nom_substance) = ?",
            (clean_val(nom_substance).lower(),),
        ).fetchone()
        if not row:
            return False, "Substance introuvable dans l'inventaire."
        stock_unit = clean_val(row["unite"]) or "g"
        dens = float(row["densite"] or 1.0)
        amt = abs(float(amount))

        u_in = clean_val(input_unit).lower()
        u_st = stock_unit.lower()
        converted = amt
        if u_in == "g" and u_st == "ml" and dens > 0:
            converted = amt / dens
        elif u_in == "ml" and u_st == "g":
            converted = amt * dens
        elif u_in == "g" and u_st == "kg" or u_in == "ml" and u_st == "l":
            converted = amt / 1000.0
        elif u_in == "g" and u_st == "l" and dens > 0:
            converted = (amt / dens) / 1000.0
        elif u_in == "ml" and u_st == "kg":
            converted = (amt * dens) / 1000.0

        old_qty = float(row["quantite"] or 0.0)
        delta = converted if is_addition else -converted
        new_qty = max(0.0, round(old_qty + delta, 2))
        real_delta = round(new_qty - old_qty, 2)
        conn.execute("UPDATE inventory SET quantite = ?, derniere_maj = ? WHERE id = ?", (new_qty, now_s, row["id"]))
        default_motif = "Réapprovisionnement paillasse" if is_addition else "Prélèvement paillasse"
        _record_stock_movement(conn, row["nom_substance"], real_delta, stock_unit, new_qty, operator, motif or default_motif)
        _maybe_create_stock_alert(conn, row["nom_substance"], new_qty, stock_unit, float(row["seuil_alerte"] or 0.0))
        conn.commit()
        verb = "Ajouté" if is_addition else "Prélevé"
        return True, f"{verb} {converted:.2f} {stock_unit} sur « {row['nom_substance']} » (nouveau stock : {new_qty:g} {stock_unit})."


def deduct_inventory_by_name(nom_substance: str, amount_g: float, operator: str = "chercheur", motif: str = "Calculateur stœchiométrique") -> bool:
    ok, _msg = quick_stock_movement(nom_substance, amount_g, "g", is_addition=False, operator=operator, motif=motif)
    return ok


def delete_inventory_item(item_id: int, operator: str = "chercheur"):
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT nom_substance FROM inventory WHERE id = ?", (int(item_id),)).fetchone()
        conn.execute("DELETE FROM inventory WHERE id = ?", (int(item_id),))
        if row:
            _log_activity_conn(conn, operator, "STOCK", f"Suppression référence : {row['nom_substance']}", "Retirée de l'inventaire")
        conn.commit()


# ------------------------------------------------------------------
# CAHIER DE LABORATOIRE & PIÈCES JOINTES PERSISTANTES (BLOB SQLITE)
# ------------------------------------------------------------------
def get_all_labo_entries() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, date_essai, operateur, produit_cible, quantites_engagees, "
                "masse_theorique, masse_obtenue, rendement_reel, rendement_theorique, "
                "statut, observations, attachment_path, attachment_name, attachment_mime, "
                "CASE WHEN attachment_data IS NOT NULL AND LENGTH(attachment_data) > 0 THEN 1 ELSE 0 END AS has_blob "
                "FROM lab_notebook ORDER BY id DESC"
            ).fetchall()
        ]


def get_labo_attachment(entry_id: int) -> tuple[str, str, bytes] | None:
    """Récupère la pièce jointe stockée en BLOB SQLite (avec repli compatible sur anciens fichiers disque)."""
    with get_connection(sync=False) as conn:
        row = conn.execute(
            "SELECT attachment_name, attachment_mime, attachment_data, attachment_path FROM lab_notebook WHERE id = ?",
            (int(entry_id),),
        ).fetchone()
    if not row:
        return None
    blob = row["attachment_data"]
    if blob:
        fname = clean_val(row["attachment_name"]) or f"piece_jointe_{entry_id}"
        mime = clean_val(row["attachment_mime"]) or mimetypes.guess_type(fname)[0] or "application/octet-stream"
        return fname, mime, bytes(blob)
    legacy_path = clean_val(row["attachment_path"])
    if legacy_path:
        disk_path = os.path.join(LABO_FILES_DIR, os.path.basename(legacy_path))
        if os.path.exists(disk_path):
            with open(disk_path, "rb") as f:
                raw = f.read()
            fname = os.path.basename(disk_path)
            mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
            return fname, mime, raw
    return None


def insert_labo_entry(
    date_essai: str,
    operateur: str,
    produit_cible: str,
    quantites_engagees: str,
    masse_theorique: float,
    masse_obtenue: float,
    rendement_reel: float,
    rendement_theorique: str,
    statut: str,
    observations: str,
    attachment_path: str = "",
    attachment_name: str = "",
    attachment_mime: str = "",
    attachment_data: bytes | None = None,
):
    with get_connection(sync=True) as conn:
        conn.execute(
            "INSERT INTO lab_notebook (date_essai, operateur, produit_cible, quantites_engagees, masse_theorique, "
            "masse_obtenue, rendement_reel, rendement_theorique, statut, observations, attachment_path, "
            "attachment_name, attachment_mime, attachment_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date_essai, operateur, produit_cible, quantites_engagees,
                round(float(masse_theorique), 2), round(float(masse_obtenue), 2),
                round(float(rendement_reel), 1), rendement_theorique, statut, observations,
                attachment_path, attachment_name, attachment_mime,
                sqlite3.Binary(attachment_data) if attachment_data else None,
            ),
        )
        _log_activity_conn(
            conn,
            operateur,
            "LABO",
            f"Essai archivé : {produit_cible}",
            f"Rendement {round(float(rendement_reel), 1)} % ({round(float(masse_obtenue), 2)} g / {round(float(masse_theorique), 2)} g) · {statut}",
        )
        conn.commit()


def delete_labo_entry(entry_id: int, actor_username: str = ""):
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT produit_cible, operateur FROM lab_notebook WHERE id = ?", (int(entry_id),)).fetchone()
        conn.execute("DELETE FROM lab_notebook WHERE id = ?", (int(entry_id),))
        if row:
            _log_activity_conn(
                conn,
                actor_username or clean_val(row["operateur"]),
                "LABO",
                f"Essai supprimé : {row['produit_cible']}",
                f"Essai #{entry_id} (auteur initial : {row['operateur']})",
            )
        conn.commit()


# ------------------------------------------------------------------
# UTILISATEURS, CONNEXION OBLIGATOIRE, INSCRIPTION CODE LABO & HIÉRARCHIE ROOT
# ------------------------------------------------------------------
def _row_to_user_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "username": str(row["username"]),
        "role": str(row["role"]),
        "warnings": int(row["warnings"] or 0),
        "warning_acknowledged": int(row["warning_acknowledged"] if row["warning_acknowledged"] is not None else 1),
        "is_root": int(row["is_root"] or 0) == 1,
    }


def authenticate_user_checked(username: str, password: str) -> tuple[dict[str, Any] | None, str]:
    u_clean = clean_val(username)
    if not u_clean or not password:
        return None, "Saisissez votre identifiant et votre mot de passe."
    bucket = f"login:{u_clean.lower()}"
    wait_s = _check_rate_limit(bucket)
    if wait_s > 0:
        return None, f"Trop de tentatives échouées. Réessayez dans {wait_s} s."

    with get_connection(sync=False) as conn:
        row = conn.execute(
            "SELECT id, username, password, role, warnings, warning_acknowledged, is_root FROM users WHERE LOWER(username) = ?",
            (u_clean.lower(),),
        ).fetchone()
        if not row or not verify_password(password, row["password"]):
            locked = _record_auth_fail(bucket)
            if locked > 0:
                return None, f"Identifiants incorrects. Compte temporairement bloqué ({locked} s)."
            return None, "Identifiant ou mot de passe incorrect."

        _clear_auth_fail(bucket)
        user_d = _row_to_user_dict(row)
        _log_activity_conn(conn, user_d["username"], "CONNEXION", "Connexion à ChemBase", f"Rôle : {user_d['role']}", role=user_d["role"])
        conn.commit()
        return user_d, "Connexion réussie."


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    user, _msg = authenticate_user_checked(username, password)
    return user


def register_researcher(username: str, password: str, access_code: str) -> tuple[bool, str, dict[str, Any] | None]:
    bucket = "register:global"
    wait_s = _check_rate_limit(bucket)
    if wait_s > 0:
        return False, f"Trop de tentatives avec un mauvais code. Réessayez dans {wait_s} s.", None

    settings = get_lab_registration_settings()
    if not settings["open"]:
        return False, "Les nouvelles inscriptions sont actuellement fermées par le Super-Admin.", None

    u_clean = clean_val(username)
    if len(u_clean) < 3 or len(u_clean) > 32 or not re.fullmatch(r"[A-Za-z0-9._-]+", u_clean):
        return False, "Identifiant invalide (3 à 32 caractères : lettres, chiffres, ., _ ou -).", None
    if len(password or "") < 6:
        return False, "Le mot de passe doit contenir au moins 6 caractères.", None
    if not hmac.compare_digest(clean_val(access_code), settings["code"]):
        locked = _record_auth_fail(bucket)
        if locked > 0:
            return False, f"Code Laboratoire incorrect. Inscriptions en pause ({locked} s).", None
        return False, "Code Laboratoire incorrect.", None

    _clear_auth_fail(bucket)
    with get_connection(sync=True) as conn:
        existing = conn.execute("SELECT 1 FROM users WHERE LOWER(username) = ?", (u_clean.lower(),)).fetchone()
        if existing:
            return False, "Cet identifiant est déjà utilisé.", None
        cur = conn.execute(
            "INSERT INTO users (username, password, role, warnings, warning_acknowledged, is_root) VALUES (?, ?, 'chercheur', 0, 1, 0)",
            (u_clean, hash_password(password)),
        )
        new_id = int(cur.lastrowid or 0)
        _log_activity_conn(
            conn,
            u_clean,
            "INSCRIPTION",
            "Nouveau compte chercheur créé",
            "Inscription autonome via Code Laboratoire",
            role="chercheur",
        )
        conn.commit()
        user_d = {
            "id": new_id,
            "username": u_clean,
            "role": "chercheur",
            "warnings": 0,
            "warning_acknowledged": 1,
            "is_root": False,
        }
        return True, f"Bienvenue {u_clean} ! Votre compte chercheur est actif.", user_d


def change_own_password(user_id: int, current_password: str, new_password: str) -> tuple[bool, str]:
    if len(new_password or "") < 6:
        return False, "Le nouveau mot de passe doit contenir au moins 6 caractères."
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT id, username, password, role FROM users WHERE id = ?", (int(user_id),)).fetchone()
        if not row:
            return False, "Compte introuvable."
        if not verify_password(current_password or "", row["password"]):
            return False, "Votre mot de passe actuel est incorrect."
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(new_password), int(user_id)))
        _log_activity_conn(conn, row["username"], "COMPTE", "Mot de passe modifié", "Changement autonome depuis Mon compte", role=row["role"])
        conn.commit()
        return True, "Votre mot de passe a été mis à jour avec succès."


def get_user_by_username(username: str) -> dict[str, Any] | None:
    if not clean_val(username):
        return None
    with get_connection(sync=False) as conn:
        row = conn.execute(
            "SELECT id, username, role, warnings, warning_acknowledged, is_root FROM users WHERE LOWER(username) = ?",
            (clean_val(username).lower(),),
        ).fetchone()
        return _row_to_user_dict(row) if row else None


def acknowledge_user_warnings(username: str):
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE users SET warning_acknowledged = 1 WHERE LOWER(username) = ?", (clean_val(username).lower(),))
        conn.commit()


def get_all_users() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        rows = conn.execute(
            "SELECT id, username, role, warnings, warning_acknowledged, is_root FROM users "
            "ORDER BY is_root DESC, CASE role WHEN 'superadmin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, username ASC"
        ).fetchall()
        return [_row_to_user_dict(r) for r in rows]


def create_user(username: str, password: str, role: str = "admin", actor_username: str = "superadmin") -> bool:
    u_clean = clean_val(username)
    if not u_clean or not password:
        return False
    try:
        with get_connection(sync=True) as conn:
            conn.execute(
                "INSERT INTO users (username, password, role, warnings, warning_acknowledged, is_root) VALUES (?, ?, ?, 0, 1, 0)",
                (u_clean, hash_password(password), role),
            )
            _log_activity_conn(conn, actor_username, "ADMIN", f"Création compte : {u_clean}", f"Rôle attribué : {role}")
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False


def update_user_account(
    target_user_id: int,
    new_username: str,
    new_password: str,
    new_role: str,
    confirm_super_pwd: str = "",
    actor_username: str = "superadmin",
    actor_is_root: bool = False,
) -> tuple[bool, str]:
    with get_connection(sync=True) as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (int(target_user_id),)).fetchone()
        if not target:
            return False, "Compte introuvable."
        target_is_root = int(target["is_root"] or 0) == 1

        if target_is_root:
            if not actor_is_root:
                return False, "Action refusée : le compte Super-Admin fondateur est intouchable."
            if new_role != "superadmin":
                return False, "Le compte Super-Admin fondateur doit conserver le rôle superadmin."
        elif target["role"] == "superadmin":
            if not actor_is_root:
                if not verify_password(confirm_super_pwd, target["password"]):
                    return False, "Action refusée : le mot de passe du Super-Admin concerné est incorrect."
            if new_role != "superadmin":
                sup_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'superadmin'").fetchone()[0]
                if sup_count <= 1:
                    return False, "Impossible de rétrograder le dernier Super-Admin actif."

        final_user = clean_val(new_username) or str(target["username"])
        final_pwd = hash_password(new_password) if new_password else str(target["password"])
        try:
            conn.execute(
                "UPDATE users SET username = ?, password = ?, role = ? WHERE id = ?",
                (final_user, final_pwd, new_role, int(target_user_id)),
            )
        except sqlite3.IntegrityError:
            return False, "Cet identifiant est déjà utilisé."

        details_txt = f"Compte {target['username']} ({target['role']}) -> {final_user} ({new_role})"
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'COMPTE_MODIF', ?, ?, '', 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), actor_username, final_user, details_txt),
        )
        _log_activity_conn(conn, actor_username, "ADMIN", f"Compte modifié : {final_user}", details_txt)
        conn.commit()
        return True, f"Compte « {final_user} » mis à jour ({new_role})."


def delete_user_account(
    target_user_id: int,
    confirm_super_pwd: str = "",
    actor_username: str = "superadmin",
    actor_is_root: bool = False,
) -> tuple[bool, str]:
    with get_connection(sync=True) as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (int(target_user_id),)).fetchone()
        if not target:
            return False, "Compte introuvable."
        if int(target["is_root"] or 0) == 1:
            return False, "Suppression impossible : le compte Super-Admin fondateur ne peut pas être supprimé."
        if target["role"] == "superadmin":
            if not actor_is_root:
                if not verify_password(confirm_super_pwd, target["password"]):
                    return False, "Suppression refusée : le mot de passe du Super-Admin concerné est incorrect."
            sup_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'superadmin'").fetchone()[0]
            if sup_count <= 1:
                return False, "Impossible de supprimer le dernier Super-Admin du système."

        conn.execute("DELETE FROM users WHERE id = ?", (int(target_user_id),))
        details_txt = f"Suppression du compte {target['username']} ({target['role']})"
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'COMPTE_SUPPR', ?, ?, '', 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), actor_username, target["username"], details_txt),
        )
        _log_activity_conn(conn, actor_username, "ADMIN", f"Compte supprimé : {target['username']}", details_txt)
        conn.commit()
        return True, f"Compte « {target['username']} » supprimé."


def request_password_reset(username: str) -> tuple[bool, str]:
    u = clean_val(username)
    if not u:
        return False, "Saisissez votre identifiant."
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT username FROM users WHERE LOWER(username) = ?", (u.lower(),)).fetchone()
        if not row:
            return False, "Aucun compte trouvé avec cet identifiant."
        real_u = str(row["username"])
        existing = conn.execute(
            "SELECT id FROM password_resets WHERE LOWER(username) = ? AND status = 'pending'",
            (real_u.lower(),),
        ).fetchone()
        if existing:
            return True, "Une demande est déjà en attente auprès du Super-Admin."
        conn.execute(
            "INSERT INTO password_resets (username, requested_at, status) VALUES (?, ?, 'pending')",
            (real_u, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        _log_activity_conn(conn, real_u, "COMPTE", "Demande de réinitialisation MDP", "Transmise au Super-Admin")
        conn.commit()
        return True, "Demande transmise au Super-Admin. Il vous communiquera un nouveau mot de passe."


def get_pending_password_resets() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM password_resets WHERE status = 'pending' ORDER BY id DESC").fetchall()]


def resolve_password_reset(reset_id: int, new_password: str, superadmin_username: str) -> tuple[bool, str]:
    if not new_password or len(new_password.strip()) < 6:
        return False, "Le nouveau mot de passe doit faire au moins 6 caractères."
    with get_connection(sync=True) as conn:
        req = conn.execute("SELECT * FROM password_resets WHERE id = ?", (int(reset_id),)).fetchone()
        if not req:
            return False, "Demande introuvable."
        conn.execute("UPDATE users SET password = ? WHERE LOWER(username) = ?", (hash_password(new_password.strip()), req["username"].lower()))
        conn.execute("UPDATE password_resets SET status = 'resolved' WHERE id = ?", (int(reset_id),))
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'RESET_MDP', ?, ?, '', 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), superadmin_username, req["username"], "Réinitialisation du mot de passe suite à demande utilisateur"),
        )
        _log_activity_conn(conn, superadmin_username, "ADMIN", f"MDP réinitialisé : {req['username']}", "Suite à demande de récupération")
        conn.commit()
        return True, f"Nouveau mot de passe défini pour « {req['username']} »."


def dismiss_password_reset(reset_id: int):
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE password_resets SET status = 'dismissed' WHERE id = ?", (int(reset_id),))
        conn.commit()


# ------------------------------------------------------------------
# MODÉRATION, ÉDITION CATALOGUE, AUDIT & DROIT DE VETO SUPER-ADMIN
# ------------------------------------------------------------------
def _row_to_snapshot(row_dict: dict[str, Any]) -> dict[str, str]:
    return {c: clean_val(row_dict.get(c)) for c in BASE_COLS}


def get_audit_logs(limit: int = 80) -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]


def get_pending_syntheses() -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM syntheses_pending ORDER BY id DESC").fetchall()]


def approve_pending_synthese(pending_id: int, admin_username: str) -> str:
    cols_str = ", ".join([f"[{c}]" for c in BASE_COLS])
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT * FROM syntheses_pending WHERE id = ?", (int(pending_id),)).fetchone()
        if not row:
            return ""
        d = dict(row)
        snap = _row_to_snapshot(d)
        prod = snap["Produit final"] or "Sans nom"
        vals = [snap[c] for c in BASE_COLS]
        cur = conn.execute(
            f"INSERT INTO syntheses ({cols_str}) VALUES ({', '.join(['?'] * len(BASE_COLS))})",
            tuple(vals),
        )
        new_id = cur.lastrowid
        conn.execute("DELETE FROM syntheses_pending WHERE id = ?", (int(pending_id),))
        sync_inventory_with_syntheses(conn)
        payload = json.dumps({"synth_id": new_id, "snapshot": snap}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'VALIDATION', ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin_username, prod, f"Validation fiche proposée #{pending_id} (CAS: {snap['Numéro CAS']})", payload),
        )
        _log_activity_conn(conn, admin_username, "CATALOGUE", f"Fiche validée : {prod}", f"Proposition #{pending_id} publiée")
        conn.commit()
        return prod


def reject_pending_synthese(pending_id: int, admin_username: str) -> str:
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT * FROM syntheses_pending WHERE id = ?", (int(pending_id),)).fetchone()
        if not row:
            return ""
        snap = _row_to_snapshot(dict(row))
        prod = snap["Produit final"] or f"#{pending_id}"
        conn.execute("DELETE FROM syntheses_pending WHERE id = ?", (int(pending_id),))
        payload = json.dumps({"snapshot": snap}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'REJET', ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin_username, prod, f"Rejet de la proposition #{pending_id}", payload),
        )
        _log_activity_conn(conn, admin_username, "CATALOGUE", f"Proposition rejetée : {prod}", f"Proposition #{pending_id}")
        conn.commit()
        return prod


def update_synthese_by_id(synth_id: int, new_data: dict[str, Any], admin_username: str) -> str:
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT * FROM syntheses WHERE id = ?", (int(synth_id),)).fetchone()
        if not row:
            return ""
        before_snap = _row_to_snapshot(dict(row))
        after_snap = {c: clean_val(new_data.get(c, before_snap[c])) for c in BASE_COLS}
        set_sql = ", ".join([f"[{c}] = ?" for c in BASE_COLS])
        vals = [after_snap[c] for c in BASE_COLS] + [int(synth_id)]
        conn.execute(f"UPDATE syntheses SET {set_sql} WHERE id = ?", tuple(vals))
        sync_inventory_with_syntheses(conn)
        changed_cols = [c for c in BASE_COLS if before_snap[c] != after_snap[c]]
        details = f"Champs modifiés : {', '.join(changed_cols) if changed_cols else 'aucun'}"
        payload = json.dumps({"synth_id": int(synth_id), "before": before_snap, "after": after_snap}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'MODIFICATION', ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin_username, after_snap["Produit final"] or f"#{synth_id}", details, payload),
        )
        _log_activity_conn(conn, admin_username, "CATALOGUE", f"Fiche modifiée : {after_snap['Produit final']}", details)
        conn.commit()
        return after_snap["Produit final"]


def delete_synthese_by_id(synth_id: int, admin_username: str) -> str:
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT * FROM syntheses WHERE id = ?", (int(synth_id),)).fetchone()
        if not row:
            return ""
        snap = _row_to_snapshot(dict(row))
        prod = snap["Produit final"] or f"#{synth_id}"
        conn.execute("DELETE FROM syntheses WHERE id = ?", (int(synth_id),))
        payload = json.dumps({"snapshot": snap}, ensure_ascii=False)
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'SUPPRESSION', ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), admin_username, prod, f"Suppression de la fiche #{synth_id} du catalogue", payload),
        )
        _log_activity_conn(conn, admin_username, "CATALOGUE", f"Fiche supprimée : {prod}", f"Fiche #{synth_id}")
        conn.commit()
        return prod


def veto_audit_action(log_id: int, superadmin_username: str, send_warning: bool = False) -> tuple[bool, str]:
    cols_str = ", ".join([f"[{c}]" for c in BASE_COLS])
    with get_connection(sync=True) as conn:
        log = conn.execute("SELECT * FROM admin_audit_logs WHERE id = ?", (int(log_id),)).fetchone()
        if not log:
            return False, "Entrée d'audit introuvable."
        if int(log["reverted"] or 0) == 1:
            return False, "Cette décision a déjà été annulée."
        raw_payload = clean_val(log["payload_json"])
        if not raw_payload:
            return False, "Ancienne entrée sans instantané de sauvegarde (non réversible automatiquement)."

        data = json.loads(raw_payload)
        act = clean_val(log["action_type"]).upper()
        prod = clean_val(log["product_name"])

        if act == "VALIDATION":
            snap = data.get("snapshot", {})
            sid = data.get("synth_id")
            if sid:
                conn.execute("DELETE FROM syntheses WHERE id = ?", (int(sid),))
            else:
                conn.execute("DELETE FROM syntheses WHERE [Produit final] = ?", (prod,))
            vals = [snap.get(c, "") for c in BASE_COLS]
            conn.execute(f"INSERT INTO syntheses_pending ({cols_str}) VALUES ({', '.join(['?'] * len(BASE_COLS))})", tuple(vals))
            msg = f"Veto appliqué : « {prod} » retirée du catalogue et replacée en modération."

        elif act == "REJET":
            snap = data.get("snapshot", {})
            vals = [snap.get(c, "") for c in BASE_COLS]
            conn.execute(f"INSERT INTO syntheses_pending ({cols_str}) VALUES ({', '.join(['?'] * len(BASE_COLS))})", tuple(vals))
            msg = f"Veto appliqué : la proposition rejetée « {prod} » a été restaurée en modération."

        elif act == "SUPPRESSION":
            snap = data.get("snapshot", {})
            vals = [snap.get(c, "") for c in BASE_COLS]
            conn.execute(f"INSERT INTO syntheses ({cols_str}) VALUES ({', '.join(['?'] * len(BASE_COLS))})", tuple(vals))
            sync_inventory_with_syntheses(conn)
            msg = f"Veto appliqué : la fiche supprimée « {prod} » a été restaurée dans le catalogue."

        elif act == "MODIFICATION":
            before = data.get("before", {})
            sid = data.get("synth_id")
            set_sql = ", ".join([f"[{c}] = ?" for c in BASE_COLS])
            vals = [before.get(c, "") for c in BASE_COLS]
            if sid:
                conn.execute(f"UPDATE syntheses SET {set_sql} WHERE id = ?", tuple(vals + [int(sid)]))
            else:
                conn.execute(f"UPDATE syntheses SET {set_sql} WHERE [Produit final] = ?", tuple(vals + [prod]))
            msg = f"Veto appliqué : les modifications sur « {prod} » ont été annulées."
        else:
            return False, f"Action « {act} » non réversible."

        conn.execute("UPDATE admin_audit_logs SET reverted = 1 WHERE id = ?", (int(log_id),))

        warn_note = ""
        target_admin = clean_val(log["admin_username"])
        if send_warning and target_admin and target_admin.lower() != superadmin_username.lower():
            conn.execute(
                "UPDATE users SET warnings = COALESCE(warnings, 0) + 1, warning_acknowledged = 0 WHERE LOWER(username) = ?",
                (target_admin.lower(),),
            )
            warn_note = f" (+ avertissement envoyé à {target_admin})"

        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'VETO', ?, ?, '', 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), superadmin_username, prod, f"Annulation de {act} #{log_id} ({target_admin}){warn_note}"),
        )
        _log_activity_conn(conn, superadmin_username, "ADMIN", f"Veto appliqué sur {prod}", f"Annulation de {act} #{log_id}{warn_note}")
        conn.commit()
        return True, msg + warn_note


def get_stock_alerts(unread_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM stock_alerts WHERE is_read = 0 ORDER BY id DESC" if unread_only else "SELECT * FROM stock_alerts ORDER BY id DESC LIMIT 60"
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def mark_all_alerts_read():
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE stock_alerts SET is_read = 1 WHERE is_read = 0")
        conn.commit()


def get_zero_result_searches(limit: int = 30) -> list[dict[str, Any]]:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT timestamp, query_text, filter_reaction, filter_reactif FROM search_logs WHERE results_count = 0 AND TRIM(COALESCE(query_text, '')) != '' ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]