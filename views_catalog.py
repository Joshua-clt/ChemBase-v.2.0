import html
import json
import re
import urllib.parse
from typing import Any

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
    insert_direct_synthese,
    insert_pending_synthese,
    log_search,
    toggle_favorite,
)
from theme import safe_html

SGH_OPTIONS = [f"{code} - {lbl}" for code, (lbl, _fn) in SGH_DICT.items()]
SORT_OPTIONS = ["Nom (A → Z)", "Meilleur rendement", "Réalisables d'abord"]


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


def _copy_onclick(value: str, label: str = "") -> str:
    v_js = json.dumps(clean_val(value), ensure_ascii=False)
    l_js = json.dumps(clean_val(label or value), ensure_ascii=False)
    return html.escape(f"event.stopPropagation(); window.cbCopyText({v_js}, {l_js});", quote=True)


def _extract_yield_val(val: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)", clean_val(val).replace(",", "."))
    return float(m.group(1)) if m else -1.0


def _fast_card_2d_url(cas: str, prod: str) -> str:
    smi = FAST_SMILES_MAP.get(cas.lower()) or FAST_SMILES_MAP.get(prod.lower())
    if smi:
        return get_vector_depict_url(smi, style="cow", w=220, h=170, zoom=2.5) or ""
    if cas:
        return f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/{urllib.parse.quote(cas)}/PNG?image_size=300x300"
    return ""


def _stock_badge_html(name: str, inv_map: dict[str, Any]) -> str:
    info = inv_map.get(clean_val(name).lower())
    if not info:
        return ""
    qty, unit, seuil, _dens = info
    if qty <= 0:
        return '<span class="stock-pill stock-empty">Rupture</span>'
    if qty <= seuil:
        return f'<span class="stock-pill stock-low">Bas · {qty:g} {html.escape(unit)}</span>'
    return f'<span class="stock-pill stock-ok">Stock · {qty:g} {html.escape(unit)}</span>'


def _check_synthesis_feasibility(row: dict[str, Any], inv_map: dict[str, Any]) -> dict[str, Any]:
    reas = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
    missing: list[str] = []
    low: list[str] = []
    available = 0
    for rea in reas:
        info = inv_map.get(rea.lower())
        if not info or info[0] <= 0:
            missing.append(rea)
        else:
            available += 1
            if info[0] <= info[2]:
                low.append(rea)
    return {
        "total": len(reas),
        "available": available,
        "missing": missing,
        "low": low,
        "has_missing": len(missing) > 0,
    }


def _reactant_skeleton_html() -> str:
    return """
    <div class="modal-grid">
      <div>
        <div class="detail-box">
          <div class="skeleton-line" style="width:45%;"></div>
          <div class="kv-grid">
            <div class="skeleton-box" style="height:52px;"></div>
            <div class="skeleton-box" style="height:52px;"></div>
            <div class="skeleton-box" style="height:52px;"></div>
            <div class="skeleton-box" style="height:52px;"></div>
          </div>
        </div>
        <div class="detail-box">
          <div class="skeleton-line" style="width:40%;"></div>
          <div class="skeleton-line" style="width:80%;"></div>
          <div class="skeleton-line" style="width:60%;"></div>
        </div>
      </div>
      <div>
        <div class="detail-box">
          <div class="skeleton-line" style="width:35%;"></div>
          <div class="skeleton-box" style="height:190px;"></div>
        </div>
      </div>
    </div>
    """


def build_catalog_and_proposal_views(app_state: dict[str, Any], on_data_changed=None, on_launch_in_labo=None):
    fiche_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with fiche_dialog:
        fiche_body = ui.element("div").classes("cb-modal-card")

    inspector_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with inspector_dialog:
        inspector_body = ui.element("div").classes("cb-inspector-card")

    prefill_bridge: dict[str, Any] = {"fn": None}

    def make_open_fiche_handler(target_row: dict[str, Any], close_inspector: bool = False):
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
                svg_url = get_vector_depict_url(rxn_smi, style="cow", w=620, h=170, zoom=2.3) or ""
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
                safe_html(_reactant_skeleton_html())

        inspector_dialog.open()

        data = await run.io_bound(fetch_reactant_inspector_data, rea_clean)
        pc_url, sig_url = await run.io_bound(get_safety_fds_links, clean_val(data.get("cas")), rea_clean)
        depict_url = (get_vector_depict_url(data["smiles"], style="cow", w=260, h=190, zoom=2.6) or "") if data.get("smiles") else ""
        stock_html = _stock_badge_html(rea_clean, inv_map) or '<span class="stock-pill stock-empty">Non référencé en stock</span>'

        cas_val = clean_val(data.get("cas"))
        cas_cell = (
            f'<div class="kv-item copyable-tag" title="Cliquer pour copier le CAS" onclick="{_copy_onclick(cas_val, f"CAS {cas_val}")}">'
            f'<div class="kv-label">Numéro CAS (clic = copier)</div><div class="kv-val">{html.escape(cas_val)}</div></div>'
            if cas_val
            else '<div class="kv-item"><div class="kv-label">Numéro CAS</div><div class="kv-val">N/A</div></div>'
        )
        form_val = clean_val(data.get("formule"))
        form_cell = (
            f'<div class="kv-item copyable-tag" title="Cliquer pour copier la formule" onclick="{_copy_onclick(form_val, form_val)}">'
            f'<div class="kv-label">Formule brute</div><div class="kv-val">{html.escape(form_val)}</div></div>'
        )
        iupac_html = f'<p class="muted-small" style="margin-top:10px;"><strong>IUPAC :</strong> {html.escape(clean_val(data.get("iupac")))}</p>' if data.get("iupac") else ""

        op_enc = urllib.parse.quote(str(app_state.get("username", "chercheur")))
        label_url = (
            f"/api/label?nom={urllib.parse.quote(rea_clean)}"
            f"&cas={urllib.parse.quote(cas_val)}"
            f"&formule={urllib.parse.quote(form_val)}"
            f"&pictos={urllib.parse.quote(clean_val(data.get('pictos')))}"
            f"&op={op_enc}"
        )

        fds_btns = f'<a class="glass-btn" style="text-decoration:none;" href="{label_url}" target="_blank">Étiquette flacon ↗</a>'
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
                            {form_cell}
                            <div class="kv-item"><div class="kv-label">Masse molaire</div><div class="kv-val">{html.escape(clean_val(data.get('masse_molaire')) or 'N/A')}</div></div>
                            <div class="kv-item"><div class="kv-label">Densité</div><div class="kv-val">{html.escape(clean_val(data.get('densite')) or 'N/A')}</div></div>
                            {cas_cell}
                          </div>
                          {iupac_html}
                          <div style="margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                            <span class="muted-small">Stock laboratoire :</span> {stock_html}
                          </div>
                        </div>
                        <div class="detail-box">
                          <div class="detail-title">Dangers SGH, Étiquette &amp; FDS</div>
                          {render_pictograms_html(clean_val(data.get("pictos")))}
                          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;">{fds_btns}</div>
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

    async def open_fiche(row: dict[str, Any]):
        sid = row.get("id")
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
        pictos = clean_val(row.get("Pictogrammes danger"))
        reactants = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
        inv_map = get_inventory_map()
        feas = _check_synthesis_feasibility(row, inv_map)
        img_2d = _fast_card_2d_url(cas, prod)
        viewer_mode = {"mode": "2d"}

        cas_tag = (
            f'<span class="mono-tag copyable-tag" title="Cliquer pour copier le CAS" onclick="{_copy_onclick(cas, f"CAS {cas}")}">CAS {html.escape(cas)} ⧉</span>'
            if cas
            else ""
        )
        rdt_tag = f'<span class="yield-tag">Rdt {html.escape(rdt)}</span>' if rdt else ""
        comm_html = f'<p class="muted-text"><strong style="color:var(--txt);">Notes R&amp;D :</strong> {html.escape(comm)}</p>' if comm else ""

        if feas["has_missing"]:
            feas_pill = f'<span class="stock-pill stock-empty">Non réalisable · {len(feas["missing"])} réactif(s) manquant(s)</span>'
        elif feas["low"]:
            feas_pill = f'<span class="stock-pill stock-low">Réalisable · {feas["available"]}/{feas["total"]} réactifs (seuil bas)</span>'
        elif feas["total"] > 0:
            feas_pill = f'<span class="stock-pill stock-ok">Synthèse réalisable · {feas["available"]}/{feas["total"]} réactifs dispo</span>'
        else:
            feas_pill = ""

        op_enc = urllib.parse.quote(str(app_state.get("username", "chercheur")))
        label_url = (
            f"/api/label?nom={urllib.parse.quote(prod)}"
            f"&cas={urllib.parse.quote(cas)}"
            f"&formule={urllib.parse.quote(formule)}"
            f"&pictos={urllib.parse.quote(pictos)}"
            f"&stockage={urllib.parse.quote(stockage)}"
            f"&op={op_enc}"
        )
        print_url = f"/api/print/fiche/{int(sid)}" if sid else ""

        def launch_labo(_e=None):
            fiche_dialog.close()
            if callable(on_launch_in_labo):
                on_launch_in_labo(prod)

        fiche_body.clear()
        with fiche_body:
            with ui.element("div").classes("modal-head"):
                with ui.element("div"):
                    safe_html('<div class="section-kicker">SPÉCIFICATION TECHNIQUE &amp; SYNTHÈSE</div>')
                    safe_html(
                        f'<h2 style="margin:4px 0 4px 0;font-size:1.45rem;">{html.escape(prod)}</h2>'
                        f'<div class="mol-subrow">{cas_tag}{rdt_tag}{_stock_badge_html(prod, inv_map)}{feas_pill}</div>'
                    )
                with ui.element("div").style("display:flex;gap:7px;flex-wrap:wrap;align-items:center;"):
                    _btn(
                        "Lancer dans le Cahier de Labo",
                        classes="glass-btn glass-btn-accent",
                        on_click=launch_labo,
                    )
                    safe_html(f'<a class="glass-btn" style="text-decoration:none;" href="{label_url}" target="_blank">Étiquette flacon</a>')
                    if print_url:
                        safe_html(f'<a class="glass-btn" style="text-decoration:none;" href="{print_url}" target="_blank">Imprimer / PDF</a>')
                    else:
                        _btn(
                            "Exporter HTML",
                            on_click=lambda _e, r=row, p=prod: ui.download(
                                generate_molecule_html(r), f"Fiche_{sanitize_filename(p)}.html"
                            ),
                        )
                    _btn("Fermer ✕", on_click=lambda _e: fiche_dialog.close())

            if feas["has_missing"]:
                safe_html(
                    f'<div class="warning-banner" style="padding:10px 14px;margin-bottom:14px;">'
                    f'<span style="font-size:0.84rem;color:var(--txt);">'
                    f'<strong style="color:var(--danger);">Réactif(s) en rupture ou absent(s) du stock :</strong> '
                    f'{html.escape(", ".join(feas["missing"]))}</span></div>'
                )

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
                            safe_html('<div class="rxn-canvas-box"><div class="skeleton-box" style="height:105px;"></div></div>')

                    with ui.element("div").classes("detail-box"):
                        safe_html('<div class="detail-title">Réactifs &amp; Catalyseurs (cliquer pour inspecter)</div>')
                        if not reactants:
                            safe_html('<span class="muted-small">Aucun réactif renseigné.</span>')
                        else:
                            with ui.element("div").style("display:flex;flex-wrap:wrap;gap:8px;"):
                                for rea in reactants:
                                    s_info = inv_map.get(rea.lower())
                                    if not s_info or s_info[0] <= 0:
                                        dot = '<span class="status-dot status-err"></span>'
                                    elif s_info[0] <= s_info[2]:
                                        dot = '<span class="status-dot status-warn"></span>'
                                    else:
                                        dot = '<span class="status-dot status-ok"></span>'
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
                    form_copy_attr = _copy_onclick(formule, formule) if formule != "N/A" else ""
                    form_cls = "kv-item copyable-tag" if formule != "N/A" else "kv-item"
                    form_click = f'onclick="{form_copy_attr}" title="Cliquer pour copier la formule"' if form_copy_attr else ""

                    with props_slot:
                        safe_html(
                            f"""
                            <div class="detail-box">
                              <div class="detail-title">Propriétés Physico-Chimiques</div>
                              <div class="kv-grid">
                                <div class="{form_cls}" {form_click}><div class="kv-label">Formule &amp; Masse</div><div class="kv-val">{html.escape(formule)}</div></div>
                                <div class="kv-item"><div class="kv-label">Densité</div><div class="skeleton-line" style="width:65%;margin:6px 0 0 0;"></div></div>
                                <div class="kv-item"><div class="kv-label">État physique</div><div class="kv-val">{html.escape(etat)}</div></div>
                                <div class="kv-item"><div class="kv-label">Rareté &amp; Coût</div><div class="kv-val">{html.escape(rarete)}</div></div>
                              </div>
                            </div>
                            <div class="detail-box">
                              <div class="detail-title">Classification SGH &amp; FDS</div>
                              {render_pictograms_html(pictos)}
                              <div class="skeleton-line" style="width:55%;margin-top:12px;"></div>
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
                rxn_svg = get_vector_depict_url(rxn_smi, style="cow", w=580, h=155, zoom=2.3) or ""
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
                    <div class="{form_cls}" {form_click}><div class="kv-label">Formule &amp; Masse</div><div class="kv-val">{html.escape(formule)}</div></div>
                    <div class="kv-item"><div class="kv-label">Densité</div><div class="kv-val">{dens_txt}</div></div>
                    <div class="kv-item"><div class="kv-label">État physique</div><div class="kv-val">{html.escape(etat)}</div></div>
                    <div class="kv-item"><div class="kv-label">Rareté &amp; Coût</div><div class="kv-val">{html.escape(rarete)}</div></div>
                  </div>
                  <div class="kv-item" style="margin-top:10px;"><div class="kv-label">Conditions de stockage</div><div class="kv-val">{html.escape(stockage)}</div></div>
                </div>
                <div class="detail-box">
                  <div class="detail-title">Classification SGH &amp; FDS Officielles</div>
                  {render_pictograms_html(pictos)}
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

        filters: dict[str, Any] = {
            "q": "",
            "rx": "Toutes",
            "rea": "Tous",
            "sort": SORT_OPTIONS[0],
            "fav_only": False,
            "feasible_only": False,
        }
        log_timer: dict[str, Any] = {"ref": None}

        with ui.element("div").classes("filter-bar"):
            q_input = ui.input(
                placeholder="Rechercher une molécule, un CAS, une réaction ou un réactif..."
            ).props("outlined dense clearable")
            rx_select = ui.select(["Toutes"] + reactions_list, value="Toutes", label="Réaction").props("outlined dense")
            rea_select = ui.select(["Tous"] + reactants_list, value="Tous", label="Réactif").props("outlined dense")
            sort_select = ui.select(SORT_OPTIONS, value=SORT_OPTIONS[0], label="Trier par").props("outlined dense")
            export_btn = _btn("Export Excel (.xls)", style="height:40px;")

        with ui.element("div").classes("filter-subbar"):
            with ui.element("div").style("display:flex;align-items:center;gap:16px;flex-wrap:wrap;"):
                fav_check = ui.checkbox("Favoris uniquement")
                feas_check = ui.checkbox("Réalisables uniquement (masquer ruptures)")
            meta_slot = ui.element("div").classes("catalog-meta-row").style("margin-bottom:0;")

        grid_slot = ui.element("div")

        def current_username() -> str:
            return str(app_state.get("username", "chercheur"))

        def get_filtered_rows():
            rows = get_all_syntheses()
            favs = get_favorites(current_username())
            inv_map = get_inventory_map()
            q = clean_val(filters["q"]).lower()
            rx_f = str(filters["rx"])
            rea_f = str(filters["rea"])
            out: list[tuple[dict[str, Any], dict[str, Any]]] = []
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
                feas = _check_synthesis_feasibility(r, inv_map)
                if filters["feasible_only"] and feas["has_missing"]:
                    continue
                out.append((r, feas))

            sort_mode = str(filters["sort"])
            if sort_mode == "Meilleur rendement":
                out.sort(key=lambda pair: (-_extract_yield_val(clean_val(pair[0].get("Rendement"))), clean_val(pair[0].get("Produit final")).lower()))
            elif sort_mode == "Réalisables d'abord":
                out.sort(key=lambda pair: (1 if pair[1]["has_missing"] else 0, clean_val(pair[0].get("Produit final")).lower()))
            else:
                out.sort(key=lambda pair: clean_val(pair[0].get("Produit final")).lower())

            return out, favs, inv_map

        def reset_filters(_e=None):
            q_input.value = ""
            rx_select.value = "Toutes"
            rea_select.value = "Tous"
            sort_select.value = SORT_OPTIONS[0]
            fav_check.value = False
            feas_check.value = False
            filters.update(q="", rx="Toutes", rea="Tous", sort=SORT_OPTIONS[0], fav_only=False, feasible_only=False)
            refresh_grid()

        def schedule_zero_result_log(q_text: str):
            if log_timer["ref"] is not None:
                log_timer["ref"].cancel()
                log_timer["ref"] = None
            if len(clean_val(q_text)) < 2:
                return
            log_timer["ref"] = ui.timer(
                1.5,
                lambda q=q_text, rx=str(filters["rx"]), rea=str(filters["rea"]): log_search(q, "", rx, rea, 0),
                once=True,
            )

        def refresh_grid():
            filtered_pairs, favs, inv_map = get_filtered_rows()

            if len(filtered_pairs) == 0 and clean_val(filters["q"]):
                schedule_zero_result_log(str(filters["q"]))
            elif log_timer["ref"] is not None:
                log_timer["ref"].cancel()
                log_timer["ref"] = None

            missing_cards = sum(1 for _r, feas in filtered_pairs if feas["has_missing"])
            has_active_filter = any([
                filters["q"],
                filters["rx"] != "Toutes",
                filters["rea"] != "Tous",
                filters["fav_only"],
                filters["feasible_only"],
                filters["sort"] != SORT_OPTIONS[0],
            ])

            meta_slot.clear()
            with meta_slot:
                warn_txt = f" · {missing_cards} AVEC RÉACTIF MANQUANT" if missing_cards > 0 else ""
                safe_html(f"<span>{len(filtered_pairs)} FICHE(S){warn_txt}</span>")
                if has_active_filter:
                    _btn("Réinitialiser", style="padding:4px 10px;font-size:0.72rem;", on_click=reset_filters)

            grid_slot.clear()
            with grid_slot:
                if not filtered_pairs:
                    safe_html(
                        '<div class="hud-card"><div class="section-kicker">AUCUN RÉSULTAT</div>'
                        '<h2>Aucune molécule ne correspond à vos filtres</h2>'
                        '<p class="muted-text">Cette recherche est enregistrée pour la veille catalogue. Vous pouvez aussi proposer cette fiche dans l\'onglet dédié.</p></div>'
                    )
                    return

                with ui.element("div").classes("catalog-grid"):
                    for row, feas in filtered_pairs:
                        prod = clean_val(row.get("Produit final")) or "Sans nom"
                        cas = clean_val(row.get("Numéro CAS"))
                        rx1, rx2 = clean_val(row.get("Réaction 1")), clean_val(row.get("Réaction 2"))
                        rdt = clean_val(row.get("Rendement"))
                        formule = clean_val(row.get("Formule brute & masse"))
                        reas = [clean_val(row.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(row.get(f"Réactifs {i}"))]
                        img_2d = _fast_card_2d_url(cas, prod)
                        is_fav = prod in favs

                        card_cls = "mol-card mol-card-missing" if feas["has_missing"] else "mol-card"
                        cas_tag = (
                            f'<span class="mono-tag copyable-tag" title="Cliquer pour copier le CAS" onclick="{_copy_onclick(cas, f"CAS {cas}")}">CAS {html.escape(cas)}</span>'
                            if cas
                            else ""
                        )
                        rdt_tag = f'<span class="yield-tag">Rdt {html.escape(rdt)}</span>' if rdt else ""
                        miss_tag = (
                            f'<span class="stock-pill stock-empty">Manque : {html.escape(feas["missing"][0])}{" +" if len(feas["missing"]) > 1 else ""}</span>'
                            if feas["has_missing"]
                            else ""
                        )

                        with ui.element("article").classes(card_cls).on("click", make_open_fiche_handler(row)):
                            safe_html(HEX_WATERMARK_SVG)

                            with ui.element("div").classes("mol-card-top"):
                                with ui.element("div"):
                                    safe_html(f'<h3 class="mol-title">{html.escape(prod)}</h3>')
                                    safe_html(f'<div class="mol-subrow">{cas_tag}{rdt_tag}{_stock_badge_html(prod, inv_map)}{miss_tag}</div>')

                                fav_cls = "fav-btn is-fav" if is_fav else "fav-btn"
                                fav_btn = ui.element("button").classes(fav_cls).props(
                                    'title="Ajouter / Retirer des favoris"'
                                ).on("click.stop", lambda _e, p=prod: (toggle_favorite(current_username(), p), refresh_grid()))
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
                                    {render_pictograms_html(clean_val(row.get("Pictogrammes danger")))}
                                  </div>
                                  <div class="mol-preview-box">{img_block}</div>
                                </div>
                                """
                            )

        q_input.on_value_change(lambda e: (filters.update(q=e.value or ""), refresh_grid()))
        rx_select.on_value_change(lambda e: (filters.update(rx=e.value or "Toutes"), refresh_grid()))
        rea_select.on_value_change(lambda e: (filters.update(rea=e.value or "Tous"), refresh_grid()))
        sort_select.on_value_change(lambda e: (filters.update(sort=e.value or SORT_OPTIONS[0]), refresh_grid()))
        fav_check.on_value_change(lambda e: (filters.update(fav_only=bool(e.value)), refresh_grid()))
        feas_check.on_value_change(lambda e: (filters.update(feasible_only=bool(e.value)), refresh_grid()))
        export_btn.on(
            "click",
            lambda _e: ui.download(
                export_styled_table([r for r, _f in get_filtered_rows()[0]], BASE_COLS, title="Catalogue Syntheses ChemBase"),
                "ChemBase_Catalogue.xls",
            ),
        )

        refresh_grid()
        return refresh_grid

    # ------------------------------------------------------------------
    # ONGLET 5 : NOUVELLE FICHE (AUTO-REMPLISSAGE PUBCHEM + PUBLICATION DIRECTE SUPER-ADMIN)
    # ------------------------------------------------------------------
    def render_proposal_tab():
        auth_u = app_state.get("auth_user") or {}
        is_super = auth_u.get("role") == "superadmin"

        with ui.element("div").classes("hud-card"):
            kicker_txt = "CONTRIBUTION R&amp;D · PUBLICATION DIRECTE SUPER-ADMIN" if is_super else "CONTRIBUTION R&amp;D · EXTRACTION PUBCHEM"
            title_txt = "Ajouter ou Proposer une Fiche de Synthèse" if is_super else "Proposer une Nouvelle Fiche de Synthèse"
            safe_html(
                f'<div class="section-kicker">{kicker_txt}</div>'
                f'<h2>{title_txt}</h2>'
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

            direct_publish_chk = None
            if is_super:
                direct_publish_chk = ui.checkbox(
                    "Publier directement dans le Catalogue (sans passer par la modération)",
                    value=True,
                ).style("margin-top:14px;")

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

            def apply_external_prefill(cas_val: str = "", name_val: str = "", smiles_note: str = ""):
                if clean_val(cas_val):
                    in_cas.value = clean_val(cas_val)
                if clean_val(name_val):
                    in_prod.value = clean_val(name_val)
                if clean_val(smiles_note):
                    prev = clean_val(in_comm.value)
                    in_comm.value = f"{prev}\nSMILES : {clean_val(smiles_note)}".strip()

            prefill_bridge["fn"] = apply_external_prefill

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
                actor = str(app_state.get("username", "chercheur"))
                if is_super and direct_publish_chk is not None and bool(direct_publish_chk.value):
                    insert_direct_synthese(values_16, admin_username=actor)
                    ui.notify(f"Fiche « {clean_val(in_prod.value)} » publiée directement dans le Catalogue !", type="positive")
                else:
                    insert_pending_synthese(values_16, author_username=actor)
                    ui.notify(f"Fiche « {clean_val(in_prod.value)} » envoyée en modération !", type="positive")

                for fld in (in_cas, in_prod, in_rdt, in_rx1, in_rx2, in_rea1, in_rea2, in_rea3, in_rea4, in_form, in_etat, in_rarete, in_stock, in_cond, in_comm):
                    fld.value = ""
                in_sgh.value = []
                if callable(on_data_changed):
                    on_data_changed()

            btn_fetch.on("click", on_pubchem_fill)

            with ui.element("div").style("display:flex;justify-content:flex-end;margin-top:18px;"):
                btn_lbl = "Enregistrer / Publier la fiche" if is_super else "Soumettre la fiche en modération"
                _btn(
                    btn_lbl,
                    classes="glass-btn glass-btn-accent",
                    style="padding:10px 22px;",
                    on_click=on_submit_fiche,
                )

    def trigger_prefill(cas_val: str = "", name_val: str = "", smiles_note: str = ""):
        if callable(prefill_bridge["fn"]):
            prefill_bridge["fn"](cas_val, name_val, smiles_note)

    return render_catalog_tab, render_proposal_tab, open_fiche, trigger_prefill