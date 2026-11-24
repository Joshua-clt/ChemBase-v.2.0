import html
import urllib.parse

from nicegui import ui

from chem_data import clean_val, export_styled_table, get_known_density
from database import (
    adjust_inventory_quantity,
    delete_inventory_item,
    get_all_inventory,
    get_all_syntheses,
    get_stock_movements,
    quick_stock_movement,
    upsert_inventory_item,
)
from theme import safe_html

CATEGORIES = ["Produit synthétisé", "Réactif / Matière 1ère", "Solvant / Consommable"]
UNITS = ["g", "mL", "kg", "L", "pcs"]


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


def _convert_g_ml(qty: float, unite: str, densite: float) -> str:
    d = float(densite or 1.0)
    u = clean_val(unite).lower()
    if d <= 0:
        return "—"
    if u == "g":
        return f"≈ {qty / d:.1f} mL"
    if u == "ml":
        return f"≈ {qty * d:.1f} g"
    if u == "kg":
        return f"≈ {(qty * 1000.0) / d:.0f} mL"
    if u == "l":
        return f"≈ {qty * d:.2f} kg"
    return "—"


def build_stocks_view(app_state: dict, on_data_changed=None):
    edit_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with edit_dialog:
        edit_body = ui.element("div").classes("cb-inspector-card")

    history_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with history_dialog:
        history_body = ui.element("div").classes("cb-inspector-card")

    confirm_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with confirm_dialog:
        confirm_body = ui.element("div").classes("cb-confirm-card")

    focus_hook = {"set_search": None}

    def current_op() -> str:
        return app_state.get("username", "chercheur")

    def open_confirm_delete(label_name: str, on_confirm):
        confirm_body.clear()
        with confirm_body:
            safe_html(
                '<div class="section-kicker" style="color:var(--danger);">CONFIRMATION REQUISE</div>'
                f'<h2 style="margin:6px 0 8px 0;font-size:1.2rem;">Supprimer « {html.escape(label_name)} » ?</h2>'
                '<p class="muted-text" style="margin-bottom:18px;">Cette référence sera retirée définitivement de l\'inventaire physique.</p>'
            )
            with ui.element("div").style("display:flex;justify-content:flex-end;gap:10px;"):
                _btn("Annuler", on_click=lambda _e: confirm_dialog.close())
                _btn(
                    "Confirmer la suppression",
                    classes="glass-btn glass-btn-danger",
                    on_click=lambda _e: (confirm_dialog.close(), on_confirm()),
                )
        confirm_dialog.open()

    def build_label_url_for_item(item: dict) -> str:
        nom = clean_val(item.get("nom_substance"))
        syn_match = next(
            (r for r in get_all_syntheses() if clean_val(r.get("Produit final")).lower() == nom.lower()),
            {},
        )
        return (
            f"/api/label?nom={urllib.parse.quote(nom)}"
            f"&cas={urllib.parse.quote(clean_val(syn_match.get('Numéro CAS')))}"
            f"&formule={urllib.parse.quote(clean_val(syn_match.get('Formule brute & masse')))}"
            f"&pictos={urllib.parse.quote(clean_val(syn_match.get('Pictogrammes danger')))}"
            f"&stockage={urllib.parse.quote(clean_val(item.get('emplacement')) or clean_val(syn_match.get('Conditions de stockage')))}"
            f"&op={urllib.parse.quote(current_op())}"
        )

    def open_movements_modal(item: dict):
        nom = clean_val(item.get("nom_substance"))
        unit = clean_val(item.get("unite")) or "g"
        qty = float(item.get("quantite") or 0.0)
        dens = float(item.get("densite") or 1.0)
        moves = get_stock_movements(nom, limit=40)
        label_url = build_label_url_for_item(item)

        history_body.clear()
        with history_body:
            with ui.element("div").classes("modal-head"):
                with ui.element("div"):
                    safe_html('<div class="section-kicker">TRAÇABILITÉ INVENTAIRE · JOURNAL DES MOUVEMENTS</div>')
                    safe_html(
                        f'<h2 style="margin:4px 0 4px 0;font-size:1.3rem;">{html.escape(nom)}</h2>'
                        f'<div class="muted-small">Stock actuel : <strong style="color:var(--cyan);">{qty:g} {html.escape(unit)}</strong> '
                        f'({_convert_g_ml(qty, unit, dens)}) · Emplacement : {html.escape(clean_val(item.get("emplacement")) or "N/A")}</div>'
                    )
                with ui.element("div").style("display:flex;gap:8px;flex-wrap:wrap;"):
                    safe_html(f'<a class="glass-btn" style="text-decoration:none;" href="{label_url}" target="_blank">Étiquette flacon</a>')
                    _btn("Fermer ✕", on_click=lambda _e: history_dialog.close())

            if not moves:
                safe_html(
                    '<div class="detail-box"><p class="muted-text">Aucun mouvement encore enregistré pour cette substance. '
                    'Les prochains prélèvements, réapprovisionnements et déductions du calculateur apparaîtront ici.</p></div>'
                )
            else:
                rows_html = []
                for mv in moves:
                    d_val = float(mv.get("delta") or 0.0)
                    sign_cls = "stock-ok" if d_val >= 0 else "stock-empty"
                    sign_txt = f"+{d_val:g}" if d_val >= 0 else f"{d_val:g}"
                    u_mv = clean_val(mv.get("unite")) or unit
                    rows_html.append(
                        f'<div class="kv-item" style="display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:7px;flex-wrap:wrap;">'
                        f'<div style="display:flex;align-items:center;gap:9px;flex-wrap:wrap;">'
                        f'<span class="stock-pill {sign_cls}">{sign_txt} {html.escape(u_mv)}</span>'
                        f'<div><strong style="color:var(--txt);font-size:0.86rem;">{html.escape(clean_val(mv.get("motif")))}</strong>'
                        f'<div class="muted-small">Par {html.escape(clean_val(mv.get("operateur")))} · {html.escape(clean_val(mv.get("timestamp")))}</div></div>'
                        f'</div>'
                        f'<div style="font-family:\'JetBrains Mono\',monospace;font-size:0.84rem;color:var(--cyan);">'
                        f'Solde : {float(mv.get("quantite_apres") or 0.0):g} {html.escape(u_mv)}</div></div>'
                    )
                safe_html("".join(rows_html))

        history_dialog.open()

    def render_stocks_tab():
        filters = {"q": "", "cat": "Toutes", "low_only": False}

        all_init = get_all_inventory()
        sub_names = [it["nom_substance"] for it in all_init]

        with ui.element("div").classes("hud-card").style("margin-bottom:16px;padding:16px 20px;"):
            safe_html(
                '<div class="section-kicker">MOUVEMENT RAPIDE DE PAILLASSE</div>'
                '<div style="display:flex;justify-content:space-between;align-items:baseline;flex-wrap:wrap;gap:8px;margin-bottom:12px;">'
                '<h2 style="margin:2px 0 0 0;">Prélever ou Réapprovisionner en un geste</h2>'
                '<span class="muted-small">Conversion automatique g ↔ mL et journalisation par substance</span></div>'
            )
            with ui.element("div").style("display:grid;grid-template-columns:2fr 0.9fr 0.7fr auto auto;gap:10px;align-items:center;"):
                qm_sub = ui.select(
                    sub_names,
                    value=sub_names[0] if sub_names else None,
                    label="Substance",
                    with_input=True,
                ).props("outlined dense")
                qm_amt = ui.number(label="Quantité", value=10.0, min=0.01, step=5.0).props("outlined dense")
                qm_unit = ui.select(["g", "mL"], value="g", label="Unité").props("outlined dense")
                btn_take = _btn("− Retirer", classes="glass-btn glass-btn-danger", style="height:40px;padding:0 16px;")
                btn_put = _btn("+ Ajouter", classes="glass-btn glass-btn-accent", style="height:40px;padding:0 16px;")

            qm_info_slot = ui.element("div").style("margin-top:8px;")

        with ui.element("div").style("display:grid;grid-template-columns:2fr 1.2fr auto auto auto;gap:10px;align-items:center;margin-bottom:12px;"):
            q_in = ui.input(placeholder="Filtrer le tableau par substance ou emplacement...").props("outlined dense clearable")
            cat_sel = ui.select(["Toutes"] + CATEGORIES, value="Toutes", label="Catégorie").props("outlined dense")
            low_chk = ui.checkbox("Alertes uniquement")
            btn_add = _btn("+ Nouvelle référence", classes="glass-btn glass-btn-accent", style="height:40px;")
            btn_order = _btn("Bon de commande (.xls)", style="height:40px;")

        summary_slot = ui.element("div").classes("catalog-meta-row")
        table_slot = ui.element("div")

        def update_quick_preview(_e=None):
            items_map = {it["nom_substance"]: it for it in get_all_inventory()}
            sel = qm_sub.value
            it = items_map.get(sel)
            qm_info_slot.clear()
            if not it:
                return
            qty = float(it.get("quantite") or 0.0)
            unit = clean_val(it.get("unite")) or "g"
            dens = float(it.get("densite") or 1.0)
            seuil = float(it.get("seuil_alerte") or 0.0)
            equiv = _convert_g_ml(qty, unit, dens)
            with qm_info_slot:
                safe_html(
                    f'<span class="muted-small">Stock actuel : '
                    f'<strong style="color:var(--txt);font-family:\'JetBrains Mono\',monospace;">{qty:g} {html.escape(unit)}</strong> '
                    f'<span style="color:var(--cyan);">({html.escape(equiv)})</span> · '
                    f'Densité : {dens:.2f} g/mL · Seuil critique : {seuil:g} {html.escape(unit)} · '
                    f'Emplacement : {html.escape(clean_val(it.get("emplacement")) or "N/A")}</span>'
                )

        def run_quick_move(is_add: bool):
            sel = qm_sub.value
            amt = float(qm_amt.value or 0.0)
            if not sel or amt <= 0:
                ui.notify("Choisissez une substance et une quantité positive.", type="warning")
                return
            ok, msg = quick_stock_movement(sel, amt, qm_unit.value or "g", is_addition=is_add, operator=current_op())
            ui.notify(msg, type="positive" if ok else "negative")
            notify_refresh()

        btn_take.on("click", lambda _e: run_quick_move(False))
        btn_put.on("click", lambda _e: run_quick_move(True))
        qm_sub.on_value_change(update_quick_preview)

        def notify_refresh():
            refresh_table()
            if callable(on_data_changed):
                on_data_changed()

        def open_edit_modal(item=None):
            is_edit = item is not None
            edit_body.clear()
            with edit_body:
                with ui.element("div").classes("modal-head"):
                    with ui.element("div"):
                        safe_html('<div class="section-kicker">GESTION DE STOCK &amp; DENSITÉ</div>')
                        title_txt = f"Modifier : {html.escape(item['nom_substance'])}" if is_edit else "Ajouter une référence à l'inventaire"
                        safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.3rem;">{title_txt}</h2>')
                    _btn("Fermer ✕", on_click=lambda _e: edit_dialog.close())

                with ui.element("div").classes("form-grid-2"):
                    in_nom = ui.input(label="Nom de la substance *", value=item["nom_substance"] if is_edit else "").props("outlined dense")
                    in_cat = ui.select(CATEGORIES, value=item["categorie"] if is_edit and item["categorie"] in CATEGORIES else CATEGORIES[1], label="Catégorie").props("outlined dense")
                    in_qty = ui.number(label="Quantité en stock", value=float(item["quantite"]) if is_edit else 100.0, min=0, step=5).props("outlined dense")
                    in_unit = ui.select(UNITS, value=item["unite"] if is_edit and item["unite"] in UNITS else "g", label="Unité").props("outlined dense")
                    in_seuil = ui.number(label="Seuil d'alerte critique", value=float(item["seuil_alerte"]) if is_edit else 25.0, min=0, step=5).props("outlined dense")
                    in_dens = ui.number(label="Densité (g/mL)", value=float(item["densite"] or 1.0) if is_edit else 1.0, min=0.1, max=15.0, step=0.01, format="%.2f").props("outlined dense")

                in_loc = ui.input(label="Emplacement / Armoire", value=item["emplacement"] if is_edit else "Magasin réactifs").props("outlined dense").style("margin-top:12px;width:100%;")

                conv_preview = ui.element("div").style("margin-top:12px;")

                def update_conv():
                    q_v = float(in_qty.value or 0.0)
                    u_v = in_unit.value or "g"
                    d_v = float(in_dens.value or 1.0)
                    equiv = _convert_g_ml(q_v, u_v, d_v)
                    conv_preview.clear()
                    with conv_preview:
                        safe_html(
                            f'<div class="detail-box" style="margin-bottom:0;padding:10px 14px;">'
                            f'<span class="muted-small">Équivalence masse / volume : </span>'
                            f'<strong style="color:var(--cyan);font-family:\'JetBrains Mono\',monospace;">{q_v:g} {html.escape(u_v)} {html.escape(equiv)}</strong>'
                            f' <span class="muted-small">(d = {d_v:.2f} g/mL)</span></div>'
                        )

                in_qty.on_value_change(lambda _e: update_conv())
                in_unit.on_value_change(lambda _e: update_conv())
                in_dens.on_value_change(lambda _e: update_conv())
                if not is_edit:
                    def auto_dens(_e):
                        d_known = get_known_density(in_nom.value, 0.0)
                        if d_known > 0:
                            in_dens.value = d_known
                    in_nom.on("blur", auto_dens)
                update_conv()

                def on_save(_e=None):
                    nom_v = clean_val(in_nom.value)
                    if not nom_v:
                        ui.notify("Le nom de la substance est requis.", type="warning")
                        return
                    upsert_inventory_item(
                        nom=nom_v,
                        categorie=in_cat.value or CATEGORIES[1],
                        quantite=float(in_qty.value or 0.0),
                        unite=in_unit.value or "g",
                        seuil=float(in_seuil.value or 0.0),
                        emplacement=in_loc.value or "Armoire",
                        densite=float(in_dens.value or 1.0),
                        item_id=item["id"] if item is not None else None,
                        operator=current_op(),
                    )
                    edit_dialog.close()
                    ui.notify(f"Inventaire mis à jour pour « {nom_v} ».", type="positive")
                    notify_refresh()

                def ask_delete(_e=None):
                    if item is None:
                        return
                    target_id = item["id"]
                    target_nom = item["nom_substance"]

                    def really_delete():
                        delete_inventory_item(target_id, operator=current_op())
                        edit_dialog.close()
                        ui.notify(f"Référence « {target_nom} » supprimée.", type="warning")
                        notify_refresh()
                    open_confirm_delete(target_nom, really_delete)

                with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;margin-top:18px;gap:10px;"):
                    if is_edit:
                        _btn("Supprimer", classes="glass-btn glass-btn-danger", on_click=ask_delete)
                    else:
                        ui.element("div")
                    _btn("Enregistrer", classes="glass-btn glass-btn-accent", style="padding:9px 20px;", on_click=on_save)

            edit_dialog.open()

        def get_filtered():
            items = get_all_inventory()
            q = clean_val(filters["q"]).lower()
            out = []
            for it in items:
                qty = float(it.get("quantite") or 0.0)
                seuil = float(it.get("seuil_alerte") or 0.0)
                if filters["low_only"] and qty > seuil:
                    continue
                if filters["cat"] != "Toutes" and clean_val(it.get("categorie")) != filters["cat"]:
                    continue
                if q:
                    blob = f"{clean_val(it.get('nom_substance'))} {clean_val(it.get('emplacement'))} {clean_val(it.get('categorie'))}".lower()
                    if q not in blob:
                        continue
                out.append(it)
            return out

        def export_purchase_order(_e=None):
            all_items = get_all_inventory()
            low_items = [it for it in all_items if float(it.get("quantite") or 0.0) <= float(it.get("seuil_alerte") or 0.0)]
            if not low_items:
                ui.notify("Aucune substance en seuil critique : tout le stock est au vert !", type="positive")
                return
            rows_export = []
            for it in low_items:
                qty = float(it.get("quantite") or 0.0)
                seuil = float(it.get("seuil_alerte") or 0.0)
                a_commander = max(round(seuil * 2.5 - qty, 1), 50.0)
                rows_export.append({
                    "Substance": it["nom_substance"],
                    "Catégorie": it["categorie"],
                    "Stock actuel": f"{qty:g} {it['unite']}",
                    "Seuil alerte": f"{seuil:g} {it['unite']}",
                    "Qté recommandée à commander": f"{a_commander:g} {it['unite']}",
                    "Emplacement": it["emplacement"],
                })
            cols = ["Substance", "Catégorie", "Stock actuel", "Seuil alerte", "Qté recommandée à commander", "Emplacement"]
            ui.download(
                export_styled_table(rows_export, cols, title="Bon de Commande Laboratoire"),
                "ChemBase_Bon_De_Commande.xls",
            )

        def refresh_table():
            all_items = get_all_inventory()
            qm_sub.options = [it["nom_substance"] for it in all_items]
            qm_sub.update()
            update_quick_preview()

            items = get_filtered()
            low_count = sum(1 for it in items if float(it.get("quantite") or 0.0) <= float(it.get("seuil_alerte") or 0.0))

            summary_slot.clear()
            with summary_slot:
                safe_html(f"<span>{len(items)} RÉFÉRENCE(S) · {low_count} EN ALERTE CRITIQUE / RUPTURE · CLIC SUR « HISTORIQUE » POUR LA TRAÇABILITÉ</span>")
                _btn(
                    "Export Inventaire complet (.xls)",
                    style="padding:4px 10px;font-size:0.72rem;",
                    on_click=lambda _e: ui.download(
                        export_styled_table(
                            [
                                {
                                    "Substance": x["nom_substance"],
                                    "Catégorie": x["categorie"],
                                    "Quantité": x["quantite"],
                                    "Unité": x["unite"],
                                    "Densité (g/mL)": x["densite"],
                                    "Seuil alerte": x["seuil_alerte"],
                                    "Emplacement": x["emplacement"],
                                    "Dernière MAJ": x["derniere_maj"],
                                }
                                for x in items
                            ],
                            ["Substance", "Catégorie", "Quantité", "Unité", "Densité (g/mL)", "Seuil alerte", "Emplacement", "Dernière MAJ"],
                            title="Inventaire Complet ChemBase",
                        ),
                        "ChemBase_Inventaire.xls",
                    ),
                )

            table_slot.clear()
            with table_slot:
                if not items:
                    safe_html('<div class="hud-card"><p class="muted-text">Aucune référence ne correspond à ce filtre.</p></div>')
                    return

                with ui.element("div").classes("stock-table-wrap"):
                    safe_html(
                        '<div class="stock-table-head">'
                        '<div>Substance &amp; Catégorie</div>'
                        '<div>Quantité &amp; Équiv.</div>'
                        '<div>Niveau &amp; Seuil</div>'
                        '<div>Emplacement</div>'
                        '<div style="text-align:right;">Actions</div>'
                        '</div>'
                    )
                    for it in items:
                        it_id = int(it["id"])
                        qty = float(it.get("quantite") or 0.0)
                        seuil = float(it.get("seuil_alerte") or 0.0)
                        unit = clean_val(it.get("unite")) or "g"
                        dens = float(it.get("densite") or 1.0)
                        equiv = _convert_g_ml(qty, unit, dens)

                        ref_max = max(seuil * 3.0, qty, 1.0)
                        pct = min(100.0, max(4.0 if qty > 0 else 0.0, (qty / ref_max) * 100.0))

                        if qty <= 0:
                            st_badge = '<span class="stock-pill stock-empty">RUPTURE</span>'
                            gauge_cls = "gauge-fill-empty"
                        elif qty <= seuil:
                            st_badge = '<span class="stock-pill stock-low">CRITIQUE</span>'
                            gauge_cls = "gauge-fill-low"
                        else:
                            st_badge = '<span class="stock-pill stock-ok">OK</span>'
                            gauge_cls = "gauge-fill-ok"

                        step = 10.0 if seuil >= 20 else 5.0

                        with ui.element("div").classes("stock-table-row"):
                            safe_html(
                                f'<div>'
                                f'<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">'
                                f'<strong style="font-size:0.93rem;color:var(--txt);">{html.escape(it["nom_substance"])}</strong>{st_badge}</div>'
                                f'<div class="muted-small" style="margin-top:2px;">{html.escape(clean_val(it.get("categorie")))} · d={dens:.2f}</div>'
                                f'</div>'
                            )
                            safe_html(
                                f'<div style="font-family:\'JetBrains Mono\',monospace;">'
                                f'<div style="font-size:0.95rem;font-weight:700;color:var(--txt);">{qty:g} {html.escape(unit)}</div>'
                                f'<div class="muted-small" style="color:var(--cyan);">{html.escape(equiv)}</div>'
                                f'</div>'
                            )
                            safe_html(
                                f'<div>'
                                f'<div class="muted-small" style="display:flex;justify-content:space-between;">'
                                f'<span>Seuil : {seuil:g} {html.escape(unit)}</span><span>{pct:.0f}%</span></div>'
                                f'<div class="gauge-track"><div class="{gauge_cls}" style="width:{pct:.1f}%;"></div></div>'
                                f'</div>'
                            )
                            safe_html(f'<div class="muted-small" style="color:var(--txt);">{html.escape(clean_val(it.get("emplacement")) or "N/A")}</div>')

                            with ui.element("div").style("display:flex;align-items:center;justify-content:flex-end;gap:5px;flex-wrap:wrap;"):
                                _btn(
                                    f"-{step:g}",
                                    style="padding:4px 8px;font-size:0.74rem;font-family:'JetBrains Mono',monospace;",
                                    on_click=lambda _e, i=it_id, d=-step: (adjust_inventory_quantity(i, d, operator=current_op()), notify_refresh()),
                                )
                                _btn(
                                    f"+{step:g}",
                                    style="padding:4px 8px;font-size:0.74rem;font-family:'JetBrains Mono',monospace;",
                                    on_click=lambda _e, i=it_id, d=step: (adjust_inventory_quantity(i, d, operator=current_op()), notify_refresh()),
                                )
                                _btn(
                                    "Historique",
                                    style="padding:4px 9px;font-size:0.74rem;",
                                    on_click=lambda _e, row=it: open_movements_modal(row),
                                )
                                _btn(
                                    "Éditer",
                                    style="padding:4px 9px;font-size:0.74rem;",
                                    on_click=lambda _e, row=it: open_edit_modal(row),
                                )

        def set_search(term: str):
            q_in.value = term
            filters["q"] = term
            refresh_table()

        
        q_in.on_value_change(lambda e: (filters.update(q=e.value or ""), refresh_table()))
        cat_sel.on_value_change(lambda e: (filters.update(cat=e.value or "Toutes"), refresh_table()))
        low_chk.on_value_change(lambda e: (filters.update(low_only=bool(e.value)), refresh_table()))
        btn_add.on("click", lambda _e: open_edit_modal(None))
        btn_order.on("click", export_purchase_order)

        refresh_table()
        return refresh_table

    return render_stocks_tab, lambda term: focus_hook["set_search"](term) if callable(focus_hook["set_search"]) else None