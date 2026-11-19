import base64
import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime

from chem_data import BASE_COLS, FAST_DENSITY_MAP, clean_val, get_known_density

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "chimie_db.sqlite")


def sync_db_to_github():
    """Sauvegarde automatique de chimie_db.sqlite sur GitHub si configuré dans les variables d'environnement (Render)."""
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO")
    if not token or not repo or not os.path.exists(DB_FILE):
        return
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
                return
        with open(DB_FILE, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {
            "message": f"Auto-save DB ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})",
            "content": b64,
        }
        if sha:
            payload["sha"] = sha
        urllib.request.urlopen(
            urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="PUT"),
            timeout=12,
        )
    except Exception:
        pass


class SyncedConnection(sqlite3.Connection):
    def commit(self):
        super().commit()
        sync_db_to_github()


def get_connection(sync: bool = True):
    conn = sqlite3.connect(DB_FILE, timeout=15, factory=SyncedConnection if sync else sqlite3.Connection)
    conn.row_factory = sqlite3.Row
    return conn


def sync_inventory_with_syntheses(conn):
    cur = conn.cursor()
    rows = [dict(r) for r in cur.execute("SELECT * FROM syntheses").fetchall()]
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    cas_by_prod = {}

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
        cur.execute("CREATE TABLE IF NOT EXISTS admin_audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, admin_username TEXT, action_type TEXT, product_name TEXT, full_details TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS search_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, query_text TEXT, filter_produit TEXT, filter_reaction TEXT, filter_reactif TEXT, results_count INTEGER)")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, password TEXT, role TEXT, warnings INTEGER DEFAULT 0, warning_acknowledged INTEGER DEFAULT 1)")
        cur.execute("CREATE TABLE IF NOT EXISTS password_resets (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, requested_at TEXT, status TEXT DEFAULT 'pending')")
        cur.execute("CREATE TABLE IF NOT EXISTS favorites (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, product_name TEXT, UNIQUE(username, product_name))")
        cur.execute("CREATE TABLE IF NOT EXISTS lab_notebook (id INTEGER PRIMARY KEY AUTOINCREMENT, date_essai TEXT, operateur TEXT, produit_cible TEXT, quantites_engagees TEXT, masse_theorique REAL, masse_obtenue REAL, rendement_reel REAL, rendement_theorique TEXT, statut TEXT, observations TEXT, attachment_path TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, nom_substance TEXT UNIQUE, categorie TEXT, quantite REAL, unite TEXT, seuil_alerte REAL, emplacement TEXT, derniere_maj TEXT, densite REAL DEFAULT 1.0)")
        cur.execute("CREATE TABLE IF NOT EXISTS stock_alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, nom_substance TEXT, alert_level TEXT, quantite REAL, unite TEXT, seuil REAL, is_read INTEGER DEFAULT 0)")

        for alter_sql in (
            "ALTER TABLE lab_notebook ADD COLUMN attachment_path TEXT",
            "ALTER TABLE inventory ADD COLUMN densite REAL DEFAULT 1.0",
        ):
            try:
                cur.execute(alter_sql)
            except Exception:
                pass

        if cur.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            cur.executemany(
                "INSERT INTO users (username, password, role, warnings, warning_acknowledged) VALUES (?, ?, ?, 0, 1)",
                [("superadmin", "super2026", "superadmin"), ("admin", "chimie2026", "admin")],
            )

        sync_inventory_with_syntheses(conn)
        conn.commit()


def _safe_count(cur, query: str) -> int:
    try:
        row = cur.execute(query).fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:
        return 0


def read_db_status() -> dict:
    if not os.path.exists(DB_FILE):
        return {"connected": False, "molecules": 0, "inventory": 0, "low_stock": 0, "eln": 0, "pending": 0, "alerts": 0}
    with get_connection(sync=False) as conn:
        cur = conn.cursor()
        return {
            "connected": True,
            "molecules": _safe_count(cur, "SELECT COUNT(*) FROM syntheses"),
            "inventory": _safe_count(cur, "SELECT COUNT(*) FROM inventory"),
            "low_stock": _safe_count(cur, "SELECT COUNT(*) FROM inventory WHERE quantite <= seuil_alerte"),
            "eln": _safe_count(cur, "SELECT COUNT(*) FROM lab_notebook"),
            "pending": _safe_count(cur, "SELECT COUNT(*) FROM syntheses_pending"),
            "alerts": _safe_count(cur, "SELECT COUNT(*) FROM stock_alerts WHERE is_read = 0"),
        }


def get_all_syntheses() -> list:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM syntheses ORDER BY [Produit final] ASC").fetchall()]


def get_inventory_map() -> dict:
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


def get_favorites(username: str) -> set:
    with get_connection(sync=False) as conn:
        rows = conn.execute("SELECT product_name FROM favorites WHERE username = ?", (username,)).fetchall()
        return {r["product_name"] for r in rows}


def toggle_favorite(username: str, product_name: str) -> bool:
    """Ajoute ou retire un favori. Retourne True s'il est désormais en favori."""
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
    with get_connection(sync=False) as conn:
        conn.execute(
            "INSERT INTO search_logs (timestamp, query_text, filter_produit, filter_reaction, filter_reactif, results_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), query_text, f_prod, f_rx, f_rea, results_count),
        )
        conn.commit()


def insert_pending_synthese(values_16: list):
    cols_str = ", ".join([f"[{c}]" for c in BASE_COLS])
    with get_connection(sync=True) as conn:
        conn.execute(
            f"INSERT INTO syntheses_pending ({cols_str}) VALUES ({', '.join(['?'] * 16)})",
            tuple(values_16),
        )
        conn.commit()
        