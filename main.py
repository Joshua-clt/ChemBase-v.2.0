import os
from fastapi.responses import HTMLResponse
from nicegui import app, ui

from chem_data import build_3dmol_html
from database import init_db, read_db_status
from theme import LOGO_SVG, THEME_TOGGLE_SVGS, inject_theme, safe_html
from views_catalog import build_catalog_and_proposal_views

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "images")
os.makedirs(IMAGES_DIR, exist_ok=True)

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
    dark = ui.dark_mode(value=True)
    state = {"tab": "recherche", "dark": True, "username": "chercheur"}

    tab_buttons = {}
    tab_panels = {}

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

        ui.run_javascript("window.cbMovePill(false);")

    def on_logo_click():
        if state["tab"] != "recherche":
            switch_tab("recherche")

    def toggle_theme():
        state["dark"] = not state["dark"]
        dark.value = state["dark"]
        mode = "dark" if state["dark"] else "light"
        ui.run_javascript(f'window.cbApplyTheme("{mode}");')

    # --- COQUE PRINCIPALE ---
    with ui.element("div").classes("app-shell"):
        # En-tête
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
                    safe_html('<div class="section-kicker">LABORATORY INFORMATION &amp; ELN SYSTEM</div>')
                    safe_html('<h1>ChemBase <span class="version-pill">v2.0</span></h1>')

            with ui.element("div").classes("header-actions"):
                status_slot = ui.element("div")

                with (
                    ui.element("button")
                    .classes("glass-btn icon-btn")
                    .props('id="theme-toggle" title="Passer en mode clair" aria-label="Changer de thème"')
                    .on("click", toggle_theme)
                ):
                    safe_html(THEME_TOGGLE_SVGS)

        # Barre de navigation Liquid Glass
        nav_slot = ui.element("nav").classes("lg-nav").props('id="lg-nav"')
        ui.element("div").classes("hud-divider")

        kpi_slot = ui.element("div")

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

            admin_notifs = st["pending"] + st["alerts"]
            nav_defs = [
                ("recherche", "Catalogue & Synthèses", 0),
                ("stocks", "Inventaire & Commandes", st["low_stock"]),
                ("eln", "Carnet ELN", 0),
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

            kpi_slot.clear()
            with kpi_slot:
                safe_html(
                    f"""
                    <div class="kpi-grid">
                      <div class="kpi-card">
                        <div class="kpi-label">Molécules en base</div>
                        <div class="kpi-value">{st['molecules']}</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Références en stock</div>
                        <div class="kpi-value">{st['inventory']}</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Alertes seuil critique</div>
                        <div class="kpi-value">{st['low_stock']}</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Essais ELN archivés</div>
                        <div class="kpi-value">{st['eln']}</div>
                      </div>
                    </div>
                    """
                )

        render_catalog_tab, render_proposal_tab = build_catalog_and_proposal_views(
            state, on_data_changed=refresh_chrome
        )

        # Contenu des 6 onglets
        with ui.element("main").classes("main-content"):
            # Onglet 1 : Catalogue & Synthèses (Phase 2 actif)
            with ui.element("section").classes("tab-panel active") as p_rec:
                render_catalog_tab()
            tab_panels["recherche"] = p_rec

            # Onglets Phase 3 (Inventaire, ELN, Analytique)
            placeholders_mid = [
                ("stocks", "PHASE 3 · MODULE LOGISTIQUE", "Inventaire Physique, Densités & Commandes",
                 "Gestion temps réel des stocks, conversion automatique g / mL, alertes critiques et export des bons de commande."),
                ("eln", "PHASE 3 · CAHIER DE LABORATOIRE", "Carnet ELN & Calculateur Stœchiométrique",
                 "Calculateur stœchiométrique 1:1, archivage des essais, pièces jointes analytiques et courbes de rendement."),
                ("dashboard", "PHASE 3 · TÉLÉMÉTRIE R&D", "Tableau de Bord Analytique",
                 "Statistiques de rendements, répartition SGH, réactifs clés et relevé des recherches sans résultat."),
            ]
            for key, kicker, title, desc in placeholders_mid:
                with ui.element("section").classes("tab-panel") as panel:
                    safe_html(
                        f'<div class="hud-card"><div class="section-kicker">{kicker}</div>'
                        f'<h2>{title}</h2><p class="muted-text">{desc}</p></div>'
                    )
                tab_panels[key] = panel

            # Onglet 5 : Nouvelle Fiche (Phase 2 actif)
            with ui.element("section").classes("tab-panel") as p_prop:
                render_proposal_tab()
            tab_panels["proposition"] = p_prop

            # Onglet 6 : Administration (Phase 3)
            with ui.element("section").classes("tab-panel") as p_adm:
                safe_html(
                    '<div class="hud-card"><div class="section-kicker">PHASE 3 · GOUVERNANCE</div>'
                    '<h2>Administration, Modération &amp; Audit</h2>'
                    '<p class="muted-text">Alertes de stock, validation des fiches proposées, journal d\'audit avec droit de veto et gestion des comptes.</p></div>'
                )
            tab_panels["admin"] = p_adm

        refresh_chrome()

        safe_html(
            """
            <footer class="app-footer">
              <span>CHEMBASE R&amp;D PLATFORM · 100 % PYTHON (NICEGUI)</span>
              <span>BASE SQLITE · PHASE 2 CATALOGUE &amp; INSPECTEUR</span>
            </footer>
            """
        )


if __name__ in {"__main__", "__mp_main__"}:
    port = int(os.environ.get("PORT", 8080))
    is_render = os.environ.get("RENDER") is not None
    ui.run(
        host="0.0.0.0",
        port=port,
        title="ChemBase — R&D, ELN & Stocks",
        favicon=find_favicon(),
        dark=True,
        reload=not is_render,
        show=not is_render,
    )