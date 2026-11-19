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
        cur.execute("CREATE TABLE IF NOT EXISTS admin_audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, admin_username TEXT, action_type TEXT, product_name TEXT, full_details TEXT, payload_json TEXT, reverted INTEGER DEFAULT 0)")
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
            "ALTER TABLE admin_audit_logs ADD COLUMN payload_json TEXT",
            "ALTER TABLE admin_audit_logs ADD COLUMN reverted INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN warnings INTEGER DEFAULT 0",
            "ALTER TABLE users ADD COLUMN warning_acknowledged INTEGER DEFAULT 1",
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
def get_all_syntheses() -> list:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM syntheses ORDER BY [Produit final] ASC").fetchall()]


def get_favorites(username: str) -> set:
    with get_connection(sync=False) as conn:
        rows = conn.execute("SELECT product_name FROM favorites WHERE username = ?", (username,)).fetchall()
        return {r["product_name"] for r in rows}


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
        # Évite d'enregistrer en double la même requête exacte dans les 2 dernières minutes
        last = conn.execute(
            "SELECT query_text FROM search_logs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last and clean_val(last["query_text"]).lower() == q.lower():
            return
        conn.execute(
            "INSERT INTO search_logs (timestamp, query_text, filter_produit, filter_reaction, filter_reactif, results_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), q, f_prod, f_rx, f_rea, results_count),
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


# ------------------------------------------------------------------
# INVENTAIRE & ALERTES STOCK
# ------------------------------------------------------------------
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


def get_all_inventory() -> list:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM inventory ORDER BY CASE WHEN quantite <= 0 THEN 0 WHEN quantite <= seuil_alerte THEN 1 ELSE 2 END, nom_substance ASC"
            ).fetchall()
        ]


def _maybe_create_stock_alert(conn, nom: str, qty: float, unite: str, seuil: float):
    if qty <= seuil:
        level = "RUPTURE" if qty <= 0 else "SEUIL CRITIQUE"
        conn.execute(
            "INSERT INTO stock_alerts (timestamp, nom_substance, alert_level, quantite, unite, seuil, is_read) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), nom, level, round(qty, 2), unite, round(seuil, 2)),
        )


def upsert_inventory_item(nom: str, categorie: str, quantite: float, unite: str, seuil: float, emplacement: str, densite: float, item_id=None):
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    qty_clean = max(0.0, round(float(quantite), 2))
    seuil_clean = max(0.0, round(float(seuil), 2))
    dens_clean = max(0.1, round(float(densite or 1.0), 3))
    with get_connection(sync=True) as conn:
        if item_id is not None:
            conn.execute(
                "UPDATE inventory SET nom_substance=?, categorie=?, quantite=?, unite=?, seuil_alerte=?, emplacement=?, derniere_maj=?, densite=? WHERE id=?",
                (nom.strip(), categorie, qty_clean, unite, seuil_clean, emplacement.strip(), now_s, dens_clean, int(item_id)),
            )
        else:
            conn.execute(
                "INSERT INTO inventory (nom_substance, categorie, quantite, unite, seuil_alerte, emplacement, derniere_maj, densite) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(nom_substance) DO UPDATE SET categorie=excluded.categorie, quantite=excluded.quantite, unite=excluded.unite, "
                "seuil_alerte=excluded.seuil_alerte, emplacement=excluded.emplacement, derniere_maj=excluded.derniere_maj, densite=excluded.densite",
                (nom.strip(), categorie, qty_clean, unite, seuil_clean, emplacement.strip(), now_s, dens_clean),
            )
        _maybe_create_stock_alert(conn, nom.strip(), qty_clean, unite, seuil_clean)
        conn.commit()


def adjust_inventory_quantity(item_id: int, delta: float):
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M")
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT nom_substance, quantite, unite, seuil_alerte FROM inventory WHERE id = ?", (int(item_id),)).fetchone()
        if not row:
            return
        new_qty = max(0.0, round(float(row["quantite"] or 0.0) + float(delta), 2))
        conn.execute("UPDATE inventory SET quantite = ?, derniere_maj = ? WHERE id = ?", (new_qty, now_s, int(item_id)))
        _maybe_create_stock_alert(conn, row["nom_substance"], new_qty, row["unite"] or "g", float(row["seuil_alerte"] or 0.0))
        conn.commit()


def quick_stock_movement(nom_substance: str, amount: float, input_unit: str, is_addition: bool) -> tuple:
    """Mouvement rapide (Retirer / Ajouter) en g ou mL avec conversion automatique via densité."""
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

        # Conversion unité saisie -> unité stock
        u_in = clean_val(input_unit).lower()
        u_st = stock_unit.lower()
        converted = amt
        if u_in == "g" and u_st == "ml" and dens > 0:
            converted = amt / dens
        elif u_in == "ml" and u_st == "g":
            converted = amt * dens
        elif u_in == "g" and u_st == "kg":
            converted = amt / 1000.0
        elif u_in == "ml" and u_st == "l":
            converted = amt / 1000.0
        elif u_in == "g" and u_st == "l" and dens > 0:
            converted = (amt / dens) / 1000.0
        elif u_in == "ml" and u_st == "kg":
            converted = (amt * dens) / 1000.0

        delta = converted if is_addition else -converted
        new_qty = max(0.0, round(float(row["quantite"] or 0.0) + delta, 2))
        conn.execute("UPDATE inventory SET quantite = ?, derniere_maj = ? WHERE id = ?", (new_qty, now_s, row["id"]))
        _maybe_create_stock_alert(conn, row["nom_substance"], new_qty, stock_unit, float(row["seuil_alerte"] or 0.0))
        conn.commit()
        verb = "Ajouté" if is_addition else "Prélevé"
        return True, f"{verb} {converted:.2f} {stock_unit} sur « {row['nom_substance']} » (nouveau stock : {new_qty:g} {stock_unit})."


def deduct_inventory_by_name(nom_substance: str, amount_g: float):
    ok, _msg = quick_stock_movement(nom_substance, amount_g, "g", is_addition=False)
    return ok


def delete_inventory_item(item_id: int):
    with get_connection(sync=True) as conn:
        conn.execute("DELETE FROM inventory WHERE id = ?", (int(item_id),))
        conn.commit()


# ------------------------------------------------------------------
# CAHIER DE LABORATOIRE
# ------------------------------------------------------------------
def get_all_labo_entries() -> list:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM lab_notebook ORDER BY id DESC").fetchall()]


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
):
    with get_connection(sync=True) as conn:
        conn.execute(
            "INSERT INTO lab_notebook (date_essai, operateur, produit_cible, quantites_engagees, masse_theorique, "
            "masse_obtenue, rendement_reel, rendement_theorique, statut, observations, attachment_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                date_essai, operateur, produit_cible, quantites_engagees,
                round(float(masse_theorique), 2), round(float(masse_obtenue), 2),
                round(float(rendement_reel), 1), rendement_theorique, statut, observations, attachment_path,
            ),
        )
        conn.commit()


def delete_labo_entry(entry_id: int):
    with get_connection(sync=True) as conn:
        conn.execute("DELETE FROM lab_notebook WHERE id = ?", (int(entry_id),))
        conn.commit()


# ------------------------------------------------------------------
# UTILISATEURS, MOT DE PASSE OUBLIÉ & AVERTISSEMENTS
# ------------------------------------------------------------------
def authenticate_user(username: str, password: str):
    with get_connection(sync=False) as conn:
        row = conn.execute(
            "SELECT id, username, role, warnings, warning_acknowledged FROM users WHERE LOWER(username) = ? AND password = ?",
            (clean_val(username).lower(), password),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str):
    with get_connection(sync=False) as conn:
        row = conn.execute(
            "SELECT id, username, role, warnings, warning_acknowledged FROM users WHERE LOWER(username) = ?",
            (clean_val(username).lower(),),
        ).fetchone()
        return dict(row) if row else None


def acknowledge_user_warnings(username: str):
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE users SET warning_acknowledged = 1 WHERE LOWER(username) = ?", (clean_val(username).lower(),))
        conn.commit()


def get_all_users() -> list:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT id, username, role, warnings, warning_acknowledged FROM users ORDER BY CASE role WHEN 'superadmin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, username ASC"
            ).fetchall()
        ]


def create_user(username: str, password: str, role: str = "admin") -> bool:
    try:
        with get_connection(sync=True) as conn:
            conn.execute(
                "INSERT INTO users (username, password, role, warnings, warning_acknowledged) VALUES (?, ?, ?, 0, 1)",
                (username.strip(), password, role),
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False


def update_user_account(target_user_id: int, new_username: str, new_password: str, new_role: str, confirm_super_pwd: str = "", actor_username: str = "superadmin") -> tuple:
    """Modifie ou rétrograde un compte. Si la cible est Super-Admin, exige son mot de passe actuel."""
    with get_connection(sync=True) as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (int(target_user_id),)).fetchone()
        if not target:
            return False, "Compte introuvable."
        if target["role"] == "superadmin":
            if confirm_super_pwd != target["password"]:
                return False, "Action refusée : le mot de passe du Super-Admin concerné est incorrect."
            if new_role != "superadmin":
                sup_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'superadmin'").fetchone()[0]
                if sup_count <= 1:
                    return False, "Impossible de rétrograder le dernier Super-Admin actif."
        final_user = clean_val(new_username) or target["username"]
        final_pwd = new_password if new_password else target["password"]
        try:
            conn.execute(
                "UPDATE users SET username = ?, password = ?, role = ? WHERE id = ?",
                (final_user, final_pwd, new_role, int(target_user_id)),
            )
        except sqlite3.IntegrityError:
            return False, "Cet identifiant est déjà utilisé."
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'COMPTE_MODIF', ?, ?, '', 1)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                actor_username,
                final_user,
                f"Compte {target['username']} ({target['role']}) -> {final_user} ({new_role})",
            ),
        )
        conn.commit()
        return True, f"Compte « {final_user} » mis à jour ({new_role})."


def delete_user_account(target_user_id: int, confirm_super_pwd: str = "", actor_username: str = "superadmin") -> tuple:
    """Supprime un compte. Si la cible est Super-Admin, exige son mot de passe actuel."""
    with get_connection(sync=True) as conn:
        target = conn.execute("SELECT * FROM users WHERE id = ?", (int(target_user_id),)).fetchone()
        if not target:
            return False, "Compte introuvable."
        if target["role"] == "superadmin":
            if confirm_super_pwd != target["password"]:
                return False, "Suppression refusée : le mot de passe du Super-Admin concerné est incorrect."
            sup_count = conn.execute("SELECT COUNT(*) FROM users WHERE role = 'superadmin'").fetchone()[0]
            if sup_count <= 1:
                return False, "Impossible de supprimer le dernier Super-Admin du système."
        conn.execute("DELETE FROM users WHERE id = ?", (int(target_user_id),))
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'COMPTE_SUPPR', ?, ?, '', 1)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                actor_username,
                target["username"],
                f"Suppression du compte {target['username']} ({target['role']})",
            ),
        )
        conn.commit()
        return True, f"Compte « {target['username']} » supprimé."


def request_password_reset(username: str) -> tuple:
    u = clean_val(username)
    if not u:
        return False, "Saisissez votre identifiant."
    with get_connection(sync=True) as conn:
        row = conn.execute("SELECT username FROM users WHERE LOWER(username) = ?", (u.lower(),)).fetchone()
        if not row:
            return False, "Aucun compte trouvé avec cet identifiant."
        real_u = row["username"]
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
        conn.commit()
        return True, "Demande transmise au Super-Admin. Il vous communiquera un nouveau mot de passe."


def get_pending_password_resets() -> list:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM password_resets WHERE status = 'pending' ORDER BY id DESC").fetchall()]


def resolve_password_reset(reset_id: int, new_password: str, superadmin_username: str) -> tuple:
    if not new_password or len(new_password.strip()) < 4:
        return False, "Le nouveau mot de passe doit faire au moins 4 caractères."
    with get_connection(sync=True) as conn:
        req = conn.execute("SELECT * FROM password_resets WHERE id = ?", (int(reset_id),)).fetchone()
        if not req:
            return False, "Demande introuvable."
        conn.execute("UPDATE users SET password = ? WHERE LOWER(username) = ?", (new_password.strip(), req["username"].lower()))
        conn.execute("UPDATE password_resets SET status = 'resolved' WHERE id = ?", (int(reset_id),))
        conn.execute(
            "INSERT INTO admin_audit_logs (timestamp, admin_username, action_type, product_name, full_details, payload_json, reverted) "
            "VALUES (?, ?, 'RESET_MDP', ?, ?, '', 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), superadmin_username, req["username"], "Réinitialisation du mot de passe suite à demande utilisateur"),
        )
        conn.commit()
        return True, f"Nouveau mot de passe défini pour « {req['username']} »."


def dismiss_password_reset(reset_id: int):
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE password_resets SET status = 'dismissed' WHERE id = ?", (int(reset_id),))
        conn.commit()


# ------------------------------------------------------------------
# MODÉRATION, ÉDITION CATALOGUE, AUDIT & DROIT DE VETO SUPER-ADMIN
# ------------------------------------------------------------------
def _row_to_snapshot(row_dict: dict) -> dict:
    return {c: clean_val(row_dict.get(c)) for c in BASE_COLS}


def get_audit_logs(limit: int = 80) -> list:
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM admin_audit_logs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()]


def get_pending_syntheses() -> list:
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
        conn.commit()
        return prod


def update_synthese_by_id(synth_id: int, new_data: dict, admin_username: str) -> str:
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
        conn.commit()
        return prod


def veto_audit_action(log_id: int, superadmin_username: str, send_warning: bool = False) -> tuple:
    """Annule une décision (VALIDATION, REJET, SUPPRESSION, MODIFICATION) et avertit l'admin si demandé."""
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
        conn.commit()
        return True, msg + warn_note


def get_stock_alerts(unread_only: bool = False) -> list:
    sql = "SELECT * FROM stock_alerts WHERE is_read = 0 ORDER BY id DESC" if unread_only else "SELECT * FROM stock_alerts ORDER BY id DESC LIMIT 60"
    with get_connection(sync=False) as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def mark_all_alerts_read():
    with get_connection(sync=True) as conn:
        conn.execute("UPDATE stock_alerts SET is_read = 1 WHERE is_read = 0")
        conn.commit()


def get_zero_result_searches(limit: int = 30) -> list:
    with get_connection(sync=False) as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT timestamp, query_text, filter_reaction, filter_reactif FROM search_logs WHERE results_count = 0 AND TRIM(COALESCE(query_text, '')) != '' ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        ]