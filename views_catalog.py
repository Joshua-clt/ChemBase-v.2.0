import html
import urllib.parse
from nicegui import run, ui

from chem_data import (
    BASE_COLS,
    FAST_SMILES_MAP,
    GENERAL_RXN_SCHEMES,
    HEX_WATERMARK_SVG,
    REACTION_DETAILS,
    SGH_DICT,
    build_specific_reaction_smiles,
    clean_val,
    export_styled_table,
    fetch_full_pubchem_by_cas,
    fetch_reactant_inspector_data,
    generate_molecule_html,
    get_density_from_pubchem,
    get_safety_fds_links,
    get_vector_depict_url,
    render_pictograms_html,
    sanitize_filename,
)
from database import (
    get_all_syntheses,
    get_favorites,
    get_inventory_map,
    insert_pending_synthese,
    toggle_favorite,
)
from theme import safe_html

SGH_OPTIONS = [f"{code} - {lbl}" for code, (lbl, _fn) in SGH_DICT.items()]


def _btn(label_html: str, classes: str = "glass-btn", on_click=None, style: str = "", props: str = ""):
    el = ui.element("button").classes(classes)
    if style:
        el.style(style)
    if props:
        el.props(props)
    if on_click is not None:
        el.on("click", on_click)
    with el:
        safe_html(label_html)
    return el


def _fast_card_2d_url(cas: str, prod: str) -> str:
    smi = FAST_SMILES_MAP.get(cas.lower()) or FAST_SMILES_MAP.get(prod.lower())
    if smi:
        return get_vector_depict_url(smi, style="cow", w=220, h=170, zoom=2.5)
    if cas:
        return f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(cas)}/PNG?image_size=300x300"
    return ""


def _stock_badge_html(name: str, inv_map: dict) -> str:
    info = inv_map.get(clean_val(name).lower())
    if not info:
        return ""
    qty, unit, seuil, _dens = info
    if qty <= 0:
        return '<span class="stock-pill stock-empty">Rupture</span>'
    if qty <= seuil:
        return f'<span class="stock-pill stock-low">Bas · {qty:g} {html.escape(unit)}</span>'
    return f'<span class="stock-pill stock-ok">Stock · {qty:g} {html.escape(unit)}</span>'


def build_catalog_and_proposal_views(app_state: dict, on_data_changed=None):
    username = app_state.get("username", "chercheur")

    fiche_dialog = ui.dialog()
    with fiche_dialog:
        fiche_body = ui.element("div").classes("cb-modal-card")

    inspector_dialog = ui.dialog()
    with inspector_dialog:
        inspector_body = ui.element("div").classes("cb-inspector-card")

    def make_open_fiche_handler(target_row: dict, close_inspector: bool = False):
        async def _handler(_e=None):
            if close_inspector:
                inspector_dialog.close()
            await open_fiche(target_row)
        return _handler

    def make_reactant_handler(rea_name: str):
        async def _handler(_e=None):
            await open_reactant_inspector(rea_name)
        return _handler

    def open_reaction_inspector(rx_name: str):
        rx_clean = clean_val(rx_name)
        key = rx_clean.lower()
        scheme = GENERAL_RXN_SCHEMES.get(key)
        details = REACTION_DETAILS.get(key)
        all_rows = get_all_syntheses()
        related = [
            r for r in all_rows
            if clean_val(r.get("Réaction 1")).lower() == key
            or clean_val(r.get("Réaction 2")).lower() == key
        ]

        inspector_body.clear()
        with inspector_body:
            with ui.element("div").classes("modal-head"):
                with ui.element("div"):
                    safe_html('<div class="section-kicker">VUE INSPECTEUR · MÉCANISME RÉACTIONNEL</div>')
                    safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.35rem;">{html.escape(rx_clean)}</h2>')
                _btn("Fermer ✕", on_click=lambda _e: inspector_dialog.close())

            if scheme:
                rxn_smi, rxn_eq = scheme
                svg_url = get_vector_depict_url(rxn_smi, style="cow", w=620, h=170, zoom=2.3)
                safe_html(
                    f"""
                    <div class="detail-box">
                      <div class="detail-title">Schéma général de la transformation</div>
                      <div class="rxn-canvas-box">
                        <img class="rxn-svg-adaptive" src="{svg_url}" alt="{html.escape(rx_clean)}" />
                      </div>
                      <div class="muted-small" style="text-align:center;margin-top:8px;font-family:'JetBrains Mono',monospace;">
                        {html.escape(rxn_eq)}
                      </div>
                    </div>
                    """
                )

            if details:
                safe_html(
                    f"""
                    <div class="detail-box">
                      <div class="detail-title">Fiche Mécanistique &amp; Sécurité Opératoire</div>
                      <div class="kv-grid" style="margin-bottom:10px;">
                        <div class="kv-item"><div class="kv-label">Famille</div><div class="kv-val">{html.escape(details['famille'])}</div></div>
                        <div class="kv-item"><div class="kv-label">Système catalytique</div><div class="kv-val">{html.escape(details['catalyseur'])}</div></div>
                      </div>
                      <p class="muted-text" style="margin-bottom:10px;"><strong style="color:var(--txt);">Principe :</strong> {html.escape(details['principe'])}</p>
                      <p class="muted-text"><strong style="color:var(--warn);">Points de vigilance :</strong> {html.escape(details['vigilance'])}</p>
                    </div>
                    """
                )
            else:
                safe_html(
                    '<div class="detail-box"><p class="muted-text">Aucune fiche mécanistique détaillée pré-enregistrée pour cette réaction.</p></div>'
                )

            with ui.element("div").classes("detail-box"):
                safe_html(f'<div class="detail-title">Synthèses du catalogue utilisant cette réaction ({len(related)})</div>')
                if not related:
                    safe_html('<span class="muted-small">Aucune autre synthèse trouvée.</span>')
                else:
                    with ui.element("div").style("display:flex;flex-wrap:wrap;gap:8px;"):
                        for rel in related:
                            p_lbl = clean_val(rel.get("Produit final"))
                            _btn(
                                f"<span>{html.escape(p_lbl)}</span>",
                                classes="rea-pill-click",
                                on_click=make_open_fiche_handler(rel, close_inspector=True),
                            )

        inspector_dialog.open()

    async def open_reactant_inspector(reactant_name: str):
        rea_clean = clean_val(reactant_name)
        inv_map = get_inventory_map()
        all_rows = get_all_syntheses()
        used_in = [
            r for r in all_rows
            if any(clean_val(r.get(f"Réactifs {i}")).lower() == rea_clean.lower() for i in range(1, 5))
        ]

        inspector_body.clear()
        with inspector_body:
            with ui.element("div").classes("modal-head"):
                with ui.element("div"):
                    safe_html('<div class="section-kicker">VUE INSPECTEUR · RÉACTIF &amp; SÉCURITÉ</div>')
                    safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.35rem;">{html.escape(rea_clean)}</h2>')
                _btn("Fermer ✕", on_click=lambda _e: inspector_dialog.close())

            content_slot = ui.element("div")
            with content_slot:
                with ui.row().classes("items-center gap-3 q-pa-md"):
                    ui.spinner("dots", size="md", color="cyan")
                    safe_html('<span class="muted-text">Interrogation PubChem &amp; vérification de l\'inventaire...</span>')

        inspector_dialog.open()

        data = await run.io_bound(fetch_reactant_inspector_data, rea_clean)
        pc_url, sig_url = await run.io_bound(get_safety_fds_links, data.get("cas", ""), rea_clean)
        depict_url = get_vector_depict_url(data["smiles"], style="cow", w=260, h=190, zoom=2.6) if data.get("smiles") else ""
        stock_html = _stock_badge_html(rea_clean, inv_map) or '<span class="muted-small">Non référencé en stock</span>'

        iupac_html = ""
        if data.get("iupac"):
            iupac_html = f'<p class="muted-small" style="margin-top:10px;"><strong>IUPAC :</strong> {html.escape(data["iupac"])}</p>'

        fds_btns = ""
        if pc_url:
            fds_btns += f'<a class="glass-btn" style="text-decoration:none;" href="{pc_url}" target="_blank">FDS PubChem LCSS ↗</a>'
        if sig_url:
            fds_btns += f'<a class="glass-btn" style="text-decoration:none;" href="{sig_url}" target="_blank">FDS Sigma-Aldrich ↗</a>'

        content_slot.clear()
        with content_slot:
            with ui.element("div").classes("modal-grid"):
                with ui.element("div"):
                    safe_html(
                        f"""
                        <div class="detail-box">
                          <div class="detail-title">Identité &amp; Constantes</div>
                          <div class="kv-grid">
                            <div class="kv-item"><div class="kv-label">Formule brute</div><div class="kv-val">{html.escape(data['formule'])}</div></div>
                            <div class="kv-item"><div class="kv-label">Masse molaire</div><div class="kv-val">{html.escape(data['masse_molaire'])}</div></div>
                            <div class="kv-item"><div class="kv-label">Densité</div><div class="kv-val">{html.escape(data['densite'])}</div></div>
                            <div class="kv-item"><div class="kv-label">Numéro CAS</div><div class="kv-val">{html.escape(data['cas'] or 'N/A')}</div></div>
                          </div>
                          {iupac_html}
                          <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                            <span class="muted-small">Stock laboratoire :</span> {stock_html}
                          </div>
                        </div>
                        <div class="detail-box">
                          <div class="detail-title">Dangers SGH &amp; FDS</div>
                          {render_pictograms_html(data.get("pictos", ""))}
                          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">{fds_btns}</div>
                        </div>
                        """
                    )

                with ui.element("div"):
                    if depict_url:
                        safe_html(
                            f"""
                            <div class="detail-box">
                              <div class="detail-title">Structure 2D</div>
                              <div class="rxn-canvas-box" style="min-height:190px;">
                                <img class="mol-2d-adaptive" src="{depict_url}" alt="{html.escape(rea_clean)}" />
                              </div>
                            </div>
                            """
                        )
                    with ui.element("div").classes("detail-box"):
                        safe_html(f'<div class="detail-title">Utilisé dans {len(used_in)} synthèse(s)</div>')
                        with ui.element("div").style("display:flex;flex-wrap:wrap;gap:8px;"):
                            for rel in used_in:
                                p_lbl = clean_val(rel.get("Produit final"))
                                _btn(
                                    f"<span>{html.escape(p_lbl)}</span>",
                                    classes="rea-pill-click",
                                    on_click=make_open_fiche_handler(rel, close_inspector=True),
                                )

    async def open_fiche(row: dict):
        prod = clean_val(row.get("Produit final")) or "Molécule"
        cas = clean_val(row.get("Numéro CAS"))
        rdt = clean_val(row.get("Rendement"))
        rx1, rx2 = clean_val(row.get("Réaction 1")), clean_val(row.get("Réaction 2"))
        comm = clean_val(row.get("Commentaire"))
        cond_op = clean_val(row.get("Conditions opératoires")) or "Non renseignées"
        formule = clean_val(row.get("Formule brute & masse")) or "N/A"
        etat = clean_val(row.get("État physique")) or "N/A"
        rarete = clean_val(row.get("Rareté & Coût")) or "N/A"
        stockage = clean_val(row.get("Conditions de stockage")) or "N/A"
        reactants = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
        inv_map = get_inventory_map()
        img_2d = _fast_card_2d_url(cas, prod)
        viewer_mode = {"mode": "2d"}

        cas_tag = f'<span class="mono-tag">CAS {html.escape(cas)}</span>' if cas else ""
        rdt_tag = f'<span class="yield-tag">Rdt {html.escape(rdt)}</span>' if rdt else ""
        comm_html = f'<p class="muted-text"><strong style="color:var(--txt);">Notes R&amp;D :</strong> {html.escape(comm)}</p>' if comm else ""

        fiche_body.clear()
        with fiche_body:
            with ui.element("div").classes("modal-head"):
                with ui.element("div"):
                    safe_html('<div class="section-kicker">SPÉCIFICATION TECHNIQUE &amp; SYNTHÈSE</div>')
                    safe_html(
                        f'<h2 style="margin:4px 0 4px 0;font-size:1.45rem;">{html.escape(prod)}</h2>'
                        f'<div class="mol-subrow">{cas_tag}{rdt_tag}{_stock_badge_html(prod, inv_map)}</div>'
                    )
                with ui.element("div").style("display:flex;gap:8px;flex-wrap:wrap;"):
                    _btn(
                        "Exporter Fiche HTML",
                        on_click=lambda _e, r=row, p=prod: ui.download(
                            generate_molecule_html(r), f"Fiche_{sanitize_filename(p)}.html"
                        ),
                    )
                    _btn("Fermer ✕", on_click=lambda _e: fiche_dialog.close())

            with ui.element("div").classes("modal-grid"):
                with ui.element("div"):
                    with ui.element("div").classes("detail-box"):
                        safe_html('<div class="detail-title">Voie Réactionnelle (cliquer pour inspecter)</div>')
                        with ui.element("div").style("display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:12px;"):
                            if rx1:
                                _btn(
                                    f"<span>⚗ {html.escape(rx1)}</span>",
                                    classes="rx-pill-click",
                                    on_click=lambda _e, name=rx1: open_reaction_inspector(name),
                                )
                            if rx2:
                                safe_html('<span class="muted-small">➔</span>')
                                _btn(
                                    f"<span>⚗ {html.escape(rx2)}</span>",
                                    classes="rx-pill-click",
                                    on_click=lambda _e, name=rx2: open_reaction_inspector(name),
                                )
                        rxn_slot = ui.element("div")
                        with rxn_slot:
                            safe_html('<div class="rxn-canvas-box"><span class="muted-small">Génération de l\'équation vectorielle...</span></div>')

                    with ui.element("div").classes("detail-box"):
                        safe_html('<div class="detail-title">Réactifs &amp; Catalyseurs (cliquer pour inspecter)</div>')
                        if not reactants:
                            safe_html('<span class="muted-small">Aucun réactif renseigné.</span>')
                        else:
                            with ui.element("div").style("display:flex;flex-wrap:wrap;gap:8px;"):
                                for rea in reactants:
                                    s_info = inv_map.get(rea.lower())
                                    dot = ""
                                    if s_info:
                                        dot_c = "status-err" if s_info[0] <= 0 else ("status-warn" if s_info[0] <= s_info[2] else "status-ok")
                                        dot = f'<span class="status-dot {dot_c}"></span>'
                                    _btn(
                                        f"{dot}<span>{html.escape(rea)}</span>",
                                        classes="rea-pill-click",
                                        on_click=make_reactant_handler(rea),
                                    )

                    safe_html(
                        f"""
                        <div class="detail-box">
                          <div class="detail-title">Protocole &amp; Observations</div>
                          <p class="muted-text" style="margin-bottom:8px;"><strong style="color:var(--txt);">Conditions opératoires :</strong> {html.escape(cond_op)}</p>
                          {comm_html}
                        </div>
                        """
                    )

                with ui.element("div"):
                    with ui.element("div").classes("detail-box"):
                        with ui.element("div").style("display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;"):
                            safe_html('<div class="detail-title" style="margin:0;">Visualisation Moléculaire</div>')
                            with ui.element("div").style("display:flex;gap:6px;"):
                                btn_2d = _btn("Structure 2D", style="padding:4px 10px;font-size:0.74rem;")
                                btn_3d = _btn("Modèle 3D", style="padding:4px 10px;font-size:0.74rem;")

                        mol_view_slot = ui.element("div")

                        def render_mol_viewer():
                            mol_view_slot.clear()
                            with mol_view_slot:
                                if viewer_mode["mode"] == "2d":
                                    if img_2d:
                                        safe_html(
                                            f'<div class="rxn-canvas-box" style="min-height:245px;">'
                                            f'<img class="mol-2d-adaptive" style="max-height:220px;" src="{img_2d}" alt="{html.escape(prod)}" />'
                                            f'</div>'
                                        )
                                    else:
                                        safe_html('<div class="rxn-canvas-box" style="min-height:245px;"><span class="muted-small">Structure 2D indisponible</span></div>')
                                else:
                                    d_flag = 1 if app_state.get("dark", True) else 0
                                    src = f"/api/3d?cas={urllib.parse.quote(cas)}&dark={d_flag}"
                                    safe_html(f'<iframe class="viewer-3d-frame" src="{src}" title="3D {html.escape(prod)}"></iframe>')

                        btn_2d.on("click", lambda _e: (viewer_mode.update(mode="2d"), render_mol_viewer()))
                        btn_3d.on("click", lambda _e: (viewer_mode.update(mode="3d"), render_mol_viewer()))
                        render_mol_viewer()

                    props_slot = ui.element("div")
                    with props_slot:
                        safe_html(
                            f"""
                            <div class="detail-box">
                              <div class="detail-title">Propriétés Physico-Chimiques</div>
                              <div class="kv-grid">
                                <div class="kv-item"><div class="kv-label">Formule &amp; Masse</div><div class="kv-val">{html.escape(formule)}</div></div>
                                <div class="kv-item"><div class="kv-label">État physique</div><div class="kv-val">{html.escape(etat)}</div></div>
                                <div class="kv-item"><div class="kv-label">Rareté &amp; Coût</div><div class="kv-val">{html.escape(rarete)}</div></div>
                                <div class="kv-item"><div class="kv-label">Stockage</div><div class="kv-val">{html.escape(stockage)}</div></div>
                              </div>
                            </div>
                            <div class="detail-box">
                              <div class="detail-title">Classification SGH &amp; FDS</div>
                              {render_pictograms_html(row.get("Pictogrammes danger"))}
                              <div style="margin-top:10px;"><span class="muted-small">Chargement des liens FDS...</span></div>
                            </div>
                            """
                        )

        fiche_dialog.open()

        rxn_smi = await run.io_bound(build_specific_reaction_smiles, row)
        pc_url, sig_url = await run.io_bound(get_safety_fds_links, cas, prod)
        dens = await run.io_bound(get_density_from_pubchem, cas or prod)

        rxn_slot.clear()
        with rxn_slot:
            if rxn_smi:
                rxn_svg = get_vector_depict_url(rxn_smi, style="cow", w=580, h=155, zoom=2.3)
                safe_html(f'<div class="rxn-canvas-box"><img class="rxn-svg-adaptive" src="{rxn_svg}" alt="Équation" /></div>')
            else:
                safe_html('<div class="rxn-canvas-box"><span class="muted-small">Équation vectorielle non générable pour ces réactifs.</span></div>')

        fds_links = ""
        if pc_url:
            fds_links += f'<a class="glass-btn" style="text-decoration:none;" href="{pc_url}" target="_blank">PubChem LCSS ↗</a>'
        if sig_url:
            fds_links += f'<a class="glass-btn" style="text-decoration:none;" href="{sig_url}" target="_blank">Sigma-Aldrich ↗</a>'

        props_slot.clear()
        with props_slot:
            dens_txt = f"{dens:.2f} g/mL" if dens else "N/A"
            safe_html(
                f"""
                <div class="detail-box">
                  <div class="detail-title">Propriétés Physico-Chimiques</div>
                  <div class="kv-grid">
                    <div class="kv-item"><div class="kv-label">Formule &amp; Masse</div><div class="kv-val">{html.escape(formule)}</div></div>
                    <div class="kv-item"><div class="kv-label">Densité</div><div class="kv-val">{dens_txt}</div></div>
                    <div class="kv-item"><div class="kv-label">État physique</div><div class="kv-val">{html.escape(etat)}</div></div>
                    <div class="kv-item"><div class="kv-label">Rareté &amp; Coût</div><div class="kv-val">{html.escape(rarete)}</div></div>
                  </div>
                  <div class="kv-item" style="margin-top:10px;"><div class="kv-label">Conditions de stockage</div><div class="kv-val">{html.escape(stockage)}</div></div>
                </div>
                <div class="detail-box">
                  <div class="detail-title">Classification SGH &amp; FDS Officielles</div>
                  {render_pictograms_html(row.get("Pictogrammes danger"))}
                  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;">{fds_links}</div>
                </div>
                """
            )

    # ------------------------------------------------------------------
    # ONGLET 1 : CATALOGUE & SYNTHÈSES
    # ------------------------------------------------------------------
    def render_catalog_tab():
        all_rows = get_all_syntheses()
        reactions_list = sorted({
            clean_val(r.get(col))
            for r in all_rows
            for col in ("Réaction 1", "Réaction 2")
            if clean_val(r.get(col))
        })
        reactants_list = sorted({
            clean_val(r.get(f"Réactifs {i}"))
            for r in all_rows
            for i in range(1, 5)
            if clean_val(r.get(f"Réactifs {i}"))
        })

        filters = {"q": "", "rx": "Toutes", "rea": "Tous", "fav_only": False}

        with ui.element("div").classes("filter-bar"):
            q_input = ui.input(
                placeholder="Rechercher une molécule, un CAS, une réaction ou un réactif..."
            ).props("outlined dense clearable")
            rx_select = ui.select(
                ["Toutes"] + reactions_list, value="Toutes", label="Réaction"
            ).props("outlined dense")
            rea_select = ui.select(
                ["Tous"] + reactants_list, value="Tous", label="Réactif"
            ).props("outlined dense")
            fav_check = ui.checkbox("Favoris uniquement")
            export_btn = _btn("Export Excel (.xls)", style="height:40px;")

        meta_slot = ui.element("div").classes("catalog-meta-row")
        grid_slot = ui.element("div")

        def get_filtered_rows():
            rows = get_all_syntheses()
            favs = get_favorites(username)
            q = clean_val(filters["q"]).lower()
            rx_f = filters["rx"]
            rea_f = filters["rea"]
            out = []
            for r in rows:
                prod = clean_val(r.get("Produit final"))
                if filters["fav_only"] and prod not in favs:
                    continue
                if rx_f != "Toutes" and rx_f not in (clean_val(r.get("Réaction 1")), clean_val(r.get("Réaction 2"))):
                    continue
                if rea_f != "Tous" and rea_f not in [clean_val(r.get(f"Réactifs {i}")) for i in range(1, 5)]:
                    continue
                if q:
                    blob = " ".join(clean_val(r.get(c)) for c in BASE_COLS).lower()
                    if q not in blob:
                        continue
                out.append(r)
            return out, favs

        def reset_filters(_e=None):
            q_input.value = ""
            rx_select.value = "Toutes"
            rea_select.value = "Tous"
            fav_check.value = False
            filters.update(q="", rx="Toutes", rea="Tous", fav_only=False)
            refresh_grid()

        def refresh_grid():
            filtered, favs = get_filtered_rows()
            inv_map = get_inventory_map()

            meta_slot.clear()
            with meta_slot:
                safe_html(f"<span>{len(filtered)} FICHE(S) AFFICHÉE(S) · CLIC SUR UNE CARTE POUR OUVRIR L'INSPECTEUR 2D/3D</span>")
                if filters["q"] or filters["rx"] != "Toutes" or filters["rea"] != "Tous" or filters["fav_only"]:
                    _btn("Réinitialiser les filtres", style="padding:4px 10px;font-size:0.72rem;", on_click=reset_filters)

            grid_slot.clear()
            with grid_slot:
                if not filtered:
                    safe_html(
                        '<div class="hud-card"><div class="section-kicker">AUCUN RÉSULTAT</div>'
                        '<h2>Aucune molécule ne correspond à vos filtres</h2>'
                        '<p class="muted-text">Essayez un autre terme de recherche ou proposez une nouvelle fiche dans l\'onglet dédié.</p></div>'
                    )
                    return

                with ui.element("div").classes("catalog-grid"):
                    for row in filtered:
                        prod = clean_val(row.get("Produit final")) or "Sans nom"
                        cas = clean_val(row.get("Numéro CAS"))
                        rx1, rx2 = clean_val(row.get("Réaction 1")), clean_val(row.get("Réaction 2"))
                        rdt = clean_val(row.get("Rendement"))
                        formule = clean_val(row.get("Formule brute & masse"))
                        reas = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
                        img_2d = _fast_card_2d_url(cas, prod)
                        is_fav = prod in favs

                        cas_tag = f'<span class="mono-tag">CAS {html.escape(cas)}</span>' if cas else ""
                        rdt_tag = f'<span class="yield-tag">Rdt {html.escape(rdt)}</span>' if rdt else ""

                        with ui.element("article").classes("mol-card").on("click", make_open_fiche_handler(row)):
                            safe_html(HEX_WATERMARK_SVG)

                            with ui.element("div").classes("mol-card-top"):
                                with ui.element("div"):
                                    safe_html(f'<h3 class="mol-title">{html.escape(prod)}</h3>')
                                    safe_html(f'<div class="mol-subrow">{cas_tag}{rdt_tag}{_stock_badge_html(prod, inv_map)}</div>')

                                fav_cls = "fav-btn is-fav" if is_fav else "fav-btn"
                                fav_btn = ui.element("button").classes(fav_cls).props(
                                    'title="Ajouter / Retirer des favoris"'
                                ).on("click.stop", lambda _e, p=prod: (toggle_favorite(username, p), refresh_grid()))
                                with fav_btn:
                                    safe_html("★" if is_fav else "☆")

                            rx_badges = ""
                            if rx1:
                                rx_badges += f'<span class="rx-pill">{html.escape(rx1)}</span>'
                            if rx2:
                                rx_badges += f'<span class="muted-small">➔</span><span class="rx-pill">{html.escape(rx2)}</span>'

                            img_block = (
                                f'<img class="mol-2d-adaptive" src="{img_2d}" alt="{html.escape(prod)}" loading="lazy" />'
                                if img_2d else '<span class="muted-small">Aperçu 2D</span>'
                            )
                            safe_html(
                                f"""
                                <div class="mol-card-body">
                                  <div>
                                    <div class="rx-line">{rx_badges}</div>
                                    <div class="mol-info-line"><strong>Réactifs :</strong> {html.escape(", ".join(reas) or "N/A")}</div>
                                    <div class="mol-info-line"><strong>Formule :</strong> {html.escape(formule or "N/A")}</div>
                                    {render_pictograms_html(row.get("Pictogrammes danger"))}
                                  </div>
                                  <div class="mol-preview-box">{img_block}</div>
                                </div>
                                """
                            )

        q_input.on_value_change(lambda e: (filters.update(q=e.value or ""), refresh_grid()))
        rx_select.on_value_change(lambda e: (filters.update(rx=e.value or "Toutes"), refresh_grid()))
        rea_select.on_value_change(lambda e: (filters.update(rea=e.value or "Tous"), refresh_grid()))
        fav_check.on_value_change(lambda e: (filters.update(fav_only=bool(e.value)), refresh_grid()))
        export_btn.on(
            "click",
            lambda _e: ui.download(
                export_styled_table(get_filtered_rows()[0], BASE_COLS, title="Catalogue Syntheses ChemBase"),
                "ChemBase_Catalogue.xls",
            ),
        )

        refresh_grid()
        return refresh_grid

    # ------------------------------------------------------------------
    # ONGLET 5 : NOUVELLE FICHE (AVEC AUTO-REMPLISSAGE PUBCHEM)
    # ------------------------------------------------------------------
    def render_proposal_tab():
        with ui.element("div").classes("hud-card"):
            safe_html(
                '<div class="section-kicker">CONTRIBUTION R&amp;D · EXTRACTION PUBCHEM</div>'
                '<h2>Proposer une Nouvelle Fiche de Synthèse</h2>'
                '<p class="muted-text" style="margin-bottom:18px;">Saisissez un numéro CAS pour récupérer automatiquement la formule brute, la masse molaire, la densité, l\'état physique et les pictogrammes SGH depuis PubChem.</p>'
            )

            with ui.element("div").style("display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;margin-bottom:16px;"):
                in_cas = ui.input(label="Numéro CAS *", placeholder="Ex : 121-33-5 (Vanilline)").props("outlined dense")
                btn_fetch = _btn("Auto-remplir via PubChem", classes="glass-btn glass-btn-accent", style="height:40px;padding:0 18px;")

            with ui.element("div").classes("form-grid-2"):
                in_prod = ui.input(label="Produit final *").props("outlined dense")
                in_rdt = ui.input(label="Rendement de référence", placeholder="Ex : 78 %").props("outlined dense")
                in_rx1 = ui.input(label="Réaction 1 *", placeholder="Ex : Estérification de Fischer").props("outlined dense")
                in_rx2 = ui.input(label="Réaction 2 (optionnel)").props("outlined dense")
                in_rea1 = ui.input(label="Réactif 1 *").props("outlined dense")
                in_rea2 = ui.input(label="Réactif 2").props("outlined dense")
                in_rea3 = ui.input(label="Réactif 3 / Catalyseur").props("outlined dense")
                in_rea4 = ui.input(label="Réactif 4 / Solvant").props("outlined dense")
                in_form = ui.input(label="Formule brute & masse").props("outlined dense")
                in_etat = ui.input(label="État physique & densité").props("outlined dense")
                in_rarete = ui.input(label="Rareté & Coût").props("outlined dense")
                in_stock = ui.input(label="Conditions de stockage").props("outlined dense")

            in_sgh = ui.select(
                SGH_OPTIONS, multiple=True, value=[], label="Pictogrammes de danger SGH"
            ).props("outlined dense use-chips").style("margin-top:12px;width:100%;")

            with ui.element("div").classes("form-grid-2").style("margin-top:12px;"):
                in_cond = ui.textarea(label="Conditions opératoires", placeholder="Température, durée, atmosphère, traitement...").props("outlined rows=3")
                in_comm = ui.textarea(label="Commentaire / Notes R&D").props("outlined rows=3")

            async def on_pubchem_fill(_e=None):
                cas_val = clean_val(in_cas.value)
                if not cas_val:
                    ui.notify("Indiquez d'abord un numéro CAS.", type="warning")
                    return
                ui.notify(f"Interrogation PubChem pour {cas_val}...", type="info")
                res = await run.io_bound(fetch_full_pubchem_by_cas, cas_val)
                if not res:
                    ui.notify("Composé introuvable sur PubChem pour ce CAS.", type="negative")
                    return
                if not clean_val(in_prod.value) and res.get("titre"):
                    in_prod.value = res["titre"]
                in_form.value = res.get("formule", "")
                in_etat.value = res.get("etat", "")
                in_rarete.value = res.get("rarete", "")
                in_stock.value = res.get("stockage", "")
                in_sgh.value = res.get("pictos", [])
                ui.notify("Propriétés physico-chimiques extraites avec succès.", type="positive")

            def on_submit_fiche(_e=None):
                if not clean_val(in_prod.value) or not clean_val(in_rx1.value):
                    ui.notify("Les champs Produit final et Réaction 1 sont obligatoires.", type="warning")
                    return
                sgh_str = ", ".join([x.split(" - ")[0] for x in (in_sgh.value or [])])
                values_16 = [
                    clean_val(in_prod.value),
                    clean_val(in_rx1.value),
                    clean_val(in_rx2.value),
                    clean_val(in_rea1.value),
                    clean_val(in_rea2.value),
                    clean_val(in_rea3.value),
                    clean_val(in_rea4.value),
                    clean_val(in_rdt.value),
                    clean_val(in_cond.value),
                    clean_val(in_comm.value),
                    clean_val(in_cas.value),
                    clean_val(in_form.value),
                    clean_val(in_etat.value),
                    sgh_str,
                    clean_val(in_rarete.value),
                    clean_val(in_stock.value),
                ]
                insert_pending_synthese(values_16)
                ui.notify(f"Fiche « {clean_val(in_prod.value)} » envoyée en modération !", type="positive")
                for fld in (in_cas, in_prod, in_rdt, in_rx1, in_rx2, in_rea1, in_rea2, in_rea3, in_rea4, in_form, in_etat, in_rarete, in_stock, in_cond, in_comm):
                    fld.value = ""
                in_sgh.value = []
                if callable(on_data_changed):
                    on_data_changed()

            btn_fetch.on("click", on_pubchem_fill)

            with ui.element("div").style("display:flex;justify-content:flex-end;margin-top:18px;"):
                _btn(
                    "Soumettre la fiche en modération",
                    classes="glass-btn glass-btn-accent",
                    style="padding:10px 22px;",
                    on_click=on_submit_fiche,
                )

    return render_catalog_tab, render_proposal_tab