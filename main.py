import html
import os
from fastapi.responses import HTMLResponse
from nicegui import app, ui

from chem_data import LABO_FILES_DIR, build_3dmol_html, clean_val
from database import (
    get_all_inventory,
    get_all_syntheses,
    get_user_by_username,
    init_db,
    read_db_status,
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


@app.get("/api/3d", response_class=HTMLResponse)
def serve_3d_viewer(cas: str = "", dark: int = 1):
    """Moteur 3Dmol.js léger servi dans la Fiche Technique."""
    return HTMLResponse(content=build_3dmol_html(cas, dark_mode=bool(dark)))


def find_favicon():
    for folder in (BASE_DIR, IMAGES_DIR):
        for ext in ("png", "jpg", "jpeg", "ico"):
            path = os.path.join(folder, f"chembase_logo.{ext}")
            if os.path.exists(path):
                return path
    return None


@ui.page("/")
def index_page():
    inject_theme()

    # Mémoire persistante du thème et de la session Administrateur
    saved_dark = app.storage.user.get("dark", True)
    saved_user_name = app.storage.user.get("auth_username", "")
    restored_user = get_user_by_username(saved_user_name) if saved_user_name else None
    if restored_user and restored_user.get("role") not in ("admin", "superadmin"):
        restored_user = None

    dark = ui.dark_mode(value=saved_dark)
    state = {
        "tab": "recherche",
        "dark": saved_dark,
        "username": restored_user["username"] if restored_user else "chercheur",
        "auth_user": restored_user,
    }

    init_mode = "dark" if saved_dark else "light"
    ui.timer(0.05, lambda: ui.run_javascript(f'window.cbApplyTheme("{init_mode}");'), once=True)

    tab_buttons = {}
    tab_panels = {}
    refresh_hooks = {}

    def switch_tab(tab_key: str):
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

        hook = refresh_hooks.get(tab_key)
        if callable(hook):
            hook()

        ui.run_javascript("window.cbMovePill(false);")

    def on_logo_click():
        if state["tab"] != "recherche":
            switch_tab("recherche")

    def toggle_theme():
        state["dark"] = not state["dark"]
        dark.value = state["dark"]
        app.storage.user["dark"] = state["dark"]
        mode = "dark" if state["dark"] else "light"
        ui.run_javascript(f'window.cbToggleThemeWave("{mode}");')

    # ------------------------------------------------------------------
    # SPOTLIGHT RECHERCHE RAPIDE (Ctrl + K)
    # ------------------------------------------------------------------
    spotlight_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with spotlight_dialog:
        with ui.element("div").classes("cb-spotlight-card"):
            safe_html('<div class="section-kicker" style="margin-bottom:8px;">RECHERCHE RAPIDE · CTRL + K</div>')
            spot_input = ui.input(
                placeholder="Taper une molécule, un CAS, un réactif en stock ou un onglet..."
            ).props("outlined dense clearable autofocus").style("width:100%;margin-bottom:12px;")
            spot_results = ui.element("div").style("max-height:360px;overflow-y:auto;")

    # --- COQUE PRINCIPALE ---
    with ui.element("div").classes("app-shell"):
        # En-tête épuré
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

                with (
                    ui.element("button")
                    .classes("glass-btn icon-btn")
                    .props('id="theme-toggle" title="Changer de thème" aria-label="Changer de thème"')
                    .on("click", toggle_theme)
                ):
                    safe_html(THEME_TOGGLE_SVGS)

        # Barre de navigation Liquid Glass
        nav_slot = ui.element("nav").classes("lg-nav").props('id="lg-nav"')
        ui.element("div").classes("hud-divider")

        def refresh_chrome():
            st = read_db_status()
            dot_cls = "status-ok" if st["connected"] else "status-err"
            st_txt = (
                f"SQLite connecté · {st['molecules']} fiches"
                if st["connected"]
                else "chimie_db.sqlite introuvable"
            )
            status_slot.clear()
            with status_slot:
                safe_html(
                    f'<div class="status-pill"><span class="status-dot {dot_cls}"></span><span>{st_txt}</span></div>'
                )

            is_super = bool(state.get("auth_user") and state["auth_user"].get("role") == "superadmin")
            admin_notifs = st["pending"] + st["alerts"] + (st["resets"] if is_super else 0)
            nav_defs = [
                ("recherche", "Catalogue & Synthèses", 0),
                ("stocks", "Inventaire & Commandes", st["low_stock"]),
                ("labo", "Cahier de Laboratoire", 0),
                ("dashboard", "Analytique", 0),
                ("proposition", "Nouvelle Fiche", 0),
                ("admin", "Administration", admin_notifs),
            ]
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

        # Ponts inter-modules (Fiche -> Cahier de Labo & Spotlight -> Fiche / Stocks)
        labo_bridge = {"select": None}

        def launch_in_labo(prod_name: str):
            switch_tab("labo")
            if callable(labo_bridge["select"]):
                labo_bridge["select"](prod_name)
            ui.notify(f"« {prod_name} » chargé dans le calculateur de paillasse.", type="info")

        render_catalog_tab, render_proposal_tab, open_fiche_fn = build_catalog_and_proposal_views(
            state,
            on_data_changed=refresh_chrome,
            on_launch_in_labo=launch_in_labo,
        )
        render_stocks_tab, focus_stock_search = build_stocks_view(on_data_changed=refresh_chrome)
        render_labo_tab, select_in_labo = build_labo_view(state, on_data_changed=refresh_chrome)
        labo_bridge["select"] = select_in_labo
        render_analytics_tab, render_admin_tab = build_analytics_and_admin_views(
            state, on_data_changed=refresh_chrome
        )

        # Logique Spotlight Ctrl + K
        nav_targets = [
            ("recherche", "Onglet · Catalogue & Synthèses"),
            ("stocks", "Onglet · Inventaire & Commandes"),
            ("labo", "Onglet · Cahier de Laboratoire"),
            ("dashboard", "Onglet · Analytique"),
            ("proposition", "Onglet · Nouvelle Fiche"),
            ("admin", "Onglet · Administration"),
        ]

        def render_spotlight_items():
            q = clean_val(spot_input.value).lower()
            mols = get_all_syntheses()
            invs = get_all_inventory()

            spot_results.clear()
            with spot_results:
                found = 0
                # 1. Molécules
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

                # 2. Substances en stock
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

                # 3. Onglets
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

        def open_spotlight(_e=None):
            spot_input.value = ""
            render_spotlight_items()
            spotlight_dialog.open()

        spot_trigger.on("click", open_spotlight)
        spot_input.on_value_change(lambda _e: render_spotlight_items())

        # Contenu des 6 onglets
        with ui.element("main").classes("main-content"):
            with ui.element("section").classes("tab-panel active") as p_rec:
                refresh_hooks["recherche"] = render_catalog_tab()
            tab_panels["recherche"] = p_rec

            with ui.element("section").classes("tab-panel") as p_sto:
                refresh_hooks["stocks"] = render_stocks_tab()
            tab_panels["stocks"] = p_sto

            with ui.element("section").classes("tab-panel") as p_labo:
                refresh_hooks["labo"] = render_labo_tab()
            tab_panels["labo"] = p_labo

            with ui.element("section").classes("tab-panel") as p_ana:
                refresh_hooks["dashboard"] = render_analytics_tab()
            tab_panels["dashboard"] = p_ana

            with ui.element("section").classes("tab-panel") as p_prop:
                render_proposal_tab()
            tab_panels["proposition"] = p_prop

            with ui.element("section").classes("tab-panel") as p_adm:
                refresh_hooks["admin"] = render_admin_tab()
            tab_panels["admin"] = p_adm

        refresh_chrome()

        safe_html(
            """
            <footer class="app-footer">
              <span>CHEMBASE R&amp;D PLATFORM · 100 % PYTHON (NICEGUI)</span>
              <span>BASE SQLITE · CATALOGUE, STOCKS &amp; CAHIER DE LABORATOIRE</span>
            </footer>
            """
        )


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