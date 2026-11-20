import html
import mimetypes
from datetime import datetime
from typing import Any
from nicegui import run, ui

from chem_data import (
    clean_val,
    export_styled_table,
    get_known_density,
    get_molecular_weight,
)
from database import (
    deduct_inventory_by_name,
    delete_labo_entry,
    get_all_labo_entries,
    get_all_syntheses,
    get_inventory_map,
    insert_labo_entry,
)
from theme import safe_html

STATUTS_ESSAI = ["Validé", "En cours", "À optimiser", "Échec"]
MAX_ATTACHMENT_BYTES = 3 * 1024 * 1024  # 3 Mo max pour garder SQLite et GitHub rapides


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


def _compute_stoich_data(row: dict[str, Any], target_mass_g: float, eq_list: list[float]) -> dict[str, Any]:
    prod = clean_val(row.get("Produit final"))
    cas = clean_val(row.get("Numéro CAS"))
    formule = clean_val(row.get("Formule brute & masse"))
    mw_prod = get_molecular_weight(cas or prod, fallback_str=formule)
    n_target = (target_mass_g / mw_prod) if (mw_prod and mw_prod > 0) else None
    inv_map = get_inventory_map()

    items: list[dict[str, Any]] = []
    for idx in range(1, 5):
        rea = clean_val(row.get(f"Réactifs {idx}"))
        if not rea:
            continue
        eq = float(eq_list[idx - 1]) if idx - 1 < len(eq_list) else 1.0
        mw_r = get_molecular_weight(rea)
        inv = inv_map.get(rea.lower())
        dens = inv[3] if inv else get_known_density(rea, 1.0)
        stock_str = f"{inv[0]:g} {inv[1]}" if inv else "Non suivi"
        mass_g = (n_target * eq * mw_r) if (n_target is not None and mw_r) else None
        vol_ml = (mass_g / dens) if (mass_g is not None and dens > 0) else None
        items.append({
            "nom": rea,
            "eq": eq,
            "mw": mw_r,
            "dens": dens,
            "mass_g": mass_g,
            "vol_ml": vol_ml,
            "stock_str": stock_str,
        })
    return {"mw_prod": mw_prod, "n_target": n_target, "items": items}


def build_labo_view(app_state: dict[str, Any], on_data_changed=None):
    select_bridge: dict[str, Any] = {"fn": None}

    confirm_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with confirm_dialog:
        confirm_body = ui.element("div").classes("cb-confirm-card")

    def open_confirm_delete(label_name: str, on_confirm):
        confirm_body.clear()
        with confirm_body:
            safe_html(
                '<div class="section-kicker" style="color:var(--danger);">CONFIRMATION REQUISE</div>'
                f'<h2 style="margin:6px 0 8px 0;font-size:1.2rem;">Supprimer cet essai ?</h2>'
                f'<p class="muted-text" style="margin-bottom:18px;">L\'archive « {html.escape(label_name)} » sera retirée définitivement du Cahier de Laboratoire.</p>'
            )
            with ui.element("div").style("display:flex;justify-content:flex-end;gap:10px;"):
                _btn("Annuler", on_click=lambda _e: confirm_dialog.close())
                _btn(
                    "Confirmer la suppression",
                    classes="glass-btn glass-btn-danger",
                    on_click=lambda _e: (confirm_dialog.close(), on_confirm()),
                )
        confirm_dialog.open()

    def render_labo_tab():
        all_rows = get_all_syntheses()
        rows_by_name = {clean_val(r.get("Produit final")): r for r in all_rows if clean_val(r.get("Produit final"))}
        prod_names = list(rows_by_name.keys())

        calc_state: dict[str, Any] = {
            "last_items": [],
            "uploaded_name": "",
            "uploaded_mime": "",
            "uploaded_bytes": None,
        }

        def current_user() -> str:
            return str(app_state.get("username", "chercheur"))

        def is_superadmin() -> bool:
            auth_u = app_state.get("auth_user") or {}
            return auth_u.get("role") == "superadmin"

        with ui.element("div").classes("modal-grid").style("margin-bottom:20px;"):
            with ui.element("div").classes("hud-card"):
                safe_html(
                    '<div class="section-kicker">STŒCHIOMÉTRIE AUTOMATIQUE</div>'
                    '<h2>Calculateur de Paillasse</h2>'
                    '<p class="muted-text" style="margin-bottom:14px;">Sélectionnez une synthèse du catalogue et la masse cible souhaitée : ChemBase calcule les masses (g), volumes (mL) et permet de déduire les réactifs du stock.</p>'
                )

                with ui.element("div").classes("form-grid-2"):
                    sel_prod = ui.select(
                        prod_names,
                        value=prod_names[0] if prod_names else None,
                        label="Synthèse cible",
                        with_input=True,
                    ).props("outlined dense")
                    in_target_g = ui.number(
                        label="Masse théorique visée (g)",
                        value=5.0,
                        min=0.05,
                        step=0.5,
                        format="%.2f",
                    ).props("outlined dense")

                with ui.element("div").style("display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:10px;"):
                    eq1 = ui.number(label="Éq. R1", value=1.0, min=0.01, step=0.1, format="%.2f").props("outlined dense")
                    eq2 = ui.number(label="Éq. R2", value=1.0, min=0.01, step=0.1, format="%.2f").props("outlined dense")
                    eq3 = ui.number(label="Éq. R3", value=0.1, min=0.0, step=0.05, format="%.2f").props("outlined dense")
                    eq4 = ui.number(label="Éq. R4", value=1.0, min=0.0, step=0.1, format="%.2f").props("outlined dense")

                stoich_slot = ui.element("div").style("margin-top:14px;")

            with ui.element("div").classes("hud-card"):
                safe_html(
                    '<div class="section-kicker">CAHIER DE LABORATOIRE · TRAÇABILITÉ NOMINATIVE</div>'
                    '<h2>Archiver un Essai de Synthèse</h2>'
                )

                with ui.element("div").classes("form-grid-2"):
                    in_date = ui.input(label="Date de l'essai", value=datetime.now().strftime("%Y-%m-%d")).props("outlined dense")
                    in_op = ui.input(label="Opérateur (verrouillé)", value=current_user()).props("outlined dense readonly")
                    in_cible = ui.input(label="Produit synthétisé *", value=prod_names[0] if prod_names else "").props("outlined dense")
                    in_statut = ui.select(STATUTS_ESSAI, value="Validé", label="Statut de l'essai").props("outlined dense")
                    in_m_theo = ui.number(label="Masse théorique (g)", value=5.0, min=0.01, step=0.1, format="%.2f").props("outlined dense")
                    in_m_obt = ui.number(label="Masse obtenue (g)", value=3.8, min=0.0, step=0.1, format="%.2f").props("outlined dense")

                in_qtes = ui.input(label="Quantités engagées (auto-rempli par le calculateur)").props("outlined dense").style("margin-top:10px;width:100%;")
                in_obs = ui.textarea(label="Observations, CCM, RMN, point de fusion...").props("outlined rows=2").style("margin-top:10px;width:100%;")

                yield_live_slot = ui.element("div").style("margin-top:10px;")

                def update_live_yield():
                    mt = float(in_m_theo.value or 0.0)
                    mo = float(in_m_obt.value or 0.0)
                    rdt = (mo / mt * 100.0) if mt > 0 else 0.0
                    col = "var(--accent)" if rdt >= 70 else ("var(--warn)" if rdt >= 40 else "var(--danger)")
                    yield_live_slot.clear()
                    with yield_live_slot:
                        safe_html(
                            f'<div class="detail-box" style="margin-bottom:0;padding:10px 14px;display:flex;justify-content:space-between;align-items:center;">'
                            f'<span class="muted-small">Rendement réel calculé</span>'
                            f'<strong style="font-family:\'JetBrains Mono\',monospace;font-size:1.15rem;color:{col};">{rdt:.1f} %</strong>'
                            f'</div>'
                        )

                in_m_theo.on_value_change(lambda _e: update_live_yield())
                in_m_obt.on_value_change(lambda _e: update_live_yield())
                update_live_yield()

                upload_status = ui.element("div").style("margin-top:8px;")

                async def handle_upload(e):
                    try:
                        if hasattr(e, "file"):
                            orig_name = str(e.file.name)
                            raw_bytes = await e.file.read()
                            mime_type = getattr(e.file, "content_type", "") or ""
                        else:
                            orig_name = str(getattr(e, "name", "spectre.bin"))
                            raw_bytes = e.content.read()
                            mime_type = str(getattr(e, "type", "") or "")

                        if len(raw_bytes) > MAX_ATTACHMENT_BYTES:
                            ui.notify("Fichier trop volumineux (maximum 3 Mo pour la persistance SQLite / Render).", type="negative")
                            return

                        final_mime = mime_type or mimetypes.guess_type(orig_name)[0] or "application/octet-stream"
                        calc_state["uploaded_name"] = orig_name
                        calc_state["uploaded_mime"] = final_mime
                        calc_state["uploaded_bytes"] = bytes(raw_bytes)
                        size_kb = len(raw_bytes) / 1024.0
                        upload_status.clear()
                        with upload_status:
                            safe_html(
                                f'<span class="stock-pill stock-ok">Stocké dans SQLite : {html.escape(orig_name)} ({size_kb:.0f} Ko)</span>'
                            )
                    except Exception as ex:
                        ui.notify(f"Erreur lors de l'import : {ex}", type="negative")

                ui.upload(
                    label="Joindre un spectre / CCM / PDF (max 3 Mo · persistant SQLite)",
                    auto_upload=True,
                    max_files=1,
                    max_file_size=MAX_ATTACHMENT_BYTES,
                    on_upload=handle_upload,
                ).props("flat bordered color=cyan").style("margin-top:10px;width:100%;")

                def save_entry(_e=None):
                    cible = clean_val(in_cible.value)
                    if not cible:
                        ui.notify("Indiquez le produit synthétisé.", type="warning")
                        return
                    mt = float(in_m_theo.value or 0.0)
                    mo = float(in_m_obt.value or 0.0)
                    rdt_reel = (mo / mt * 100.0) if mt > 0 else 0.0
                    ref_row = rows_by_name.get(cible, {})
                    rdt_theo = clean_val(ref_row.get("Rendement")) or "N/A"
                    op_locked = current_user()

                    insert_labo_entry(
                        date_essai=clean_val(in_date.value) or datetime.now().strftime("%Y-%m-%d"),
                        operateur=op_locked,
                        produit_cible=cible,
                        quantites_engagees=clean_val(in_qtes.value) or "Non précisé",
                        masse_theorique=mt,
                        masse_obtenue=mo,
                        rendement_reel=rdt_reel,
                        rendement_theorique=rdt_theo,
                        statut=in_statut.value or "Validé",
                        observations=clean_val(in_obs.value),
                        attachment_name=str(calc_state["uploaded_name"]),
                        attachment_mime=str(calc_state["uploaded_mime"]),
                        attachment_data=calc_state["uploaded_bytes"],
                    )
                    calc_state["uploaded_name"] = ""
                    calc_state["uploaded_mime"] = ""
                    calc_state["uploaded_bytes"] = None
                    upload_status.clear()
                    in_obs.value = ""
                    ui.notify(f"Essai « {cible} » ({rdt_reel:.1f} %) archivé sous {op_locked}.", type="positive")
                    refresh_history()
                    if callable(on_data_changed):
                        on_data_changed()

                with ui.element("div").style("display:flex;justify-content:flex-end;margin-top:14px;"):
                    _btn("Archiver l'essai", classes="glass-btn glass-btn-accent", style="padding:9px 20px;", on_click=save_entry)

        async def update_stoich(_e=None):
            fresh_rows = get_all_syntheses()
            rows_by_name.clear()
            for r in fresh_rows:
                pn = clean_val(r.get("Produit final"))
                if pn:
                    rows_by_name[pn] = r
            sel_prod.options = list(rows_by_name.keys())
            sel_prod.update()

            p_name = sel_prod.value
            row = rows_by_name.get(p_name) if isinstance(p_name, str) else None
            if not row or not isinstance(p_name, str):
                stoich_slot.clear()
                with stoich_slot:
                    safe_html('<span class="muted-small">Aucune synthèse sélectionnée.</span>')
                return

            target_g = float(in_target_g.value or 1.0)
            eqs = [float(eq1.value or 1.0), float(eq2.value or 1.0), float(eq3.value or 0.1), float(eq4.value or 1.0)]

            stoich_slot.clear()
            with stoich_slot:
                safe_html(
                    '<div class="skeleton-line" style="width:50%;"></div>'
                    '<div class="skeleton-box" style="height:48px;margin-bottom:6px;"></div>'
                    '<div class="skeleton-box" style="height:48px;"></div>'
                )

            res = await run.io_bound(_compute_stoich_data, row, target_g, eqs)
            calc_state["last_items"] = res["items"]

            in_cible.value = p_name
            in_m_theo.value = target_g
            summary_parts = []
            for it in res["items"]:
                if it["mass_g"] is not None:
                    summary_parts.append(f"{it['nom']}: {it['mass_g']:.2f} g ({it['vol_ml']:.2f} mL)")
                else:
                    summary_parts.append(f"{it['nom']} ({it['eq']:g} éq)")
            in_qtes.value = " | ".join(summary_parts)

            stoich_slot.clear()
            with stoich_slot:
                mw_p = res["mw_prod"]
                n_t = res["n_target"]
                header_info = (
                    f"M = {mw_p:.2f} g/mol · n cible = {n_t * 1000:.2f} mmol"
                    if (mw_p and n_t is not None)
                    else "Masse molaire du produit introuvable"
                )
                safe_html(f'<div class="mono-tag" style="display:inline-block;margin-bottom:10px;">{html.escape(header_info)}</div>')

                if not res["items"]:
                    safe_html('<p class="muted-small">Aucun réactif défini pour cette synthèse.</p>')
                    return

                rows_html = []
                for it in res["items"]:
                    m_txt = f"{it['mass_g']:.2f} g" if it["mass_g"] is not None else "N/A"
                    v_txt = f"{it['vol_ml']:.2f} mL" if it["vol_ml"] is not None else "—"
                    rows_html.append(
                        f'<div class="kv-item" style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:6px;">'
                        f'<div><strong style="color:var(--txt);font-size:0.86rem;">{html.escape(it["nom"])}</strong>'
                        f'<div class="muted-small">{it["eq"]:g} éq · Stock : {html.escape(it["stock_str"])}</div></div>'
                        f'<div style="text-align:right;font-family:\'JetBrains Mono\',monospace;">'
                        f'<div style="color:var(--cyan);font-weight:700;">{m_txt}</div>'
                        f'<div class="muted-small">{v_txt} (d={it["dens"]:.2f})</div></div></div>'
                    )
                safe_html("".join(rows_html))

                def deduct_all(_ev=None):
                    op_name = current_user()
                    motif_s = f"Synthèse {p_name} ({target_g:g} g)"
                    deducted = 0
                    for it in calc_state["last_items"]:
                        if it["mass_g"] and it["mass_g"] > 0:
                            if deduct_inventory_by_name(it["nom"], it["mass_g"], operator=op_name, motif=motif_s):
                                deducted += 1
                    if deducted > 0:
                        ui.notify(f"{deducted} réactif(s) déduit(s) de l'inventaire sous {op_name}.", type="positive")
                        if callable(on_data_changed):
                            on_data_changed()
                        ui.timer(0.05, update_stoich, once=True)
                    else:
                        ui.notify("Aucun réactif déductible trouvé dans l'inventaire.", type="warning")

                with ui.element("div").style("display:flex;justify-content:flex-end;margin-top:10px;"):
                    _btn("Déduire ces réactifs du stock", on_click=deduct_all)

        for ctrl in (sel_prod, in_target_g, eq1, eq2, eq3, eq4):
            ctrl.on_value_change(update_stoich)

        def select_product_from_fiche(prod_name: str):
            fresh_rows = get_all_syntheses()
            rows_by_name.clear()
            for r in fresh_rows:
                pn = clean_val(r.get("Produit final"))
                if pn:
                    rows_by_name[pn] = r
            sel_prod.options = list(rows_by_name.keys())
            sel_prod.update()
            if prod_name in rows_by_name:
                sel_prod.value = prod_name
                ui.timer(0.05, update_stoich, once=True)
            else:
                in_cible.value = prod_name
            in_op.value = current_user()

        select_bridge["fn"] = select_product_from_fiche

        chart_slot = ui.element("div").style("margin-bottom:18px;")
        history_slot = ui.element("div")

        def refresh_history():
            me = current_user()
            me_super = is_superadmin()
            in_op.value = me
            entries = get_all_labo_entries()

            is_dark = bool(app_state.get("dark", True))
            ax_txt = "#94a3b8" if is_dark else "#475569"
            ax_line = "rgba(148,163,184,0.30)" if is_dark else "rgba(15,23,42,0.22)"
            split_line = "rgba(148,163,184,0.14)" if is_dark else "rgba(15,23,42,0.09)"
            tip_bg = "rgba(15,23,23,0.94)" if is_dark else "rgba(255,255,255,0.96)"
            tip_txt = "#e6edf3" if is_dark else "#0f172a"
            line_col = "#38bdf8" if is_dark else "#0284c7"
            dot_col = "#10b981" if is_dark else "#059669"

            chart_slot.clear()
            if entries:
                chron = list(reversed(entries[:20]))
                labels = [f"{clean_val(e.get('date_essai'))[5:]} · {clean_val(e.get('produit_cible'))[:14]}" for e in chron]
                values = [float(e.get("rendement_reel") or 0.0) for e in chron]
                with chart_slot:
                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">SUIVI EXPÉRIMENTAL</div><h2>Évolution des Rendements (%)</h2>')
                        ui.echart({
                            "backgroundColor": "transparent",
                            "tooltip": {
                                "trigger": "axis",
                                "backgroundColor": tip_bg,
                                "borderColor": line_col,
                                "textStyle": {"color": tip_txt},
                            },
                            "grid": {"left": 45, "right": 20, "top": 20, "bottom": 55},
                            "xAxis": {
                                "type": "category",
                                "data": labels,
                                "axisLabel": {"color": ax_txt, "rotate": 20, "fontSize": 11},
                                "axisLine": {"lineStyle": {"color": ax_line}},
                            },
                            "yAxis": {
                                "type": "value",
                                "max": 100,
                                "axisLabel": {"color": ax_txt, "formatter": "{value} %"},
                                "splitLine": {"lineStyle": {"color": split_line}},
                            },
                            "series": [{
                                "name": "Rendement réel",
                                "type": "line",
                                "smooth": True,
                                "data": values,
                                "lineStyle": {"width": 3, "color": line_col},
                                "itemStyle": {"color": dot_col},
                                "areaStyle": {"color": "rgba(56, 189, 248, 0.14)" if is_dark else "rgba(2, 132, 199, 0.12)"},
                            }],
                        }).style("height:240px;width:100%;")

            history_slot.clear()
            with history_slot:
                with ui.element("div").classes("catalog-meta-row"):
                    safe_html(f"<span>{len(entries)} ESSAI(S) ARCHIVÉ(S) DANS LE CAHIER DE LABORATOIRE</span>")
                    if entries:
                        _btn(
                            "Export Cahier de Labo (.xls)",
                            style="padding:4px 10px;font-size:0.72rem;",
                            on_click=lambda _e: ui.download(
                                export_styled_table(
                                    [
                                        {
                                            "Date": x["date_essai"],
                                            "Opérateur": x["operateur"],
                                            "Produit cible": x["produit_cible"],
                                            "Quantités engagées": x["quantites_engagees"],
                                            "Masse théo (g)": x["masse_theorique"],
                                            "Masse obt (g)": x["masse_obtenue"],
                                            "Rendement réel (%)": x["rendement_reel"],
                                            "Statut": x["statut"],
                                            "Observations": x["observations"],
                                        }
                                        for x in entries
                                    ],
                                    ["Date", "Opérateur", "Produit cible", "Quantités engagées", "Masse théo (g)", "Masse obt (g)", "Rendement réel (%)", "Statut", "Observations"],
                                    title="Cahier de Laboratoire ChemBase",
                                ),
                                "ChemBase_Cahier_Laboratoire.xls",
                            ),
                        )

                if not entries:
                    safe_html('<div class="hud-card"><p class="muted-text">Aucun essai enregistré pour le moment. Utilisez le formulaire ci-dessus pour archiver votre première synthèse.</p></div>')
                    return

                with ui.element("div").style("display:flex;flex-direction:column;gap:10px;"):
                    for ent in entries:
                        ent_id = int(ent["id"])
                        cible_lbl = clean_val(ent.get("produit_cible")) or f"Essai #{ent_id}"
                        op_entry = clean_val(ent.get("operateur"))
                        can_delete = me_super or (op_entry.lower() == me.lower())
                        st_v = clean_val(ent.get("statut"))
                        st_cls = "stock-ok" if st_v == "Validé" else ("stock-empty" if st_v == "Échec" else "stock-low")

                        has_attachment = bool(ent.get("has_blob")) or bool(clean_val(ent.get("attachment_path")))
                        att_lbl = clean_val(ent.get("attachment_name")) or "Pièce jointe"
                        att_link = (
                            f'<a class="glass-btn" style="text-decoration:none;padding:4px 10px;font-size:0.74rem;" '
                            f'href="/api/labo/attachment/{ent_id}" target="_blank" title="{html.escape(att_lbl)}">Pièce jointe ↗</a>'
                            if has_attachment
                            else ""
                        )
                        print_link = f'<a class="glass-btn" style="text-decoration:none;padding:4px 10px;font-size:0.74rem;" href="/api/print/labo/{ent_id}" target="_blank">Imprimer / PDF</a>'
                        obs_txt = clean_val(ent.get("observations"))
                        obs_html = f'<div class="muted-small" style="margin-top:4px;color:var(--txt);">Notes : {html.escape(obs_txt)}</div>' if obs_txt else ""

                        def ask_del_entry(_e=None, i=ent_id, lbl=cible_lbl):
                            def do_del():
                                delete_labo_entry(i, actor_username=current_user())
                                ui.notify(f"Essai « {lbl} » supprimé.", type="warning")
                                refresh_history()
                                if callable(on_data_changed):
                                    on_data_changed()
                            open_confirm_delete(lbl, do_del)

                        with ui.element("div").classes("hud-card").style("padding:14px 18px;"):
                            with ui.element("div").style("display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;"):
                                with ui.element("div").style("flex:1;min-width:260px;"):
                                    safe_html(
                                        f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                                        f'<strong style="font-size:1rem;color:var(--txt);">{html.escape(cible_lbl)}</strong>'
                                        f'<span class="stock-pill {st_cls}">{html.escape(st_v or "N/A")}</span>'
                                        f'<span class="mono-tag">{html.escape(clean_val(ent.get("date_essai")))} · {html.escape(op_entry)}</span>'
                                        f'</div>'
                                        f'<div class="muted-small" style="margin-top:5px;">'
                                        f'Engagé : {html.escape(clean_val(ent.get("quantites_engagees")) or "N/A")}</div>'
                                        f'{obs_html}'
                                    )

                                with ui.element("div").style("display:flex;align-items:center;gap:8px;flex-wrap:wrap;"):
                                    safe_html(
                                        f'<div style="text-align:right;font-family:\'JetBrains Mono\',monospace;margin-right:4px;">'
                                        f'<div style="font-size:1.15rem;font-weight:700;color:var(--accent);">{float(ent.get("rendement_reel") or 0.0):.1f} %</div>'
                                        f'<div class="muted-small">{float(ent.get("masse_obtenue") or 0.0):.2f} g / {float(ent.get("masse_theorique") or 0.0):.2f} g</div>'
                                        f'</div>{print_link}{att_link}'
                                    )
                                    if can_delete:
                                        _btn(
                                            "Supprimer",
                                            classes="glass-btn glass-btn-danger",
                                            style="padding:5px 10px;font-size:0.74rem;",
                                            on_click=ask_del_entry,
                                        )

        ui.timer(0.1, update_stoich, once=True)
        refresh_history()
        return refresh_history

    return render_labo_tab, lambda p: select_bridge["fn"](p) if callable(select_bridge["fn"]) else None