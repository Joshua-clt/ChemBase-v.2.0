from collections import Counter
import html
import re
from nicegui import app, ui

from chem_data import BASE_COLS, SGH_DICT, clean_val
from database import (
    acknowledge_user_warnings,
    approve_pending_synthese,
    authenticate_user,
    create_user,
    delete_synthese_by_id,
    delete_user_account,
    dismiss_password_reset,
    get_all_labo_entries,
    get_all_syntheses,
    get_all_users,
    get_audit_logs,
    get_pending_password_resets,
    get_pending_syntheses,
    get_stock_alerts,
    get_user_by_username,
    get_zero_result_searches,
    mark_all_alerts_read,
    read_db_status,
    reject_pending_synthese,
    request_password_reset,
    resolve_password_reset,
    update_synthese_by_id,
    update_user_account,
    veto_audit_action,
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


def _extract_yield_number(val: str):
    m = re.search(r"(\d+(?:\.\d+)?)", clean_val(val).replace(",", "."))
    if not m:
        return None
    v = float(m.group(1))
    return v if 0 <= v <= 100 else None


def build_analytics_and_admin_views(app_state: dict, on_data_changed=None):
    # Modales translucides en fade pour l'édition de fiche et la gestion des comptes
    edit_fiche_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with edit_fiche_dialog:
        edit_fiche_body = ui.element("div").classes("cb-modal-card")

    user_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with user_dialog:
        user_body = ui.element("div").classes("cb-inspector-card").style("width:min(540px, 92vw) !important;")

    reset_pwd_dialog = ui.dialog().props('transition-show="fade" transition-hide="fade"')
    with reset_pwd_dialog:
        reset_pwd_body = ui.element("div").classes("cb-inspector-card").style("width:min(460px, 92vw) !important;")

    # ------------------------------------------------------------------
    # ONGLET 4 : ANALYTIQUE R&D (REGROUPE TOUS LES KPI + GRAPHIQUES)
    # ------------------------------------------------------------------
    def render_analytics_tab():
        container = ui.element("div")

        def refresh_analytics():
            st = read_db_status()
            syntheses = get_all_syntheses()
            labo_entries = get_all_labo_entries()
            zero_searches = get_zero_result_searches()

            cat_yields = [y for r in syntheses if (y := _extract_yield_number(r.get("Rendement"))) is not None]
            labo_yields = [float(e.get("rendement_reel") or 0.0) for e in labo_entries]
            avg_cat = (sum(cat_yields) / len(cat_yields)) if cat_yields else 0.0
            avg_labo = (sum(labo_yields) / len(labo_yields)) if labo_yields else 0.0

            sgh_counter = Counter()
            rea_counter = Counter()
            rx_counter = Counter()

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
                # Ligne 1 : KPI globaux de la plateforme (uniquement visibles ici)
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

                # Graphiques ligne 1 : Rendements & SGH
                with ui.element("div").classes("modal-grid").style("margin-bottom:16px;"):
                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">PERFORMANCE SYNTHÉTIQUE</div><h2>Répartition des Rendements Catalogue</h2>')
                        ui.echart({
                            "backgroundColor": "transparent",
                            "tooltip": {"trigger": "axis"},
                            "grid": {"left": 38, "right": 18, "top": 20, "bottom": 34},
                            "xAxis": {
                                "type": "category",
                                "data": list(buckets.keys()),
                                "axisLabel": {"color": "#94a3b8"},
                                "axisLine": {"lineStyle": {"color": "rgba(148,163,184,0.3)"}},
                            },
                            "yAxis": {
                                "type": "value",
                                "minInterval": 1,
                                "axisLabel": {"color": "#94a3b8"},
                                "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.14)"}},
                            },
                            "series": [{
                                "type": "bar",
                                "barWidth": "46%",
                                "data": list(buckets.values()),
                                "itemStyle": {"borderRadius": [6, 6, 0, 0], "color": "#10b981"},
                            }],
                        }).style("height:240px;width:100%;")

                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">PROFIL HSE &amp; SÉCURITÉ</div><h2>Occurrences des Dangers SGH</h2>')
                        sgh_sorted = sorted(sgh_counter.items(), key=lambda x: x[1], reverse=True)
                        if sgh_sorted:
                            ui.echart({
                                "backgroundColor": "transparent",
                                "tooltip": {"trigger": "item"},
                                "grid": {"left": 65, "right": 20, "top": 15, "bottom": 28},
                                "xAxis": {
                                    "type": "value",
                                    "minInterval": 1,
                                    "axisLabel": {"color": "#94a3b8"},
                                    "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.14)"}},
                                },
                                "yAxis": {
                                    "type": "category",
                                    "data": [f"{k}" for k, _v in reversed(sgh_sorted)],
                                    "axisLabel": {"color": "#94a3b8"},
                                },
                                "series": [{
                                    "type": "bar",
                                    "data": [v for _k, v in reversed(sgh_sorted)],
                                    "itemStyle": {"borderRadius": [0, 6, 6, 0], "color": "#f59e0b"},
                                }],
                            }).style("height:240px;width:100%;")
                        else:
                            safe_html('<p class="muted-text">Aucun pictogramme SGH renseigné dans le catalogue.</p>')

                # Graphiques ligne 2 : Top Réactifs & Recherches sans résultat
                with ui.element("div").classes("modal-grid"):
                    with ui.element("div").classes("hud-card"):
                        safe_html('<div class="section-kicker">CONSOMMATION R&amp;D</div><h2>Top 8 des Réactifs les plus utilisés</h2>')
                        top8 = rea_counter.most_common(8)
                        if top8:
                            ui.echart({
                                "backgroundColor": "transparent",
                                "tooltip": {"trigger": "axis"},
                                "grid": {"left": 145, "right": 22, "top": 10, "bottom": 26},
                                "xAxis": {
                                    "type": "value",
                                    "minInterval": 1,
                                    "axisLabel": {"color": "#94a3b8"},
                                    "splitLine": {"lineStyle": {"color": "rgba(148,163,184,0.14)"}},
                                },
                                "yAxis": {
                                    "type": "category",
                                    "data": [k[:22] for k, _v in reversed(top8)],
                                    "axisLabel": {"color": "#94a3b8", "fontSize": 11},
                                },
                                "series": [{
                                    "type": "bar",
                                    "data": [v for _k, v in reversed(top8)],
                                    "itemStyle": {"borderRadius": [0, 6, 6, 0], "color": "#38bdf8"},
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
    # ONGLET 6 : ADMINISTRATION, MODÉRATION, VETO & COMPTES
    # ------------------------------------------------------------------
    def render_admin_tab():
        admin_root = ui.element("div")
        sub_state = {"section": "moderation", "forgot_mode": False}

        def notify_all():
            refresh_admin()
            if callable(on_data_changed):
                on_data_changed()

        def open_edit_fiche_modal(row: dict, adm_name: str):
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

        def open_user_manage_modal(target_user: dict, actor_name: str):
            is_target_super = target_user["role"] == "superadmin"
            uid = int(target_user["id"])

            user_body.clear()
            with user_body:
                with ui.element("div").classes("modal-head"):
                    with ui.element("div"):
                        safe_html('<div class="section-kicker">GESTION DE COMPTE · SUPER-ADMIN</div>')
                        safe_html(f'<h2 style="margin:4px 0 0 0;font-size:1.25rem;">Compte : {html.escape(target_user["username"])}</h2>')
                    _btn("Fermer ✕", on_click=lambda _e: user_dialog.close())

                in_uname = ui.input(label="Identifiant", value=target_user["username"]).props("outlined dense").style("width:100%;margin-bottom:10px;")
                in_role = ui.select(
                    ["superadmin", "admin", "chercheur"],
                    value=target_user["role"] if target_user["role"] in ("superadmin", "admin", "chercheur") else "admin",
                    label="Rôle (promouvoir / rétrograder)",
                ).props("outlined dense").style("width:100%;margin-bottom:10px;")
                in_new_pwd = ui.input(
                    label="Nouveau mot de passe (laisser vide pour ne pas changer)",
                    password=True,
                    password_toggle_button=True,
                ).props("outlined dense").style("width:100%;margin-bottom:12px;")

                in_confirm_super = None
                if is_target_super:
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
                    conf = in_confirm_super.value if in_confirm_super is not None else ""
                    ok, msg = update_user_account(
                        target_user_id=uid,
                        new_username=in_uname.value or "",
                        new_password=in_new_pwd.value or "",
                        new_role=in_role.value or "admin",
                        confirm_super_pwd=conf or "",
                        actor_username=actor_name,
                    )
                    ui.notify(msg, type="positive" if ok else "negative")
                    if ok:
                        # Si le Super-Admin connecté modifie son propre compte, on synchronise sa session
                        if app_state.get("auth_user") and app_state["auth_user"]["id"] == uid:
                            refreshed = get_user_by_username(in_uname.value or target_user["username"])
                            app_state["auth_user"] = refreshed
                            if refreshed:
                                app_state["username"] = refreshed["username"]
                                app.storage.user["auth_username"] = refreshed["username"]
                        user_dialog.close()
                        notify_all()

                def do_delete_user(_e=None):
                    conf = in_confirm_super.value if in_confirm_super is not None else ""
                    ok, msg = delete_user_account(
                        target_user_id=uid,
                        confirm_super_pwd=conf or "",
                        actor_username=actor_name,
                    )
                    ui.notify(msg, type="warning" if ok else "negative")
                    if ok:
                        if app_state.get("auth_user") and app_state["auth_user"]["id"] == uid:
                            app_state["auth_user"] = None
                            app_state["username"] = "chercheur"
                            app.storage.user["auth_username"] = ""
                        user_dialog.close()
                        notify_all()

                with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;gap:10px;margin-top:14px;flex-wrap:wrap;"):
                    _btn("Supprimer le compte", classes="glass-btn glass-btn-danger", on_click=do_delete_user)
                    _btn("Enregistrer", classes="glass-btn glass-btn-accent", style="padding:8px 18px;", on_click=do_save_user)

            user_dialog.open()

        def open_resolve_reset_modal(req: dict, actor_name: str):
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
                    placeholder="Minimum 4 caractères",
                ).props("outlined dense").style("width:100%;margin-bottom:14px;")

                def apply_reset(_e=None):
                    ok, msg = resolve_password_reset(rid, in_tmp.value or "", actor_name)
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
            # Rafraîchit toujours les infos utilisateur depuis SQLite (avertissements, rôle à jour)
            cur_auth = app_state.get("auth_user")
            if cur_auth:
                fresh_u = get_user_by_username(cur_auth["username"])
                if not fresh_u or fresh_u["role"] not in ("admin", "superadmin"):
                    app_state["auth_user"] = None
                    app_state["username"] = "chercheur"
                    app.storage.user["auth_username"] = ""
                    cur_auth = None
                else:
                    app_state["auth_user"] = fresh_u
                    cur_auth = fresh_u

            with admin_root:
                # --------------------------------------------------------------
                # ÉCRAN DE CONNEXION + MOT DE PASSE OUBLIÉ
                # --------------------------------------------------------------
                if not cur_auth:
                    with ui.element("div").classes("hud-card").style("max-width:460px;margin:20px auto;"):
                        if not sub_state["forgot_mode"]:
                            safe_html(
                                '<div class="section-kicker">ACCÈS RESTREINT · GOUVERNANCE</div>'
                                '<h2>Connexion Administrateur</h2>'
                                '<p class="muted-text" style="margin-bottom:16px;">Identifiez-vous avec un compte Admin ou Super-Admin pour gérer la modération, les stocks critiques et la base.</p>'
                            )
                            in_user = ui.input(label="Identifiant").props("outlined dense").style("width:100%;margin-bottom:10px;")
                            in_pwd = ui.input(label="Mot de passe", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:16px;")

                            def try_login(_e=None):
                                user = authenticate_user(in_user.value or "", in_pwd.value or "")
                                if not user:
                                    ui.notify("Identifiant ou mot de passe incorrect.", type="negative")
                                    return
                                if user["role"] not in ("admin", "superadmin"):
                                    ui.notify("Ce compte (chercheur) n'a pas les droits d'administration.", type="warning")
                                    return
                                app_state["auth_user"] = user
                                app_state["username"] = user["username"]
                                app.storage.user["auth_username"] = user["username"]
                                ui.notify(f"Connecté en tant que {user['username']} ({user['role']}).", type="positive")
                                notify_all()

                            in_pwd.on("keydown.enter", try_login)
                            _btn("Se connecter", classes="glass-btn glass-btn-accent", style="width:100%;padding:10px;", on_click=try_login)

                            with ui.element("div").style("text-align:center;margin-top:14px;"):
                                _btn(
                                    "Mot de passe oublié ?",
                                    style="background:transparent;border:none;color:var(--cyan);font-size:0.80rem;",
                                    on_click=lambda _e: (sub_state.update(forgot_mode=True), refresh_admin()),
                                )
                        else:
                            safe_html(
                                '<div class="section-kicker">RÉCUPÉRATION D\'ACCÈS</div>'
                                '<h2>Mot de passe oublié</h2>'
                                '<p class="muted-text" style="margin-bottom:16px;">Indiquez votre identifiant : une demande de réinitialisation sera transmise au Super-Admin.</p>'
                            )
                            in_forgot = ui.input(label="Votre identifiant").props("outlined dense").style("width:100%;margin-bottom:14px;")

                            def send_reset(_e=None):
                                ok, msg = request_password_reset(in_forgot.value or "")
                                ui.notify(msg, type="positive" if ok else "negative")
                                if ok:
                                    sub_state["forgot_mode"] = False
                                    notify_all()

                            in_forgot.on("keydown.enter", send_reset)
                            _btn("Envoyer la demande au Super-Admin", classes="glass-btn glass-btn-accent", style="width:100%;padding:10px;", on_click=send_reset)
                            with ui.element("div").style("text-align:center;margin-top:12px;"):
                                _btn(
                                    "← Retour à la connexion",
                                    style="background:transparent;border:none;color:var(--sub-txt);font-size:0.80rem;",
                                    on_click=lambda _e: (sub_state.update(forgot_mode=False), refresh_admin()),
                                )
                    return

                # --------------------------------------------------------------
                # BANNIÈRE D'AVERTISSEMENT (SI VETO SUPER-ADMIN SUR CET ADMIN)
                # --------------------------------------------------------------
                is_super = cur_auth.get("role") == "superadmin"
                adm_name = cur_auth["username"]
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

                # Cloisonnement strict : un admin ne peut jamais ouvrir audit ni users
                if not is_super and sub_state["section"] in ("audit", "users"):
                    sub_state["section"] = "moderation"

                pending_list = get_pending_syntheses()
                unread_alerts = get_stock_alerts(unread_only=True)
                pending_resets = get_pending_password_resets() if is_super else []

                # Barre de session & sous-navigation
                with ui.element("div").classes("hud-card").style("padding:14px 18px;margin-bottom:16px;"):
                    with ui.element("div").style("display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;"):
                        safe_html(
                            f'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">'
                            f'<span class="status-dot status-ok"></span>'
                            f'<strong style="color:var(--txt);">Session : {html.escape(adm_name)}</strong>'
                            f'<span class="mono-tag">{html.escape(cur_auth["role"].upper())}</span>'
                            f'</div>'
                        )

                        def do_logout(_e=None):
                            app_state["auth_user"] = None
                            app_state["username"] = "chercheur"
                            app.storage.user["auth_username"] = ""
                            sub_state["section"] = "moderation"
                            notify_all()

                        _btn("Déconnexion", style="padding:5px 12px;", on_click=do_logout)

                    sub_tabs = [
                        ("moderation", f"Modération ({len(pending_list)})"),
                        ("alerts", f"Alertes Stock ({len(unread_alerts)})"),
                        ("catalogue", "Édition Catalogue"),
                    ]
                    if is_super:
                        sub_tabs.append(("audit", "Journal d'Audit & Veto"))
                        u_lbl = f"Comptes & Rôles ({len(pending_resets)} MDP)" if pending_resets else "Comptes & Rôles"
                        sub_tabs.append(("users", u_lbl))

                    with ui.element("div").style("display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;"):
                        for s_key, s_lbl in sub_tabs:
                            cls = "glass-btn glass-btn-accent" if sub_state["section"] == s_key else "glass-btn"
                            _btn(
                                html.escape(s_lbl),
                                classes=cls,
                                style="padding:6px 13px;font-size:0.80rem;",
                                on_click=lambda _e, k=s_key: (sub_state.update(section=k), refresh_admin()),
                            )

                sec = sub_state["section"]

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
                                        on_click=lambda _e, i=sid, p=p_name: (
                                            delete_synthese_by_id(i, adm_name),
                                            ui.notify(f"Fiche « {p} » supprimée (réversible via Audit).", type="warning"),
                                            notify_all(),
                                        ),
                                    )

                # --- SECTION 4 : JOURNAL D'AUDIT & DROIT DE VETO (SUPER-ADMIN UNIQUEMENT) ---
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

                # --- SECTION 5 : COMPTES, RÔLES & MOTS DE PASSE OUBLIÉS (SUPER-ADMIN UNIQUEMENT) ---
                elif sec == "users" and is_super:
                    users = get_all_users()

                    # Demandes de réinitialisation mot de passe
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
                            safe_html(
                                '<div class="section-kicker">SUPER-ADMIN · HIÉRARCHIE</div>'
                                '<h2>Comptes existants</h2>'
                                '<p class="muted-small" style="margin-bottom:12px;">Modifier, rétrograder ou supprimer un compte. Toute action sur un Super-Admin exige son mot de passe.</p>'
                            )
                            for u in users:
                                w_cnt = int(u.get("warnings") or 0)
                                w_tag = f'<span class="stock-pill stock-low">{w_cnt} avert.</span>' if w_cnt > 0 else ""
                                with ui.element("div").classes("kv-item").style("display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap;"):
                                    safe_html(
                                        f'<div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">'
                                        f'<strong style="color:var(--txt);">{html.escape(u["username"])}</strong>'
                                        f'<span class="mono-tag">{html.escape(u["role"].upper())}</span>{w_tag}</div>'
                                    )
                                    _btn(
                                        "Gérer / Rétrograder",
                                        style="padding:4px 11px;font-size:0.75rem;",
                                        on_click=lambda _e, usr=u: open_user_manage_modal(usr, adm_name),
                                    )

                        with ui.element("div").classes("hud-card"):
                            safe_html('<div class="section-kicker">NOUVEL ACCÈS</div><h2>Créer un compte</h2>')
                            new_u = ui.input(label="Identifiant").props("outlined dense").style("width:100%;margin-bottom:10px;")
                            new_p = ui.input(label="Mot de passe", password=True, password_toggle_button=True).props("outlined dense").style("width:100%;margin-bottom:10px;")
                            new_r = ui.select(["admin", "superadmin", "chercheur"], value="admin", label="Rôle").props("outlined dense").style("width:100%;margin-bottom:14px;")

                            def do_create(_e=None):
                                if not clean_val(new_u.value) or not clean_val(new_p.value):
                                    ui.notify("Remplissez l'identifiant et le mot de passe.", type="warning")
                                    return
                                ok = create_user(new_u.value, new_p.value, new_r.value or "admin")
                                if ok:
                                    ui.notify(f"Compte « {new_u.value} » ({new_r.value}) créé.", type="positive")
                                    refresh_admin()
                                else:
                                    ui.notify("Cet identifiant existe déjà.", type="negative")

                            _btn("Créer le compte", classes="glass-btn glass-btn-accent", on_click=do_create)

        refresh_admin()
        return refresh_admin

    return render_analytics_tab, render_admin_tab