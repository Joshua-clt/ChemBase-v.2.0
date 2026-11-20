import html
import os
from typing import Any
from fastapi.responses import HTMLResponse, JSONResponse
from nicegui import app, ui

from chem_data import (
    LABO_FILES_DIR,
    build_3dmol_html,
    clean_val,
    generate_bottle_label_html,
    generate_labo_entry_html,
    generate_molecule_html,
)
from database import (
    authenticate_user_checked,
    change_own_password,
    get_all_inventory,
    get_all_labo_entries,
    get_all_syntheses,
    get_lab_registration_settings,
    get_user_by_username,
    init_db,
    log_activity,
    read_db_status,
    register_researcher,
    request_password_reset,
)
from theme import LOGO_SVG, THEME_TOGGLE_SVGS, inject_theme, safe_html
from views_admin_analytics import build_analytics_and_admin_views
from views_catalog import build_catalog_and_proposal_views
from views_labo import build_labo_view
from views_stocks import build_stocks_view

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(LABO_FILES_DIR, exist_ok=True)

init_db()
app.add_static_files("/images", IMAGES_DIR)


# ------------------------------------------------------------------
# ROUTES API (3D, ÉTIQUETTES, IMPRESSION PDF & PONT FUTUR CHEMSTUDIO)
# ------------------------------------------------------------------
@app.get("/api/3d", response_class=HTMLResponse)
def serve_3d_viewer(cas: str = "", dark: int = 1):
    return HTMLResponse(content=build_3dmol_html(cas, dark_mode=bool(dark)))


@app.get("/api/label", response_class=HTMLResponse)
def serve_bottle_label(
    nom: str = "",
    cas: str = "",
    formule: str = "",
    pictos: str = "",
    stockage: str = "",
    op: str = "chercheur",
):
    return HTMLResponse(
        content=generate_bottle_label_html(
            nom=nom,
            cas=cas,
            formule=formule,
            pictos=pictos,
            stockage=stockage,
            operateur=op,
        )
    )


@app.get("/api/print/fiche/{synth_id}", response_class=HTMLResponse)
def serve_print_fiche(synth_id: int):
    row = next((r for r in get_all_syntheses() if int(r["id"]) == int(synth_id)), None)
    if not row:
        return HTMLResponse(content="<html><body><h3>Fiche introuvable.</h3></body></html>", status_code=404)
    return HTMLResponse(content=generate_molecule_html(row).decode("utf-8"))


@app.get("/api/print/labo/{entry_id}", response_class=HTMLResponse)
def serve_print_labo(entry_id: int):
    entry = next((e for e in get_all_labo_entries() if int(e["id"]) == int(entry_id)), None)
    if not entry:
        return HTMLResponse(content="<html><body><h3>Essai introuvable.</h3></body></html>", status_code=404)
    return HTMLResponse(content=generate_labo_entry_html(entry))


@app.get("/api/v1/catalog")
def api_v1_catalog(q: str = ""):
    """Point d'entrée JSON léger pour le futur module externe ChemStudio."""
    q_low = clean_val(q).lower()
    rows = get_all_syntheses()
    items = []
    for r in rows:
        item = {
            "id": r.get("id"),
            "produit": clean_val(r.get("Produit final")),
            "cas": clean_val(r.get("Numéro CAS")),
            "formule": clean_val(r.get("Formule brute & masse")),
            "reaction_1": clean_val(r.get("Réaction 1")),
            "reaction_2": clean_val(r.get("Réaction 2")),
            "reactifs": [clean_val(r.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(r.get(f"Réactifs {i}"))],
            "rendement": clean_val(r.get("Rendement")),
            "sgh": clean_val(r.get("Pictogrammes danger")),
        }
        if not q_low or q_low in item["produit"].lower() or q_low in item["cas"].lower():
            items.append(item)
    return JSONResponse(content={"count": len(items), "items": items})


@app.get("/api/v1/molecule/{cas}")
def api_v1_molecule(cas: str):
    """Détail JSON d'une molécule par CAS pour le futur ChemStudio."""
    target = clean_val(cas).lower()
    row = next((r for r in get_all_syntheses() if clean_val(r.get("Numéro CAS")).lower() == target), None)
    if not row:
        return JSONResponse(content={"error": "Molécule introuvable"}, status_code=404)
    return JSONResponse(content=dict(row))


def find_favicon():
    for folder in (BASE_DIR, IMAGES_DIR):
        for ext in ("png", "jpg", "jpeg", "ico"):
            path = os.path.join(folder, f"chembase_logo.{ext}")
            if os.path.exists(path):
                return path
    return None


@ui.page("/")
def index_page(new_cas: str = "", new_name: str = "", new_smiles: str = ""):
    inject_theme()

    saved_dark = bool(app.storage.user.get("dark", True))
    saved_user_name = str(app.storage.user.get("auth_username", "") or "")
    restored_user = get_user_by_username(saved_user_name) if saved_user_name else None

    dark = ui.dark_mode(value=saved_dark)
    state: dict[str, Any] = {
        "tab": "recherche",
        "dark": saved_dark,
        "username": restored_user["username"] if restored_user else "",
        "auth_user": restored_user,
    }
    pending_prefill: dict[str, str] = {
        "cas": clean_val(new_cas),
        "name": clean_val(new_name),
        "smiles": clean_val(new_smiles),
    }

    init_mode = "dark" if saved_dark else "light"
    ui.timer(0.05, lambda: ui.run_javascript(f'window.cbApplyTheme("{init_mode}");'), once=True)

    page_root = ui.element("div").style("width:100%;min-height:100vh;")
    active_refresh_hooks: dict[str, Any] = {}

    def toggle_theme():
        state["dark"] = not state["dark"]
        app.storage.user["dark"] = state["dark"]
        mode = "dark" if state["dark"] else "light"
        ui.run_javascript(f'window.cbToggleThemeWave("{mode}");')

        def sync_after_wave():
            dark.value = state["dark"]
            if state["tab"] in ("dashboard", "labo"):
                hook = active_refresh_hooks.get(state["tab"])
                if callable(hook):
                    hook()

        ui.timer(0.1, sync_after_wave, once=True)

    # ------------------------------------------------------------------
    # PORTAIL DE CONNEXION OBLIGATOIRE (CONNEXION / CODE LABO / MDP OUBLIÉ)
    # ------------------------------------------------------------------
    def render_auth_portal():
        page_root.clear()
        active_refresh_hooks.clear()
        auth_mode: dict[str, str] = {"view": "login"}

        with page_root:
            with ui.element("div").classes("auth-shell"):
                with ui.element("div").style("position:fixed;top:18px;right:24px;z-index:10;"):
                    with (
                        ui.element("button")
                        .classes("glass-btn icon-btn")
                        .props('id="theme-toggle" title="Changer de thème" aria-label="Changer de thème"')
                        .on("click", toggle_theme)
                    ):
                        safe_html(THEME_TOGGLE_SVGS)

                with ui.element("div").classes("auth-card"):
                    with ui.element("div").style("display:flex;flex-direction:column;align-items:center;text-align:center;"):
                        with ui.element("div").classes("cb-logo-wrap").style("transform:scale(0.88);margin-bottom:-6px;"):
                            safe_html(LOGO_SVG)
                        safe_html(
                            '<div class="section-kicker">LABORATORY INFORMATION &amp; R&amp;D SYSTEM</div>'
                            '<h1 style="margin:4px 0 2px 0;font-size:1.85rem;font-weight:800;display:flex;align-items:center;gap:8px;">'
                            'ChemBase <span class="version-pill">v2.0</span></h1>'
                            '<p class="muted-small" style="margin:4px 0 0 0;">Accès authentifié requis · Traçabilité complète du laboratoire</p>'
                        )

                    form_slot = ui.element("div")

                    def draw_auth_form():
                        form_slot.clear()
                        reg_cfg = get_lab_registration_settings()

                        with form_slot:
                            if auth_mode["view"] in ("login", "register"):
                                with ui.element("div").classes("auth-tabs"):
                                    cls_in = "auth-tab active" if auth_mode["view"] == "login" else "auth-tab"
                                    cls_reg = "auth-tab active" if auth_mode["view"] == "register" else "auth-tab"
                                    with ui.element("button").classes(cls_in).on("click", lambda _e: (auth_mode.update(view="login"), draw_auth_form())):
                                        safe_html("Connexion")
                                    with ui.element("button").classes(cls_reg).on("click", lambda _e: (auth_mode.update(view="register"), draw_auth_form())):
                                        safe_html("Créer un compte")

                            if auth_mode["view"] == "login":
                                in_u = ui.input(label="Identifiant", placeholder="Votre identifiant").props("outlined dense autofocus").style("width:100%;margin-bottom:10px;")
                                in_p = ui.input(label="Mot de passe", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:16px;")

                                def do_login(_e=None):
                                    user, msg = authenticate_user_checked(str(in_u.value or ""), str(in_p.value or ""))
                                    if not user:
                                        ui.notify(msg, type="negative")
                                        return
                                    state["auth_user"] = user
                                    state["username"] = user["username"]
                                    state["tab"] = "recherche"
                                    app.storage.user["auth_username"] = user["username"]
                                    ui.notify(f"Bienvenue {user['username']} ({user['role']}).", type="positive")
                                    render_main_app()

                                in_p.on("keydown.enter", do_login)
                                with ui.element("button").classes("glass-btn glass-btn-accent").style("width:100%;padding:11px;font-size:0.9rem;").on("click", do_login):
                                    safe_html("Se connecter à ChemBase")

                                with ui.element("div").style("text-align:center;margin-top:14px;"):
                                    with ui.element("button").style("background:transparent;border:none;color:var(--cyan);font-size:0.80rem;cursor:pointer;").on(
                                        "click", lambda _e: (auth_mode.update(view="forgot"), draw_auth_form())
                                    ):
                                        safe_html("Mot de passe oublié ?")

                            elif auth_mode["view"] == "register":
                                if not reg_cfg["open"]:
                                    safe_html(
                                        '<div class="detail-box" style="margin-bottom:0;">'
                                        '<strong style="color:var(--warn);">Inscriptions temporairement fermées</strong>'
                                        '<p class="muted-small" style="margin-top:6px;">Contactez le Super-Admin du laboratoire pour ouvrir votre accès.</p></div>'
                                    )
                                else:
                                    safe_html('<p class="muted-small" style="margin:0 0 12px 0;">Inscription instantanée (rôle <strong>chercheur</strong>) réservée aux membres disposant du Code Laboratoire.</p>')
                                    reg_u = ui.input(label="Choisir un identifiant *", placeholder="Ex : j.dupont").props("outlined dense autofocus").style("width:100%;margin-bottom:10px;")
                                    reg_p = ui.input(label="Mot de passe (min. 6 caractères) *", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                                    reg_p2 = ui.input(label="Confirmer le mot de passe *", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                                    reg_code = ui.input(label="Code Laboratoire *", placeholder="Demandé auprès du responsable labo").props("outlined dense").style("width:100%;margin-bottom:16px;")

                                    def do_register(_e=None):
                                        if str(reg_p.value or "") != str(reg_p2.value or ""):
                                            ui.notify("Les deux mots de passe ne correspondent pas.", type="warning")
                                            return
                                        ok, msg, new_user = register_researcher(
                                            str(reg_u.value or ""),
                                            str(reg_p.value or ""),
                                            str(reg_code.value or ""),
                                        )
                                        ui.notify(msg, type="positive" if ok else "negative")
                                        if ok and new_user:
                                            state["auth_user"] = new_user
                                            state["username"] = new_user["username"]
                                            state["tab"] = "recherche"
                                            app.storage.user["auth_username"] = new_user["username"]
                                            render_main_app()

                                    reg_code.on("keydown.enter", do_register)
                                    with ui.element("button").classes("glass-btn glass-btn-accent").style("width:100%;padding:11px;font-size:0.9rem;").on("click", do_register):
                                        safe_html("Créer mon compte Chercheur")

                            else:
                                safe_html(
                                    '<div style="margin-top:16px;">'
                                    '<div class="section-kicker">RÉCUPÉRATION D\'ACCÈS</div>'
                                    '<p class="muted-small" style="margin:6px 0 14px 0;">Indiquez votre identifiant : une demande de réinitialisation sera transmise au Super-Admin.</p></div>'
                                )
                                in_f = ui.input(label="Votre identifiant").props("outlined dense autofocus").style("width:100%;margin-bottom:14px;")

                                def send_forgot(_e=None):
                                    ok, msg = request_password_reset(str(in_f.value or ""))
                                    ui.notify(msg, type="positive" if ok else "negative")
                                    if ok:
                                        auth_mode["view"] = "login"
                                        draw_auth_form()

                                in_f.on("keydown.enter", send_forgot)
                                with ui.element("button").classes("glass-btn glass-btn-accent").style("width:100%;padding:10px;").on("click", send_forgot):
                                    safe_html("Envoyer la demande au Super-Admin")

                                with ui.element("div").style("text-align:center;margin-top:12px;"):
                                    with ui.element("button").style("background:transparent;border:none;color:var(--sub-txt);font-size:0.80rem;cursor:pointer;").on(
                                        "click", lambda _e: (auth_mode.update(view="login"), draw_auth_form())
                                    ):
                                        safe_html("← Retour à la connexion")

                    draw_auth_form()

        mode_now = "dark" if state["dark"] else "light"
        ui.timer(0.05, lambda: ui.run_javascript(f'window.cbApplyTheme("{mode_now}");'), once=True)

    # ------------------------------------------------------------------
    # APPLICATION PRINCIPALE (UNIQUEMENT POUR UTILISATEURS AUTHENTIFIÉS)
    # ------------------------------------------------------------------
    def render_main_app():
        page_root.clear()
        active_refresh_hooks.clear()

        auth_user = state.get("auth_user")
        if not auth_user:
            render_auth_portal()
            return

        role = str(auth_user.get("role", "chercheur"))
        is_admin = role in ("admin", "superadmin")
        is_super = role == "superadmin"
        is_root = bool(auth_user.get("is_root", False))
        uname = str(auth_user["username"])

        tab_buttons: dict[str, Any] = {}
        tab_panels: dict[str, Any] = {}
        labo_bridge: dict[str, Any] = {"select": None}

        with page_root:
            # --- MODALE « MON COMPTE » (CHANGEMENT DE MOT DE PASSE AUTONOME) ---
            account_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
            with account_dialog:
                account_body = ui.element("div").classes("cb-inspector-card").style("width:min(460px, 92vw) !important;")

            def open_account_modal(_e=None):
                account_body.clear()
                with account_body:
                    with ui.element("div").classes("modal-head"):
                        with ui.element("div"):
                            safe_html('<div class="section-kicker">ESPACE PERSONNEL · SÉCURITÉ</div>')
                            root_b = ' <span class="root-badge">FONDATEUR</span>' if is_root else ""
                            safe_html(f'<h2 style="margin:4px 0 4px 0;font-size:1.25rem;">{html.escape(uname)}{root_b}</h2>')
                            safe_html(f'<span class="mono-tag">{html.escape(role.upper())}</span>')
                        with ui.element("button").classes("glass-btn").on("click", lambda _ev: account_dialog.close()):
                            safe_html("Fermer ✕")

                    safe_html('<div class="detail-title" style="margin-bottom:8px;">Modifier mon mot de passe</div>')
                    p_old = ui.input(label="Mot de passe actuel *", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                    p_new = ui.input(label="Nouveau mot de passe (min. 6 car.) *", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                    p_new2 = ui.input(label="Confirmer le nouveau mot de passe *", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:14px;")

                    def do_change_pwd(_ev=None):
                        if str(p_new.value or "") != str(p_new2.value or ""):
                            ui.notify("Les deux nouveaux mots de passe ne correspondent pas.", type="warning")
                            return
                        ok, msg = change_own_password(int(auth_user["id"]), str(p_old.value or ""), str(p_new.value or ""))
                        ui.notify(msg, type="positive" if ok else "negative")
                        if ok:
                            account_dialog.close()

                    with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:6px;"):
                        with ui.element("button").classes("glass-btn glass-btn-danger").on("click", lambda _ev: (account_dialog.close(), do_logout())):
                            safe_html("Déconnexion")
                        with ui.element("button").classes("glass-btn glass-btn-accent").on("click", do_change_pwd):
                            safe_html("Enregistrer")

                account_dialog.open()

            def do_logout(_e=None):
                log_activity(uname, "CONNEXION", "Déconnexion", f"Fin de session ({role})", role=role)
                state["auth_user"] = None
                state["username"] = ""
                state["tab"] = "recherche"
                app.storage.user["auth_username"] = ""
                ui.notify("Vous avez été déconnecté.", type="info")
                render_auth_portal()

            def switch_tab(tab_key: str):
                if tab_key == "admin" and not is_admin:
                    return
                if state["tab"] == tab_key:
                    return
                state["tab"] = tab_key

                for key, btn in tab_buttons.items():
                    btn.classes(add="active") if key == tab_key else btn.classes(remove="active")

                for key, panel in tab_panels.items():
                    panel.classes(add="active") if key == tab_key else panel.classes(remove="active")

                if tab_key == "recherche":
                    logo_wrap.classes(remove="cb-logo-clickable")
                    logo_wrap.props('title="ChemBase R&D"')
                else:
                    logo_wrap.classes(add="cb-logo-clickable")
                    logo_wrap.props('title="Retour au Catalogue principal"')

                hook = active_refresh_hooks.get(tab_key)
                if callable(hook):
                    hook()

                ui.run_javascript("window.cbMovePill(false);")

            def on_logo_click():
                if state["tab"] != "recherche":
                    switch_tab("recherche")

            # --- SPOTLIGHT RECHERCHE RAPIDE (Ctrl + K · ↑ / ↓ / ↵) ---
            spotlight_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
            with spotlight_dialog:
                with ui.element("div").classes("cb-spotlight-card"):
                    safe_html(
                        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                        '<span class="section-kicker">RECHERCHE RAPIDE · CTRL + K</span>'
                        '<span class="muted-small" style="font-family:\'JetBrains Mono\',monospace;">↑ ↓ naviguer · ↵ ouvrir · Échap fermer</span></div>'
                    )
                    spot_input = ui.input(
                        placeholder="Taper une molécule, un CAS, un réactif en stock ou un onglet..."
                    ).props("outlined dense clearable autofocus").style("width:100%;margin-bottom:12px;")
                    spot_results = ui.element("div").props('id="spotlight-results"').style("max-height:360px;overflow-y:auto;")

            # --- COQUE PRINCIPALE ---
            with ui.element("div").classes("app-shell"):
                with ui.element("header").classes("top-header"):
                    with ui.element("div").classes("brand-group"):
                        with (
                            ui.element("div")
                            .classes("cb-logo-wrap")
                            .props('id="cb-logo" title="ChemBase R&D"')
                            .on("click", on_logo_click)
                        ) as logo_wrap:
                            safe_html(LOGO_SVG)

                        with ui.element("div").classes("brand-text"):
                            safe_html('<div class="section-kicker">LABORATORY INFORMATION &amp; R&amp;D SYSTEM</div>')
                            safe_html('<h1>ChemBase <span class="version-pill">v2.0</span></h1>')

                    with ui.element("div").classes("header-actions"):
                        with (
                            ui.element("button")
                            .classes("glass-btn")
                            .props('id="spotlight-trigger" title="Recherche rapide (Ctrl + K)"')
                        ) as spot_trigger:
                            safe_html('<span>Recherche rapide</span><span class="kbd-hint">Ctrl K</span>')

                        status_slot = ui.element("div")

                        # Badge Utilisateur connecté (ouvre Mon compte) + Déconnexion
                        with (
                            ui.element("button")
                            .classes("user-pill")
                            .props('title="Mon compte & Mot de passe"')
                            .on("click", open_account_modal)
                        ):
                            r_badge = '<span class="root-badge">ROOT</span>' if is_root else f'<span class="mono-tag">{html.escape(role.upper())}</span>'
                            safe_html(f'<span class="status-dot status-ok"></span><span>{html.escape(uname)}</span>{r_badge}')

                        with (
                            ui.element("button")
                            .classes("glass-btn")
                            .props('title="Se déconnecter"')
                            .style("padding:7px 11px;font-size:0.76rem;")
                            .on("click", do_logout)
                        ):
                            safe_html("Sortir")

                        with (
                            ui.element("button")
                            .classes("glass-btn icon-btn")
                            .props('id="theme-toggle" title="Changer de thème" aria-label="Changer de thème"')
                            .on("click", toggle_theme)
                        ):
                            safe_html(THEME_TOGGLE_SVGS)

                nav_slot = ui.element("nav").classes("lg-nav").props('id="lg-nav"')
                ui.element("div").classes("hud-divider")

                def refresh_chrome():
                    st = read_db_status()
                    dot_cls = "status-ok" if st["connected"] else "status-err"
                    st_txt = (
                        f"SQLite · {st['molecules']} fiches"
                        if st["connected"]
                        else "DB introuvable"
                    )
                    status_slot.clear()
                    with status_slot:
                        safe_html(
                            f'<div class="status-pill"><span class="status-dot {dot_cls}"></span><span>{st_txt}</span></div>'
                        )

                    admin_notifs = st["pending"] + st["alerts"] + (st["resets"] if is_super else 0)
                    nav_defs = [
                        ("recherche", "Catalogue & Synthèses", 0),
                        ("stocks", "Inventaire & Commandes", st["low_stock"]),
                        ("labo", "Cahier de Laboratoire", 0),
                        ("dashboard", "Analytique", 0),
                        ("proposition", "Nouvelle Fiche", 0),
                    ]
                    if is_admin:
                        nav_defs.append(("admin", "Administration", admin_notifs))

                    tab_buttons.clear()
                    nav_slot.clear()
                    with nav_slot:
                        ui.element("div").classes("lg-pill").props('id="lg-pill"')
                        for key, label, badge_count in nav_defs:
                            cls = "lg-tab active" if key == state["tab"] else "lg-tab"
                            badge_html = f'<span class="tab-badge">{badge_count}</span>' if badge_count > 0 else ""
                            with ui.element("button").classes(cls).on("click", lambda _e, k=key: switch_tab(k)) as btn:
                                safe_html(f"<span>{label}</span>{badge_html}")
                            tab_buttons[key] = btn
                    ui.run_javascript("setTimeout(() => window.cbMovePill(true), 30);")

                def launch_in_labo(prod_name: str):
                    switch_tab("labo")
                    if callable(labo_bridge["select"]):
                        labo_bridge["select"](prod_name)
                    ui.notify(f"« {prod_name} » chargé dans le calculateur de paillasse.", type="info")

                render_catalog_tab, render_proposal_tab, open_fiche_fn, trigger_prefill = build_catalog_and_proposal_views(
                    state,
                    on_data_changed=refresh_chrome,
                    on_launch_in_labo=launch_in_labo,
                )
                render_stocks_tab, focus_stock_search = build_stocks_view(state, on_data_changed=refresh_chrome)
                render_labo_tab, select_in_labo = build_labo_view(state, on_data_changed=refresh_chrome)
                labo_bridge["select"] = select_in_labo
                render_analytics_tab, render_admin_tab = build_analytics_and_admin_views(
                    state, on_data_changed=refresh_chrome
                )

                nav_targets = [
                    ("recherche", "Onglet · Catalogue & Synthèses"),
                    ("stocks", "Onglet · Inventaire & Commandes"),
                    ("labo", "Onglet · Cahier de Laboratoire"),
                    ("dashboard", "Onglet · Analytique"),
                    ("proposition", "Onglet · Nouvelle Fiche"),
                ]
                if is_admin:
                    nav_targets.append(("admin", "Onglet · Administration"))

                def render_spotlight_items():
                    q = clean_val(spot_input.value).lower()
                    mols = get_all_syntheses()
                    invs = get_all_inventory()

                    spot_results.clear()
                    with spot_results:
                        found = 0
                        for r in mols:
                            prod = clean_val(r.get("Produit final"))
                            cas = clean_val(r.get("Numéro CAS"))
                            if not q or q in prod.lower() or q in cas.lower():
                                async def open_from_spot(_e=None, row=r):
                                    spotlight_dialog.close()
                                    switch_tab("recherche")
                                    await open_fiche_fn(row)

                                with ui.element("button").classes("spotlight-item").on("click", open_from_spot):
                                    safe_html(f'<span><strong>{html.escape(prod)}</strong> <span class="muted-small">CAS {html.escape(cas or "N/A")}</span></span><span class="mono-tag">FICHE</span>')
                                found += 1
                                if found >= 5:
                                    break

                        inv_hits = 0
                        for it in invs:
                            sub = clean_val(it.get("nom_substance"))
                            loc = clean_val(it.get("emplacement"))
                            if q and (q in sub.lower() or q in loc.lower()):
                                def jump_stock(_e=None, name=sub):
                                    spotlight_dialog.close()
                                    switch_tab("stocks")
                                    focus_stock_search(name)

                                with ui.element("button").classes("spotlight-item").on("click", jump_stock):
                                    safe_html(f'<span><strong>{html.escape(sub)}</strong> <span class="muted-small">{it["quantite"]:g} {html.escape(clean_val(it.get("unite")))} · {html.escape(loc)}</span></span><span class="yield-tag">STOCK</span>')
                                inv_hits += 1
                                found += 1
                                if inv_hits >= 4:
                                    break

                        for key, lbl in nav_targets:
                            if not q or q in lbl.lower():
                                def jump_tab(_e=None, k=key):
                                    spotlight_dialog.close()
                                    switch_tab(k)

                                with ui.element("button").classes("spotlight-item").on("click", jump_tab):
                                    safe_html(f'<span>{html.escape(lbl)}</span><span class="muted-small">Aller ➔</span>')
                                found += 1

                        if found == 0:
                            safe_html('<p class="muted-small" style="padding:8px;">Aucun résultat correspondant.</p>')

                    ui.run_javascript("setTimeout(() => window.cbSpotResetSelection && window.cbSpotResetSelection(), 20);")

                def open_spotlight(_e=None):
                    spot_input.value = ""
                    render_spotlight_items()
                    spotlight_dialog.open()

                spot_trigger.on("click", open_spotlight)
                spot_input.on_value_change(lambda _e: render_spotlight_items())

                with ui.element("main").classes("main-content"):
                    with ui.element("section").classes("tab-panel active") as p_rec:
                        active_refresh_hooks["recherche"] = render_catalog_tab()
                    tab_panels["recherche"] = p_rec

                    with ui.element("section").classes("tab-panel") as p_sto:
                        active_refresh_hooks["stocks"] = render_stocks_tab()
                    tab_panels["stocks"] = p_sto

                    with ui.element("section").classes("tab-panel") as p_labo:
                        active_refresh_hooks["labo"] = render_labo_tab()
                    tab_panels["labo"] = p_labo

                    with ui.element("section").classes("tab-panel") as p_ana:
                        active_refresh_hooks["dashboard"] = render_analytics_tab()
                    tab_panels["dashboard"] = p_ana

                    with ui.element("section").classes("tab-panel") as p_prop:
                        render_proposal_tab()
                    tab_panels["proposition"] = p_prop

                    if is_admin:
                        with ui.element("section").classes("tab-panel") as p_adm:
                            active_refresh_hooks["admin"] = render_admin_tab()
                        tab_panels["admin"] = p_adm

                refresh_chrome()

                # Pont externe (ChemStudio) : pré-remplit Nouvelle Fiche si paramètres URL fournis
                if any(pending_prefill.values()):
                    c_p, n_p, s_p = pending_prefill["cas"], pending_prefill["name"], pending_prefill["smiles"]
                    pending_prefill.update(cas="", name="", smiles="")
                    switch_tab("proposition")
                    trigger_prefill(c_p, n_p, s_p)
                    ui.notify("Molécule reçue depuis un module externe et pré-remplie.", type="info")

                safe_html(
                    """
                    <footer class="app-footer">
                      <span>CHEMBASE R&amp;D PLATFORM · 100 % PYTHON (NICEGUI)</span>
                      <span>ACCÈS AUTHENTIFIÉ · TRAÇABILITÉ &amp; API READY (CHEMSTUDIO)</span>
                    </footer>
                    """
                )

        mode_now = "dark" if state["dark"] else "light"
        ui.timer(0.05, lambda: ui.run_javascript(f'window.cbApplyTheme("{mode_now}");'), once=True)

    if state["auth_user"]:
        render_main_app()
    else:
        render_auth_portal()


if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.environ.get("PORT", 8080))
    is_render = os.environ.get("RENDER") is not None
    ui.run(
        host="0.0.0.0",
        port=port,
        title="ChemBase — R&D, Cahier de Laboratoire & Stocks",
        favicon=find_favicon(),
        dark=True,
        storage_secret=os.environ.get("STORAGE_SECRET", "chembase-swiss-biotech-2026"),
        reload=not is_render,
        show=not is_render,
    )