from collections import Counter
from datetime import datetime
import html
import json
import re
from typing import Any
from nicegui import app, run, ui

from chem_data import SGH_DICT, clean_val
from database import (
    acknowledge_user_warnings,
    approve_pending_synthese,
    create_user,
    delete_synthese_by_id,
    delete_user_account,
    dismiss_password_reset,
    get_activity_logs,
    get_activity_usernames,
    get_all_labo_entries,
    get_all_syntheses,
    get_all_users,
    get_api_key,
    get_audit_logs,
    get_db_backup_bytes,
    get_github_sync_status,
    get_lab_registration_settings,
    get_pending_password_resets,
    get_pending_syntheses,
    get_stock_alerts,
    get_user_by_username,
    get_zero_result_searches,
    mark_all_alerts_read,
    read_db_status,
    reject_pending_synthese,
    resolve_password_reset,
    rotate_api_key,
    sync_db_to_github,
    update_lab_registration_settings,
    update_synthese_by_id,
    update_user_account,
    veto_audit_action,
)
from theme import safe_html

SGH_OPTIONS = [f"{code} - {lbl}" for code, (lbl, _fn) in SGH_DICT.items()]
ACTIVITY_CATEGORIES = ["Toutes", "CONNEXION", "INSCRIPTION", "STOCK", "LABO", "PROPOSITION", "CATALOGUE", "ADMIN", "COMPTE"]


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


def _extract_yield_number(val: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", clean_val(val).replace(",", "."))
    if not m:
        return None
    v = float(m.group(1))
    return v if 0 <= v <= 100 else None


def build_analytics_and_admin_views(app_state: dict[str, Any], on_data_changed=None):
    edit_fiche_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with edit_fiche_dialog:
        edit_fiche_body = ui.element("div").classes("cb-modal-card")

    user_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with user_dialog:
        user_body = ui.element("div").classes("cb-inspector-card").style("width:min(540px, 92vw) !important;")

    reset_pwd_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with reset_pwd_dialog:
        reset_pwd_body = ui.element("div").classes("cb-inspector-card").style("width:min(460px, 92vw) !important;")

    confirm_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with confirm_dialog:
        confirm_body = ui.element("div").classes("cb-confirm-card")

    def open_confirm_action(title: str, description: str, confirm_label: str, on_confirm):
        confirm_body.clear()
        with confirm_body:
            safe_html(
                '<div class="section-kicker" style="color:var(--danger);">CONFIRMATION REQUISE</div>'
                f'<h2 style="margin:6px 0 8px 0;font-size:1.2rem;">{html.escape(title)}</h2>'
                f'<p class="muted-text" style="margin-bottom:18px;">{html.escape(description)}</p>'
            )
            with ui.element("div").style("display:flex;justify-content:flex-end;gap:10px;"):
                _btn("Annuler", on_click=lambda _e: confirm_dialog.close())
                _btn(
                    html.escape(confirm_label),
                    classes="glass-btn glass-btn-danger",
                    on_click=lambda _e: (confirm_dialog.close(), on_confirm()),
                )
        confirm_dialog.open()

    # ------------------------------------------------------------------
    # ONGLET 4 : ANALYTIQUE R&D (KPI + GRAPHIQUES ADAPTATIFS CLAIR/SOMBRE)
    # ------------------------------------------------------------------
    def render_analytics_tab():
        container = ui.element("div")

        def refresh_analytics():
            st = read_db_status()
            syntheses = get_all_syntheses()
            labo_entries = get_all_labo_entries()
            zero_searches = get_zero_result_searches()

            is_dark = bool(app_state.get("dark", True))
            ax_txt = "#94a3b8" if is_dark else "#475569"
            ax_line = "rgba(148,163,184,0.30)" if is_dark else "rgba(15,23,42,0.22)"
            split_line = "rgba(148,163,184,0.14)" if is_dark else "rgba(15,23,42,0.09)"
            tip_bg = "rgba(15,23,23,0.94)" if is_dark else "rgba(255,255,255,0.96)"
            tip_txt = "#e6edf3" if is_dark else "#0f172a"
            col_green = "#10b981" if is_dark else "#059669"
            col_cyan = "#38bdf8" if is_dark else "#0284c7"
            col_warn = "#f59e0b" if is_dark else "#d97706"

            cat_yields = [y for r in syntheses if (y := _extract_yield_number(clean_val(r.get("Rendement")))) is not None]
            labo_yields = [float(e.get("rendement_reel") or 0.0) for e in labo_entries]
            avg_cat = (sum(cat_yields) / len(cat_yields)) if cat_yields else 0.0
            avg_labo = (sum(labo_yields) / len(labo_yields)) if labo_yields else 0.0

            sgh_counter: Counter[str] = Counter()
            rea_counter: Counter[str] = Counter()
            rx_counter: Counter[str] = Counter()

            for r in syntheses:
                picto_raw = clean_val(r.get("Pictogrammes danger")).upper()
                for code in SGH_DICT:
                    if code in picto_raw:
                        sgh_counter[code] += 1
                for i in range(1, 5):
                    rea = clean_val(r.get(f"Réactifs {i}"))
                    if rea:
                        rea_counter[rea] += 1
                for col in ("Réaction 1", "Réaction 2"):
                    rx = clean_val(r.get(col))
                    if rx:
                        rx_counter[rx] += 1

            top_rea_name = rea_counter.most_common(1)[0][0] if rea_counter else "—"
            top_rx_name = rx_counter.most_common(1)[0][0] if rx_counter else "—"

            buckets = {"< 50 %": 0, "50–70 %": 0, "70–85 %": 0, "> 85 %": 0}
            for y in cat_yields:
                if y < 50:
                    buckets["< 50 %"] += 1
                elif y < 70:
                    buckets["50–70 %"] += 1
                elif y <= 85:
                    buckets["70–85 %"] += 1
                else:
                    buckets["> 85 %"] += 1

            low_col = "var(--danger)" if st["low_stock"] > 0 else "var(--accent)"

            container.clear()
            with container:
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
                        <div class="kpi-value" style="color:{low_col};">{st['low_stock']}</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Essais Cahier de Labo</div>
                        <div class="kpi-value">{st['labo']}</div>
                      </div>
                    </div>
                    <div class="kpi-grid">
                      <div class="kpi-card">
                        <div class="kpi-label">Rendement moyen (Catalogue)</div>
                        <div class="kpi-value" style="color:var(--cyan);">{avg_cat:.1f} %</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Rendement moyen (Paillasse)</div>
                        <div class="kpi-value" style="color:var(--accent);">{avg_labo:.1f} %</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Réactif clé du labo</div>
                        <div class="kpi-value" style="font-size:1.05rem;line-height:1.35;">{html.escape(top_rea_name)}</div>
                      </div>
                      <div class="kpi-card">
                        <div class="kpi-label">Réaction la plus fréquente</div>
                        <div class="kpi-value" style="font-size:1.05rem;line-height:1.35;">{html.escape(top_rx_name)}</div>
                      </div>
                    </div>
                    """
                )

                with ui.element("div").classes("modal-grid").style("margin-bottom:16px;"):
                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">PERFORMANCE SYNTHÉTIQUE</div><h2>Répartition des Rendements Catalogue</h2>')
                        ui.echart({
                            "backgroundColor": "transparent",
                            "tooltip": {
                                "trigger": "axis",
                                "backgroundColor": tip_bg,
                                "borderColor": col_green,
                                "textStyle": {"color": tip_txt},
                            },
                            "grid": {"left": 38, "right": 18, "top": 20, "bottom": 34},
                            "xAxis": {
                                "type": "category",
                                "data": list(buckets.keys()),
                                "axisLabel": {"color": ax_txt},
                                "axisLine": {"lineStyle": {"color": ax_line}},
                            },
                            "yAxis": {
                                "type": "value",
                                "minInterval": 1,
                                "axisLabel": {"color": ax_txt},
                                "splitLine": {"lineStyle": {"color": split_line}},
                            },
                            "series": [{
                                "type": "bar",
                                "barWidth": "46%",
                                "data": list(buckets.values()),
                                "itemStyle": {"borderRadius": [6, 6, 0, 0], "color": col_green},
                            }],
                        }).style("height:240px;width:100%;")

                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">PROFIL HSE &amp; SÉCURITÉ</div><h2>Occurrences des Dangers SGH</h2>')
                        sgh_sorted = sorted(sgh_counter.items(), key=lambda x: x[1], reverse=True)
                        if sgh_sorted:
                            ui.echart({
                                "backgroundColor": "transparent",
                                "tooltip": {
                                    "trigger": "item",
                                    "backgroundColor": tip_bg,
                                    "borderColor": col_warn,
                                    "textStyle": {"color": tip_txt},
                                },
                                "grid": {"left": 65, "right": 20, "top": 15, "bottom": 28},
                                "xAxis": {
                                    "type": "value",
                                    "minInterval": 1,
                                    "axisLabel": {"color": ax_txt},
                                    "splitLine": {"lineStyle": {"color": split_line}},
                                },
                                "yAxis": {
                                    "type": "category",
                                    "data": [f"{k}" for k, _v in reversed(sgh_sorted)],
                                    "axisLabel": {"color": ax_txt},
                                    "axisLine": {"lineStyle": {"color": ax_line}},
                                },
                                "series": [{
                                    "type": "bar",
                                    "data": [v for _k, v in reversed(sgh_sorted)],
                                    "itemStyle": {"borderRadius": [0, 6, 6, 0], "color": col_warn},
                                }],
                            }).style("height:240px;width:100%;")
                        else:
                            safe_html('<p class="muted-text">Aucun pictogramme SGH renseigné dans le catalogue.</p>')

                with ui.element("div").classes("modal-grid"):
                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">CONSOMMATION R&amp;D</div><h2>Top 8 des Réactifs les plus utilisés</h2>')
                        top8 = rea_counter.most_common(8)
                        if top8:
                            ui.echart({
                                "backgroundColor": "transparent",
                                "tooltip": {
                                    "trigger": "axis",
                                    "backgroundColor": tip_bg,
                                    "borderColor": col_cyan,
                                    "textStyle": {"color": tip_txt},
                                },
                                "grid": {"left": 145, "right": 22, "top": 10, "bottom": 26},
                                "xAxis": {
                                    "type": "value",
                                    "minInterval": 1,
                                    "axisLabel": {"color": ax_txt},
                                    "splitLine": {"lineStyle": {"color": split_line}},
                                },
                                "yAxis": {
                                    "type": "category",
                                    "data": [k[:22] for k, _v in reversed(top8)],
                                    "axisLabel": {"color": ax_txt, "fontSize": 11},
                                    "axisLine": {"lineStyle": {"color": ax_line}},
                                },
                                "series": [{
                                    "type": "bar",
                                    "data": [v for _k, v in reversed(top8)],
                                    "itemStyle": {"borderRadius": [0, 6, 6, 0], "color": col_cyan},
                                }],
                            }).style("height:260px;width:100%;")
                        else:
                            safe_html('<p class="muted-text">Pas assez de données réactifs.</p>')

                    with ui.element("div").classes("hud-card"):
                        safe_html(
                            '<div class="section-kicker">VEILLE &amp; MANQUES CATALOGUE</div>'
                            '<h2>Recherches sans Résultat</h2>'
                            '<p class="muted-small" style="margin-bottom:12px;">Molécules cherchées dans le Catalogue mais absentes de la base (capturées automatiquement).</p>'
                        )
                        if not zero_searches:
                            safe_html('<p class="muted-text">Aucune recherche infructueuse enregistrée pour le moment.</p>')
                        else:
                            rows_html = []
                            for z in zero_searches[:12]:
                                rows_html.append(
                                    f'<div class="kv-item" style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">'
                                    f'<strong style="color:var(--txt);font-size:0.85rem;">{html.escape(clean_val(z.get("query_text")))}</strong>'
                                    f'<span class="muted-small">{html.escape(clean_val(z.get("timestamp")))}</span></div>'
                                )
                            safe_html("".join(rows_html))

        refresh_analytics()
        return refresh_analytics

    # ------------------------------------------------------------------
    # ONGLET 6 : ADMINISTRATION, MODÉRATION, ACTIVITÉ LABO, VETO, COMPTES & SYSTÈME
    # ------------------------------------------------------------------
    def render_admin_tab():
        admin_root = ui.element("div")
        sub_state: dict[str, Any] = {"section": "moderation"}
        act_filters: dict[str, str] = {"user": "Tous", "cat": "Toutes"}

        def notify_all():
            refresh_admin()
            if callable(on_data_changed):
                on_data_changed()

        def open_edit_fiche_modal(row: dict[str, Any], adm_name: str):
            sid = int(row["id"])
            raw_sgh = clean_val(row.get("Pictogrammes danger")).upper()
            init_sgh = [opt for opt in SGH_OPTIONS if opt.split(" - ")[0] in raw_sgh]

            edit_fiche_body.clear()
            with edit_fiche_body:
                with ui.element("div").classes("modal-head"):
                    with ui.element("div"):
                        safe_html('<div class="section-kicker">ÉDITION DE FICHE · TRAÇABILITÉ AUDIT</div>')
                        safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.35rem;">Modifier : {html.escape(clean_val(row.get("Produit final")))}</h2>')
                    _btn("Fermer ✕", on_click=lambda _e: edit_fiche_dialog.close())

                with ui.element("div").classes("form-grid-2"):
                    f_prod = ui.input(label="Produit final *", value=clean_val(row.get("Produit final"))).props("outlined dense")
                    f_cas = ui.input(label="Numéro CAS", value=clean_val(row.get("Numéro CAS"))).props("outlined dense")
                    f_rx1 = ui.input(label="Réaction 1 *", value=clean_val(row.get("Réaction 1"))).props("outlined dense")
                    f_rx2 = ui.input(label="Réaction 2", value=clean_val(row.get("Réaction 2"))).props("outlined dense")
                    f_rea1 = ui.input(label="Réactif 1", value=clean_val(row.get("Réactifs 1"))).props("outlined dense")
                    f_rea2 = ui.input(label="Réactif 2", value=clean_val(row.get("Réactifs 2"))).props("outlined dense")
                    f_rea3 = ui.input(label="Réactif 3 / Catalyseur", value=clean_val(row.get("Réactifs 3"))).props("outlined dense")
                    f_rea4 = ui.input(label="Réactif 4 / Solvant", value=clean_val(row.get("Réactifs 4"))).props("outlined dense")
                    f_rdt = ui.input(label="Rendement", value=clean_val(row.get("Rendement"))).props("outlined dense")
                    f_form = ui.input(label="Formule brute & masse", value=clean_val(row.get("Formule brute & masse"))).props("outlined dense")
                    f_etat = ui.input(label="État physique", value=clean_val(row.get("État physique"))).props("outlined dense")
                    f_rare = ui.input(label="Rareté & Coût", value=clean_val(row.get("Rareté & Coût"))).props("outlined dense")

                f_stock = ui.input(label="Conditions de stockage", value=clean_val(row.get("Conditions de stockage"))).props("outlined dense").style("margin-top:10px;width:100%;")
                f_sgh = ui.select(SGH_OPTIONS, multiple=True, value=init_sgh, label="Pictogrammes de danger SGH").props("outlined dense use-chips").style("margin-top:10px;width:100%;")

                with ui.element("div").classes("form-grid-2").style("margin-top:10px;"):
                    f_cond = ui.textarea(label="Conditions opératoires", value=clean_val(row.get("Conditions opératoires"))).props("outlined rows=3")
                    f_comm = ui.textarea(label="Commentaire / Notes R&D", value=clean_val(row.get("Commentaire"))).props("outlined rows=3")

                def save_edits(_e=None):
                    if not clean_val(f_prod.value) or not clean_val(f_rx1.value):
                        ui.notify("Produit final et Réaction 1 sont obligatoires.", type="warning")
                        return
                    sgh_str = ", ".join([x.split(" - ")[0] for x in (f_sgh.value or [])])
                    payload = {
                        "Produit final": f_prod.value,
                        "Réaction 1": f_rx1.value,
                        "Réaction 2": f_rx2.value,
                        "Réactifs 1": f_rea1.value,
                        "Réactifs 2": f_rea2.value,
                        "Réactifs 3": f_rea3.value,
                        "Réactifs 4": f_rea4.value,
                        "Rendement": f_rdt.value,
                        "Conditions opératoires": f_cond.value,
                        "Commentaire": f_comm.value,
                        "Numéro CAS": f_cas.value,
                        "Formule brute & masse": f_form.value,
                        "État physique": f_etat.value,
                        "Pictogrammes danger": sgh_str,
                        "Rareté & Coût": f_rare.value,
                        "Conditions de stockage": f_stock.value,
                    }
                    update_synthese_by_id(sid, payload, adm_name)
                    edit_fiche_dialog.close()
                    ui.notify(f"Fiche « {clean_val(f_prod.value)} » mise à jour (sauvegarde archivée dans l'audit).", type="positive")
                    notify_all()

                with ui.element("div").style("display:flex;justify-content:flex-end;gap:10px;margin-top:16px;"):
                    _btn("Annuler", on_click=lambda _e: edit_fiche_dialog.close())
                    _btn("Enregistrer les modifications", classes="glass-btn glass-btn-accent", on_click=save_edits)

            edit_fiche_dialog.open()

        def open_user_manage_modal(target_user: dict[str, Any], actor_name: str, actor_is_root: bool):
            is_target_super = target_user["role"] == "superadmin"
            is_target_root = bool(target_user.get("is_root", False))
            uid = int(target_user["id"])

            if is_target_root and not actor_is_root:
                ui.notify("Le compte Super-Admin fondateur est intouchable.", type="negative")
                return

            user_body.clear()
            with user_body:
                with ui.element("div").classes("modal-head"):
                    with ui.element("div"):
                        kicker = "SUPER-ADMIN FONDATEUR · PLEINS POUVOIRS" if actor_is_root else "GESTION DE COMPTE · SUPER-ADMIN"
                        safe_html(f'<div class="section-kicker">{kicker}</div>')
                        root_tag = ' <span class="root-badge">FONDATEUR</span>' if is_target_root else ""
                        safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.25rem;">Compte : {html.escape(target_user["username"])}{root_tag}</h2>')
                    _btn("Fermer ✕", on_click=lambda _e: user_dialog.close())

                in_uname = ui.input(label="Identifiant", value=target_user["username"]).props("outlined dense").style("width:100%;margin-bottom:10px;")

                role_options = ["superadmin"] if is_target_root else ["superadmin", "admin", "chercheur"]
                in_role = ui.select(
                    role_options,
                    value=target_user["role"] if target_user["role"] in role_options else "admin",
                    label="Rôle (promouvoir / rétrograder)",
                ).props("outlined dense" + (" disable" if is_target_root else "")).style("width:100%;margin-bottom:10px;")

                in_new_pwd = ui.input(
                    label="Nouveau mot de passe (laisser vide pour ne pas changer)",
                    password=True,
                    password_toggle_button=True,
                ).props("outlined dense").style("width:100%;margin-bottom:12px;")

                in_confirm_super: Any = None
                if is_target_super and not is_target_root:
                    if actor_is_root:
                        safe_html(
                            '<div class="detail-box" style="padding:10px 14px;margin-bottom:12px;">'
                            '<span class="muted-small" style="color:var(--accent);">'
                            '<strong>Privilège Fondateur actif :</strong> vous pouvez modifier, rétrograder ou supprimer ce compte Super-Admin sans saisir son mot de passe.</span></div>'
                        )
                    else:
                        safe_html(
                            '<div class="warning-banner" style="padding:10px 14px;margin-bottom:12px;">'
                            '<span style="font-size:0.82rem;color:var(--txt);">'
                            '<strong style="color:var(--danger);">Protection Super-Admin :</strong> '
                            'pour modifier, rétrograder ou supprimer ce compte Super-Admin, saisissez <strong>son mot de passe actuel</strong>.</span></div>'
                        )
                        in_confirm_super = ui.input(
                            label=f"Mot de passe actuel de {target_user['username']} *",
                            password=True,
                            password_toggle_button=True,
                        ).props("outlined dense").style("width:100%;margin-bottom:12px;")

                def do_save_user(_e=None):
                    conf = str(in_confirm_super.value or "") if in_confirm_super is not None else ""
                    ok, msg = update_user_account(
                        target_user_id=uid,
                        new_username=str(in_uname.value or ""),
                        new_password=str(in_new_pwd.value or ""),
                        new_role=str(in_role.value or "admin"),
                        confirm_super_pwd=conf,
                        actor_username=actor_name,
                        actor_is_root=actor_is_root,
                    )
                    ui.notify(msg, type="positive" if ok else "negative")
                    if ok:
                        cur_auth_u = app_state.get("auth_user")
                        if cur_auth_u and int(cur_auth_u["id"]) == uid:
                            refreshed = get_user_by_username(str(in_uname.value or target_user["username"]))
                            app_state["auth_user"] = refreshed
                            if refreshed:
                                app_state["username"] = refreshed["username"]
                                app.storage.user["auth_username"] = refreshed["username"]
                        user_dialog.close()
                        notify_all()

                def ask_delete_user(_e=None):
                    conf = str(in_confirm_super.value or "") if in_confirm_super is not None else ""

                    def really_del_user():
                        ok, msg = delete_user_account(
                            target_user_id=uid,
                            confirm_super_pwd=conf,
                            actor_username=actor_name,
                            actor_is_root=actor_is_root,
                        )
                        ui.notify(msg, type="warning" if ok else "negative")
                        if ok:
                            cur_auth_u = app_state.get("auth_user")
                            if cur_auth_u and int(cur_auth_u["id"]) == uid:
                                app_state["auth_user"] = None
                                app_state["username"] = ""
                                app.storage.user["auth_username"] = ""
                                ui.navigate.reload()
                                return
                            user_dialog.close()
                            notify_all()

                    open_confirm_action(
                        f"Supprimer le compte « {target_user['username']} » ?",
                        "Cette suppression est définitive et révoque immédiatement les accès associés.",
                        "Supprimer le compte",
                        really_del_user,
                    )

                with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap;"):
                    if not is_target_root:
                        _btn("Supprimer le compte", classes="glass-btn glass-btn-danger", on_click=ask_delete_user)
                    else:
                        safe_html('<span class="muted-small">Compte fondateur protégé contre la suppression</span>')
                    _btn("Enregistrer", classes="glass-btn glass-btn-accent", style="padding:8px 18px;", on_click=do_save_user)

            user_dialog.open()

        def open_resolve_reset_modal(req: dict[str, Any], actor_name: str):
            rid = int(req["id"])
            reset_pwd_body.clear()
            with reset_pwd_body:
                with ui.element("div").classes("modal-head"):
                    with ui.element("div"):
                        safe_html('<div class="section-kicker">RÉINITIALISATION MOT DE PASSE</div>')
                        safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.2rem;">Compte : {html.escape(req["username"])}</h2>')
                    _btn("Fermer ✕", on_click=lambda _e: reset_pwd_dialog.close())

                in_tmp = ui.input(
                    label="Nouveau mot de passe temporaire *",
                    placeholder="Minimum 6 caractères",
                ).props("outlined dense").style("width:100%;margin-bottom:14px;")

                def apply_reset(_e=None):
                    ok, msg = resolve_password_reset(rid, str(in_tmp.value or ""), actor_name)
                    ui.notify(msg, type="positive" if ok else "negative")
                    if ok:
                        reset_pwd_dialog.close()
                        notify_all()

                with ui.element("div").style("display:flex;justify-content:flex-end;gap:8px;"):
                    _btn("Annuler", on_click=lambda _e: reset_pwd_dialog.close())
                    _btn("Appliquer le nouveau mot de passe", classes="glass-btn glass-btn-accent", on_click=apply_reset)

            reset_pwd_dialog.open()

        def refresh_admin():
            admin_root.clear()
            cur_auth = app_state.get("auth_user")
            if cur_auth:
                fresh_u = get_user_by_username(str(cur_auth["username"]))
                if fresh_u:
                    app_state["auth_user"] = fresh_u
                    cur_auth = fresh_u

            if not cur_auth or cur_auth.get("role") not in ("admin", "superadmin"):
                with admin_root:
                    safe_html(
                        '<div class="hud-card"><div class="section-kicker">ACCÈS RESTREINT</div>'
                        '<h2>Espace réservé aux Administrateurs</h2>'
                        '<p class="muted-text">Votre compte actuel ne dispose pas des droits de modération ou d\'administration.</p></div>'
                    )
                return

            with admin_root:
                is_super = cur_auth.get("role") == "superadmin"
                is_root = bool(cur_auth.get("is_root", False))
                adm_name = str(cur_auth["username"])

                if int(cur_auth.get("warnings") or 0) > 0 and int(cur_auth.get("warning_acknowledged") or 1) == 0:
                    with ui.element("div").classes("warning-banner"):
                        safe_html(
                            f'<div>'
                            f'<strong style="color:var(--danger);font-size:0.95rem;">Avertissement Super-Admin reçu</strong>'
                            f'<div class="muted-small" style="color:var(--txt);margin-top:2px;">'
                            f'Une de vos décisions récentes a fait l\'objet d\'un veto par un Super-Admin (total avertissements : {cur_auth["warnings"]}).</div>'
                            f'</div>'
                        )
                        _btn(
                            "J'ai pris connaissance",
                            classes="glass-btn glass-btn-danger",
                            on_click=lambda _e: (acknowledge_user_warnings(adm_name), refresh_admin()),
                        )

                if not is_super and sub_state["section"] in ("activity", "audit", "users", "system"):
                    sub_state["section"] = "moderation"

                pending_list = get_pending_syntheses()
                unread_alerts = get_stock_alerts(unread_only=True)
                pending_resets = get_pending_password_resets() if is_super else []

                with ui.element("div").classes("hud-card").style("padding:14px 18px;margin-bottom:16px;"):
                    root_pill = '<span class="root-badge">FONDATEUR · PLEINS POUVOIRS</span>' if is_root else ""
                    safe_html(
                        f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
                        f'<span class="status-dot status-ok"></span>'
                        f'<strong style="color:var(--txt);">Gouvernance : {html.escape(adm_name)}</strong>'
                        f'<span class="mono-tag">{html.escape(str(cur_auth["role"]).upper())}</span>'
                        f'{root_pill}'
                        f'<span class="muted-small">PBKDF2-SHA256 · Routes sécurisées</span>'
                        f'</div>'
                    )

                    sub_tabs = [
                        ("moderation", f"Modération ({len(pending_list)})"),
                        ("alerts", f"Alertes Stock ({len(unread_alerts)})"),
                        ("catalogue", "Édition Catalogue"),
                    ]
                    if is_super:
                        sub_tabs.append(("activity", "Activité du Labo"))
                        sub_tabs.append(("audit", "Journal d'Audit & Veto"))
                        u_lbl = f"Comptes & Code Labo ({len(pending_resets)} MDP)" if pending_resets else "Comptes & Code Labo"
                        sub_tabs.append(("users", u_lbl))
                        sub_tabs.append(("system", "Sauvegarde, Sync & API"))

                    with ui.element("div").style("display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;"):
                        for s_key, s_lbl in sub_tabs:
                            cls = "glass-btn glass-btn-accent" if sub_state["section"] == s_key else "glass-btn"
                            _btn(
                                html.escape(s_lbl),
                                classes=cls,
                                style="padding:6px 13px;font-size:0.80rem;",
                                on_click=lambda _e, k=s_key: (sub_state.update(section=k), refresh_admin()),
                            )

                sec = str(sub_state["section"])

                # --- SECTION 1 : MODÉRATION ---
                if sec == "moderation":
                    if not pending_list:
                        safe_html('<div class="hud-card"><p class="muted-text">Aucune fiche en attente de validation. Tout est à jour.</p></div>')
                    else:
                        with ui.element("div").style("display:flex;flex-direction:column;gap:12px;"):
                            for item in pending_list:
                                pid = int(item["id"])
                                prod = clean_val(item.get("Produit final")) or "Sans nom"
                                cas = clean_val(item.get("Numéro CAS")) or "N/A"
                                rx1 = clean_val(item.get("Réaction 1"))
                                reas = [clean_val(item.get(f"Réactifs {i}")) for i in range(1, 5) if clean_val(item.get(f"Réactifs {i}"))]

                                with ui.element("div").classes("hud-card"):
                                    with ui.element("div").style("display:flex;justify-content:space-between;align-items:flex-start;gap:14px;flex-wrap:wrap;"):
                                        with ui.element("div").style("flex:1;min-width:260px;"):
                                            safe_html(
                                                f'<div class="section-kicker">PROPOSITION #{pid}</div>'
                                                f'<h2 style="margin:2px 0 6px 0;">{html.escape(prod)} <span class="mono-tag">CAS {html.escape(cas)}</span></h2>'
                                                f'<div class="mol-info-line"><strong>Réaction :</strong> {html.escape(rx1)}</div>'
                                                f'<div class="mol-info-line"><strong>Réactifs :</strong> {html.escape(", ".join(reas) or "N/A")}</div>'
                                                f'<div class="mol-info-line"><strong>Rendement :</strong> {html.escape(clean_val(item.get("Rendement")) or "N/A")} · <strong>Formule :</strong> {html.escape(clean_val(item.get("Formule brute & masse")) or "N/A")}</div>'
                                                f'<div class="mol-info-line"><strong>Conditions :</strong> {html.escape(clean_val(item.get("Conditions opératoires")) or "N/A")}</div>'
                                            )
                                        with ui.element("div").style("display:flex;gap:8px;flex-wrap:wrap;"):
                                            _btn(
                                                "Valider & Publier",
                                                classes="glass-btn glass-btn-accent",
                                                on_click=lambda _e, i=pid: (
                                                    approve_pending_synthese(i, adm_name),
                                                    ui.notify("Fiche publiée dans le catalogue !", type="positive"),
                                                    notify_all(),
                                                ),
                                            )
                                            _btn(
                                                "Rejeter",
                                                classes="glass-btn glass-btn-danger",
                                                on_click=lambda _e, i=pid: (
                                                    reject_pending_synthese(i, adm_name),
                                                    ui.notify("Proposition rejetée.", type="warning"),
                                                    notify_all(),
                                                ),
                                            )

                # --- SECTION 2 : ALERTES STOCK ---
                elif sec == "alerts":
                    alerts_all = get_stock_alerts(unread_only=False)
                    with ui.element("div").classes("hud-card"):
                        with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;flex-wrap:wrap;gap:10px;"):
                            safe_html('<div><div class="section-kicker">MONITORING INVENTAIRE</div><h2 style="margin:2px 0 0 0;">Alertes de Seuil &amp; Rupture</h2></div>')
                            if unread_alerts:
                                _btn(
                                    "Tout marquer comme lu",
                                    classes="glass-btn glass-btn-accent",
                                    on_click=lambda _e: (mark_all_alerts_read(), ui.notify("Alertes acquittées.", type="positive"), notify_all()),
                                )
                        if not alerts_all:
                            safe_html('<p class="muted-text">Aucune alerte de stock enregistrée.</p>')
                        else:
                            for al in alerts_all:
                                lvl = clean_val(al.get("alert_level"))
                                pill_cls = "stock-empty" if "RUPTURE" in lvl.upper() else "stock-low"
                                unread_tag = '<span class="mono-tag">NOUVEAU</span>' if int(al.get("is_read") or 0) == 0 else ""
                                safe_html(
                                    f'<div class="kv-item" style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;">'
                                    f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                                    f'<span class="stock-pill {pill_cls}">{html.escape(lvl)}</span>'
                                    f'<strong style="color:var(--txt);">{html.escape(clean_val(al.get("nom_substance")))}</strong>'
                                    f'{unread_tag}</div>'
                                    f'<div class="muted-small" style="font-family:\'JetBrains Mono\',monospace;">'
                                    f'{al["quantite"]:g} {html.escape(clean_val(al.get("unite")))} (seuil {al["seuil"]:g}) · {html.escape(clean_val(al.get("timestamp")))}'
                                    f'</div></div>'
                                )

                # --- SECTION 3 : ÉDITION & MAINTENANCE CATALOGUE ---
                elif sec == "catalogue":
                    all_syn = get_all_syntheses()
                    with ui.element("div").classes("hud-card"):
                        safe_html(
                            f'<div class="section-kicker">MAINTENANCE BASE</div>'
                            f'<h2>Fiches publiées ({len(all_syn)})</h2>'
                            f'<p class="muted-small" style="margin-bottom:12px;">Toute modification ou suppression est enregistrée dans l\'audit et reste réversible par un Super-Admin.</p>'
                        )
                        for r in all_syn:
                            sid = int(r["id"])
                            p_name = clean_val(r.get("Produit final"))
                            cas = clean_val(r.get("Numéro CAS")) or "N/A"

                            def ask_del_fiche(_e=None, i=sid, p=p_name):
                                def do_del():
                                    delete_synthese_by_id(i, adm_name)
                                    ui.notify(f"Fiche « {p} » supprimée (réversible via Audit).", type="warning")
                                    notify_all()
                                open_confirm_action(
                                    f"Supprimer la fiche « {p} » ?",
                                    "Elle sera retirée du Catalogue (un Super-Admin pourra toujours la restaurer depuis le Journal d'Audit).",
                                    "Supprimer la fiche",
                                    do_del,
                                )

                            with ui.element("div").classes("kv-item").style("display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:7px;flex-wrap:wrap;"):
                                safe_html(
                                    f'<div><strong style="color:var(--txt);">{html.escape(p_name)}</strong> '
                                    f'<span class="mono-tag">CAS {html.escape(cas)}</span> '
                                    f'<span class="muted-small">{html.escape(clean_val(r.get("Réaction 1")))}</span></div>'
                                )
                                with ui.element("div").style("display:flex;gap:6px;"):
                                    _btn(
                                        "Modifier",
                                        style="padding:4px 11px;font-size:0.75rem;",
                                        on_click=lambda _e, row=r: open_edit_fiche_modal(row, adm_name),
                                    )
                                    _btn(
                                        "Supprimer",
                                        classes="glass-btn glass-btn-danger",
                                        style="padding:4px 10px;font-size:0.75rem;",
                                        on_click=ask_del_fiche,
                                    )

                # --- SECTION 4 : FIL D'ACTIVITÉ UNIFIÉ « QUI FAIT QUOI » (SUPER-ADMIN) ---
                elif sec == "activity" and is_super:
                    known_users = ["Tous"] + get_activity_usernames()
                    if act_filters["user"] not in known_users:
                        act_filters["user"] = "Tous"

                    with ui.element("div").classes("hud-card"):
                        safe_html(
                            '<div class="section-kicker">SUPER-ADMIN · TRAÇABILITÉ GLOBALE</div>'
                            '<h2>Activité du Laboratoire (Qui fait quoi ?)</h2>'
                            '<p class="muted-small" style="margin-bottom:14px;">Connexions, inscriptions via Code Labo, prélèvements de stock, essais paillasse et propositions de fiches en temps réel.</p>'
                        )
                        with ui.element("div").style("display:grid;grid-template-columns:1fr 1fr auto;gap:10px;align-items:center;margin-bottom:14px;"):
                            sel_u = ui.select(known_users, value=act_filters["user"], label="Filtrer par utilisateur").props("outlined dense")
                            sel_c = ui.select(ACTIVITY_CATEGORIES, value=act_filters["cat"], label="Filtrer par catégorie").props("outlined dense")
                            _btn("Actualiser", style="height:40px;", on_click=lambda _e: refresh_admin())

                        sel_u.on_value_change(lambda e: (act_filters.update(user=str(e.value or "Tous")), refresh_admin()))
                        sel_c.on_value_change(lambda e: (act_filters.update(cat=str(e.value or "Toutes")), refresh_admin()))

                        acts = get_activity_logs(act_filters["user"], act_filters["cat"], limit=100)
                        if not acts:
                            safe_html('<p class="muted-text">Aucune activité enregistrée pour ces filtres.</p>')
                        else:
                            cat_styles = {
                                "INSCRIPTION": "stock-ok",
                                "CONNEXION": "stock-ok",
                                "STOCK": "stock-low",
                                "LABO": "stock-ok",
                                "ADMIN": "stock-empty",
                            }
                            for ac in acts:
                                cat = clean_val(ac.get("category")).upper()
                                pill_cls = cat_styles.get(cat, "stock-ok")
                                det = clean_val(ac.get("details"))
                                det_html = f'<div class="muted-small" style="margin-top:3px;">{html.escape(det)}</div>' if det else ""
                                safe_html(
                                    f'<div class="kv-item" style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:7px;flex-wrap:wrap;">'
                                    f'<div style="flex:1;min-width:240px;">'
                                    f'<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">'
                                    f'<span class="stock-pill {pill_cls}">{html.escape(cat)}</span>'
                                    f'<strong style="color:var(--txt);font-size:0.88rem;">{html.escape(clean_val(ac.get("action")))}</strong>'
                                    f'</div>{det_html}</div>'
                                    f'<div style="text-align:right;font-family:\'JetBrains Mono\',monospace;">'
                                    f'<div style="color:var(--cyan);font-size:0.80rem;font-weight:600;">{html.escape(clean_val(ac.get("username")))} '
                                    f'<span class="muted-small">({html.escape(clean_val(ac.get("role")))})</span></div>'
                                    f'<div class="muted-small">{html.escape(clean_val(ac.get("timestamp")))}</div>'
                                    f'</div></div>'
                                )

                # --- SECTION 5 : JOURNAL D'AUDIT & VETO (SUPER-ADMIN UNIQUEMENT) ---
                elif sec == "audit" and is_super:
                    logs = get_audit_logs()
                    with ui.element("div").classes("hud-card"):
                        safe_html(
                            '<div class="section-kicker">SUPER-ADMIN UNIQUEMENT · CONTRÔLE &amp; VETO</div>'
                            '<h2>Journal d\'Audit Administrateur</h2>'
                            '<p class="muted-small" style="margin-bottom:14px;">Annulez toute validation, rejet, modification ou suppression effectuée sur le catalogue, avec ou sans avertissement à l\'administrateur concerné.</p>'
                        )
                        if not logs:
                            safe_html('<p class="muted-text">Aucune action enregistrée dans le journal d\'audit.</p>')
                        else:
                            for lg in logs:
                                lid = int(lg["id"])
                                act = clean_val(lg.get("action_type")).upper()
                                is_rev = int(lg.get("reverted") or 0) == 1
                                has_payload = bool(clean_val(lg.get("payload_json")))
                                can_veto = (not is_rev) and has_payload and act in ("VALIDATION", "REJET", "SUPPRESSION", "MODIFICATION")
                                rev_badge = '<span class="stock-pill stock-low">ANNULÉE / VETO</span>' if (is_rev and act in ("VALIDATION", "REJET", "SUPPRESSION", "MODIFICATION")) else ""

                                with ui.element("div").classes("kv-item").style("margin-bottom:9px;padding:11px 14px;"):
                                    with ui.element("div").style("display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;"):
                                        with ui.element("div").style("flex:1;min-width:240px;"):
                                            safe_html(
                                                f'<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">'
                                                f'<span class="mono-tag">{html.escape(act)}</span>'
                                                f'<strong style="color:var(--txt);">{html.escape(clean_val(lg.get("product_name")))}</strong>'
                                                f'{rev_badge}</div>'
                                                f'<div class="muted-small" style="margin-top:4px;">{html.escape(clean_val(lg.get("full_details")))}</div>'
                                                f'<div class="muted-small" style="margin-top:2px;">Par <strong style="color:var(--txt);">{html.escape(clean_val(lg.get("admin_username")))}</strong> · {html.escape(clean_val(lg.get("timestamp")))}</div>'
                                            )
                                        if can_veto:
                                            def do_veto(log_id=lid, warn=False):
                                                ok, msg = veto_audit_action(log_id, adm_name, send_warning=warn)
                                                ui.notify(msg, type="positive" if ok else "negative")
                                                if ok:
                                                    notify_all()

                                            with ui.element("div").style("display:flex;gap:6px;flex-wrap:wrap;"):
                                                _btn(
                                                    "Annuler (Veto)",
                                                    style="padding:5px 11px;font-size:0.75rem;",
                                                    on_click=lambda _e, i=lid: do_veto(i, False),
                                                )
                                                if clean_val(lg.get("admin_username")).lower() != adm_name.lower():
                                                    _btn(
                                                        "Veto + Avertir",
                                                        classes="glass-btn glass-btn-danger",
                                                        style="padding:5px 11px;font-size:0.75rem;",
                                                        on_click=lambda _e, i=lid: do_veto(i, True),
                                                    )

                # --- SECTION 6 : COMPTES, HIÉRARCHIE & CODE LABORATOIRE (SUPER-ADMIN) ---
                elif sec == "users" and is_super:
                    users = get_all_users()
                    reg_cfg = get_lab_registration_settings()

                    with ui.element("div").classes("hud-card").style("margin-bottom:16px;border-left:3px solid var(--cyan);"):
                        safe_html(
                            '<div class="section-kicker">INSCRIPTION AUTONOME SÉCURISÉE (OPTION A)</div>'
                            '<h2>Code d\'Accès Laboratoire</h2>'
                            '<p class="muted-small" style="margin-bottom:12px;">Toute personne connaissant ce code peut créer son compte <strong>chercheur</strong> sans validation manuelle. Modifiez-le à tout moment ou fermez les inscriptions en 1 clic.</p>'
                        )
                        with ui.element("div").style("display:grid;grid-template-columns:1.4fr auto auto;gap:12px;align-items:center;"):
                            in_lab_code = ui.input(label="Code Laboratoire actif", value=str(reg_cfg["code"])).props("outlined dense")
                            sw_reg_open = ui.switch("Inscriptions ouvertes", value=bool(reg_cfg["open"]))

                            def save_reg_cfg(_e=None):
                                ok, msg = update_lab_registration_settings(
                                    str(in_lab_code.value or ""),
                                    bool(sw_reg_open.value),
                                    actor_username=adm_name,
                                )
                                ui.notify(msg, type="positive" if ok else "negative")
                                if ok:
                                    refresh_admin()

                            _btn("Enregistrer le code", classes="glass-btn glass-btn-accent", style="height:40px;", on_click=save_reg_cfg)

                    if pending_resets:
                        with ui.element("div").classes("hud-card").style("margin-bottom:16px;border-left:3px solid var(--warn);"):
                            safe_html(
                                '<div class="section-kicker">DEMANDES DE RÉINITIALISATION</div>'
                                f'<h2>Mots de passe oubliés ({len(pending_resets)})</h2>'
                            )
                            for req in pending_resets:
                                rid = int(req["id"])
                                with ui.element("div").classes("kv-item").style("display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:7px;flex-wrap:wrap;"):
                                    safe_html(
                                        f'<div><strong style="color:var(--txt);">{html.escape(req["username"])}</strong> '
                                        f'<span class="muted-small">· demandée le {html.escape(req["requested_at"])}</span></div>'
                                    )
                                    with ui.element("div").style("display:flex;gap:6px;"):
                                        _btn(
                                            "Définir nouveau MDP",
                                            classes="glass-btn glass-btn-accent",
                                            style="padding:5px 11px;font-size:0.75rem;",
                                            on_click=lambda _e, rq=req: open_resolve_reset_modal(rq, adm_name),
                                        )
                                        _btn(
                                            "Ignorer",
                                            style="padding:5px 10px;font-size:0.75rem;",
                                            on_click=lambda _e, i=rid: (dismiss_password_reset(i), notify_all()),
                                        )

                    with ui.element("div").classes("modal-grid"):
                        with ui.element("div").classes("hud-card"):
                            rule_hint = (
                                "En tant que Super-Admin Fondateur, vous pouvez modifier/supprimer n'importe quel compte sans mot de passe."
                                if is_root
                                else "Le Super-Admin Fondateur est intouchable. Toute action sur un autre Super-Admin exige son mot de passe."
                            )
                            safe_html(
                                '<div class="section-kicker">SUPER-ADMIN · HIÉRARCHIE</div>'
                                f'<h2>Comptes existants ({len(users)})</h2>'
                                f'<p class="muted-small" style="margin-bottom:12px;">{html.escape(rule_hint)}</p>'
                            )
                            for u in users:
                                u_is_root = bool(u.get("is_root", False))
                                w_cnt = int(u.get("warnings") or 0)
                                w_tag = f'<span class="stock-pill stock-low">{w_cnt} avert.</span>' if w_cnt > 0 else ""
                                root_tag = '<span class="root-badge">FONDATEUR</span>' if u_is_root else ""
                                with ui.element("div").classes("kv-item").style("display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;"):
                                    safe_html(
                                        f'<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">'
                                        f'<strong style="color:var(--txt);">{html.escape(u["username"])}</strong>'
                                        f'<span class="mono-tag">{html.escape(u["role"].upper())}</span>{root_tag}{w_tag}</div>'
                                    )
                                    if u_is_root and not is_root:
                                        safe_html('<span class="muted-small">Protégé</span>')
                                    else:
                                        _btn(
                                            "Gérer / Rétrograder",
                                            style="padding:4px 11px;font-size:0.75rem;",
                                            on_click=lambda _e, usr=u: open_user_manage_modal(usr, adm_name, is_root),
                                        )

                        with ui.element("div").classes("hud-card"):
                            safe_html('<div class="section-kicker">NOUVEL ACCÈS</div><h2>Créer un compte manuellement</h2>')
                            new_u = ui.input(label="Identifiant").props("outlined dense").style("width:100%;margin-bottom:10px;")
                            new_p = ui.input(label="Mot de passe (min. 6 car.)", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                            new_r = ui.select(["chercheur", "admin", "superadmin"], value="chercheur", label="Rôle").props("outlined dense").style("width:100%;margin-bottom:14px;")

                            def do_create(_e=None):
                                u_val = clean_val(new_u.value)
                                p_val = str(new_p.value or "")
                                if not u_val or len(p_val) < 6:
                                    ui.notify("Indiquez un identifiant et un mot de passe d'au moins 6 caractères.", type="warning")
                                    return
                                ok = create_user(u_val, p_val, str(new_r.value or "chercheur"), actor_username=adm_name)
                                if ok:
                                    ui.notify(f"Compte « {u_val} » ({new_r.value}) créé.", type="positive")
                                    refresh_admin()
                                else:
                                    ui.notify("Cet identifiant existe déjà.", type="negative")

                            _btn("Créer le compte", classes="glass-btn glass-btn-accent", on_click=do_create)

                # --- SECTION 7 : SAUVEGARDE SQLITE, SYNC ASYNC & CLÉ API CHEMSTUDIO ---
                elif sec == "system" and is_super:
                    gh = get_github_sync_status()
                    db_bytes = get_db_backup_bytes()
                    size_kb = len(db_bytes) / 1024.0
                    sync_dot = (
                        "status-warn" if gh.get("pending")
                        else ("status-ok" if gh["last_ok"] is True else ("status-err" if gh["last_ok"] is False else "status-warn"))
                    )
                    api_key, from_env = get_api_key()
                    copy_key_js = html.escape(f"window.cbCopyText({json.dumps(api_key)}, 'Clé API ChemStudio')", quote=True)

                    with ui.element("div").classes("modal-grid").style("margin-bottom:16px;"):
                        with ui.element("div").classes("hud-card"):
                            safe_html(
                                '<div class="section-kicker">ARCHIVE COMPLÈTE</div>'
                                '<h2>Sauvegarde Locale SQLite</h2>'
                                f'<p class="muted-text" style="margin-bottom:14px;">Téléchargez une copie instantanée de <code>chimie_db.sqlite</code> ({size_kb:.1f} Ko) contenant le catalogue, l\'inventaire, les mouvements, le Cahier de Laboratoire (pièces jointes BLOB incluses), les comptes hachés et les journaux.</p>'
                            )

                            def download_backup(_e=None):
                                raw = get_db_backup_bytes()
                                if not raw:
                                    ui.notify("Fichier chimie_db.sqlite introuvable.", type="negative")
                                    return
                                stamp = datetime.now().strftime("%Y%m%d_%H%M")
                                ui.download(raw, f"chimie_db_backup_{stamp}.sqlite")

                            _btn(
                                "Télécharger chimie_db.sqlite",
                                classes="glass-btn glass-btn-accent",
                                style="padding:10px 18px;",
                                on_click=download_backup,
                            )

                        with ui.element("div").classes("hud-card"):
                            safe_html(
                                '<div class="section-kicker">PERSISTANCE CLOUD · ASYNCHRONE (RENDER)</div>'
                                '<h2>Synchronisation GitHub</h2>'
                                f'<div class="kv-grid" style="margin-bottom:12px;">'
                                f'<div class="kv-item"><div class="kv-label">Configuration</div><div class="kv-val">{"Active (" + html.escape(str(gh["repo"])) + ")" if gh["configured"] else "Mode local"}</div></div>'
                                f'<div class="kv-item"><div class="kv-label">Dernière synchro</div><div class="kv-val">{html.escape(str(gh["last_sync"]))}</div></div>'
                                f'</div>'
                                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:14px;">'
                                f'<span class="status-dot {sync_dot}"></span>'
                                f'<span class="muted-small">{html.escape(str(gh["message"]))}</span></div>'
                            )
                            if gh["configured"]:
                                async def force_sync(_e=None):
                                    ui.notify("Synchronisation vers GitHub en cours...", type="info")
                                    await run.io_bound(sync_db_to_github)
                                    st_now = get_github_sync_status()
                                    ui.notify(str(st_now["message"]), type="positive" if st_now["last_ok"] else "negative")
                                    refresh_admin()

                                _btn("Forcer une synchronisation maintenant", on_click=force_sync)

                    with ui.element("div").classes("hud-card").style("border-left:3px solid var(--accent);"):
                        src_lbl = "Variable d'environnement Render (CHEMSTUDIO_API_KEY)" if from_env else "Générée automatiquement dans SQLite"
                        safe_html(
                            '<div class="section-kicker">PONT EXTERNE · SÉCURITÉ API (FUTUR CHEMSTUDIO)</div>'
                            '<h2>Clé d\'Accès API REST</h2>'
                            f'<p class="muted-small" style="margin-bottom:12px;">Les routes <code>/api/v1/catalog</code> et <code>/api/v1/molecule/{{cas}}</code> exigent désormais soit une session ChemBase connectée, soit l\'en-tête HTTP <code>X-API-Key</code> ci-dessous ({html.escape(src_lbl)}).</p>'
                            f'<div class="kv-item copyable-tag" style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap;" '
                            f'title="Cliquer pour copier la clé API" onclick="{copy_key_js}">'
                            f'<div><div class="kv-label">X-API-Key (clic pour copier)</div>'
                            f'<div class="kv-val" style="font-family:\'JetBrains Mono\',monospace;color:var(--cyan);">{html.escape(api_key)}</div></div>'
                            f'<span class="mono-tag">Copier ⧉</span></div>'
                        )
                        if not from_env:
                            def ask_rotate(_e=None):
                                def do_rotate():
                                    ok, msg = rotate_api_key(adm_name)
                                    ui.notify(msg, type="positive" if ok else "negative")
                                    refresh_admin()
                                open_confirm_action(
                                    "Régénérer la clé API ChemStudio ?",
                                    "L'ancienne clé sera immédiatement révoquée et devra être mise à jour dans vos modules externes.",
                                    "Régénérer la clé",
                                    do_rotate,
                                )

                            _btn("Régénérer une nouvelle clé API", classes="glass-btn glass-btn-danger", on_click=ask_rotate)

        refresh_admin()
        return refresh_admin

    return render_analytics_tab, render_admin_tab