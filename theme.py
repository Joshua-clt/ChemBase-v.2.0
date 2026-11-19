import inspect
from nicegui import ui


def safe_html(content: str):
    """Compatibilité automatique entre NiceGUI 2.x et 3.x."""
    if "sanitize" in inspect.signature(ui.html).parameters:
        return ui.html(content, sanitize=False)
    return ui.html(content)


THEME_HEAD_HTML = """
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet" />

<style>
:root, html[data-theme="dark"] {
  --bg: #080d0d;
  --card-solid: #0f1717;
  --card-glass: rgba(14, 23, 23, 0.78);
  --modal-bg: rgba(11, 18, 19, 0.94);
  --sub-card: rgba(20, 32, 33, 0.72);
  --txt: #e6edf3;
  --sub-txt: #94a3b8;
  --border: rgba(56, 189, 248, 0.20);
  --border-solid: #1d2d2d;
  --accent: #10b981;
  --accent-soft: rgba(16, 185, 129, 0.14);
  --cyan: #38bdf8;
  --cyan-soft: rgba(56, 189, 248, 0.13);
  --warn: #f59e0b;
  --danger: #fb7185;
  --dot-color: rgba(56, 189, 248, 0.17);
  --nav-bg: rgba(11, 19, 20, 0.62);
  --nav-border: rgba(255, 255, 255, 0.10);
  --pill-bg: linear-gradient(135deg, rgba(56, 189, 248, 0.24), rgba(16, 185, 129, 0.22));
  --pill-border: rgba(255, 255, 255, 0.26);
  --pill-shadow: 0 8px 24px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.36), inset 0 -1px 0 rgba(56, 189, 248, 0.22);
  --btn-bg: rgba(18, 29, 29, 0.78);
  --btn-border: rgba(56, 189, 248, 0.22);
  color-scheme: dark;
}

html[data-theme="light"] {
  --bg: #f2f6f5;
  --card-solid: #ffffff;
  --card-glass: rgba(255, 255, 255, 0.84);
  --modal-bg: rgba(248, 251, 250, 0.96);
  --sub-card: rgba(241, 246, 245, 0.85);
  --txt: #0f172a;
  --sub-txt: #475569;
  --border: rgba(2, 132, 199, 0.19);
  --border-solid: #cfe0dc;
  --accent: #059669;
  --accent-soft: rgba(5, 150, 105, 0.11);
  --cyan: #0284c7;
  --cyan-soft: rgba(2, 132, 199, 0.11);
  --warn: #d97706;
  --danger: #e11d48;
  --dot-color: rgba(15, 23, 42, 0.14);
  --nav-bg: rgba(255, 255, 255, 0.58);
  --nav-border: rgba(15, 23, 42, 0.10);
  --pill-bg: linear-gradient(135deg, rgba(255, 255, 255, 0.90), rgba(224, 247, 250, 0.82));
  --pill-border: rgba(2, 132, 199, 0.28);
  --pill-shadow: 0 6px 20px rgba(2, 132, 199, 0.14), inset 0 1px 0 rgba(255, 255, 255, 0.95), inset 0 -1px 0 rgba(5, 150, 105, 0.16);
  --btn-bg: rgba(255, 255, 255, 0.85);
  --btn-border: rgba(15, 23, 42, 0.14);
  color-scheme: light;
}

/* Base & Grille de points */
html, body {
  margin: 0;
  padding: 0;
  min-height: 100vh;
  background-color: var(--bg) !important;
  background-image:
    radial-gradient(circle at 12% 0%, var(--cyan-soft) 0%, transparent 42%),
    radial-gradient(circle at 88% 4%, var(--accent-soft) 0%, transparent 40%),
    radial-gradient(var(--dot-color) 1.45px, transparent 1.45px) !important;
  background-size: 100% 100%, 100% 100%, 24px 24px !important;
  background-attachment: fixed !important;
  color: var(--txt) !important;
  font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
  transition: background-color 0.25s ease, color 0.25s ease;
}

.q-page, .q-layout, .nicegui-content {
  background: transparent !important;
  padding: 0 !important;
  margin: 0 !important;
  max-width: 100% !important;
}

/* Scrollbar fine assortie */
::-webkit-scrollbar { width: 8px; height: 8px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-solid); border-radius: 99px; }
::-webkit-scrollbar-thumb:hover { background: var(--cyan); }

/* Harmonisation des champs Quasar (focus cyan, verre dépoli) */
.q-field--outlined .q-field__control {
  background: var(--card-glass) !important;
  backdrop-filter: blur(10px);
  border-radius: 10px !important;
}
.q-field--outlined .q-field__control:before {
  border-color: var(--border) !important;
}
.q-field--outlined.q-field--highlighted .q-field__control:after {
  border-color: var(--cyan) !important;
  border-width: 1.5px !important;
}
.q-field__label, .q-field__native, .q-field__input, .q-select__dropdown-icon {
  color: var(--txt) !important;
}
.q-menu {
  background: var(--card-solid) !important;
  border: 1px solid var(--border) !important;
  color: var(--txt) !important;
}

#mol-canvas {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  pointer-events: none;
  z-index: 0;
}

.app-shell {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 1400px;
  margin: 0 auto;
  padding: 20px 28px 34px 28px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* En-tête */
.top-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.brand-group { display: flex; align-items: center; gap: 18px; }
.brand-text h1 {
  margin: 2px 0 0 0;
  font-size: 2.15rem;
  font-weight: 800;
  letter-spacing: -0.025em;
  color: var(--txt);
  display: flex;
  align-items: center;
  gap: 10px;
  line-height: 1.1;
}
.version-pill {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--cyan);
  background: var(--cyan-soft);
  border: 1px solid var(--border);
  padding: 3px 8px;
  border-radius: 999px;
  letter-spacing: 0.04em;
}
.section-kicker {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.70rem;
  text-transform: uppercase;
  letter-spacing: 0.11em;
  color: var(--cyan);
  font-weight: 600;
}

/* Logo SVG */
.cb-logo-wrap {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  user-select: none;
  transition: transform 0.35s cubic-bezier(0.22, 1, 0.36, 1);
}
.cb-logo-wrap svg {
  width: 118px;
  height: 118px;
  overflow: visible;
  filter: drop-shadow(0 0 2px var(--cyan-soft));
  transition: filter 0.35s ease;
}
.cb-logo-wrap:hover { transform: scale(1.018); }
.cb-logo-wrap:hover svg { filter: brightness(1.10) drop-shadow(0 0 6px var(--cyan-soft)); }
.cb-logo-clickable { cursor: pointer; }

.header-actions { display: flex; align-items: center; gap: 10px; }
.status-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 13px;
  border-radius: 999px;
  background: var(--card-glass);
  backdrop-filter: blur(12px);
  border: 1px solid var(--border);
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.74rem;
  color: var(--sub-txt);
}
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-ok { background: #10b981; box-shadow: 0 0 8px rgba(16, 185, 129, 0.75); }
.status-warn { background: #d97706; box-shadow: 0 0 8px rgba(217, 119, 6, 0.75); }
.status-err { background: #e11d48; box-shadow: 0 0 8px rgba(225, 29, 72, 0.75); }

.glass-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: var(--btn-bg);
  backdrop-filter: blur(12px);
  border: 1px solid var(--btn-border);
  color: var(--txt);
  border-radius: 10px;
  padding: 8px 14px;
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 0.82rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, color 0.2s ease, transform 0.15s ease;
}
.glass-btn:hover {
  border-color: var(--cyan);
  color: var(--cyan);
  box-shadow: 0 0 14px var(--cyan-soft);
}
.glass-btn-accent {
  background: linear-gradient(135deg, var(--accent), var(--cyan));
  color: #ffffff !important;
  border-color: transparent;
}
.glass-btn-accent:hover {
  filter: brightness(1.08);
  color: #ffffff !important;
  box-shadow: 0 0 18px var(--accent-soft);
}
.icon-btn { width: 40px; height: 40px; padding: 0; }
.icon-btn svg { width: 19px; height: 19px; }

/* Barre Liquid Glass */
.lg-nav {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px;
  border-radius: 16px;
  background: var(--nav-bg);
  backdrop-filter: blur(20px) saturate(165%);
  -webkit-backdrop-filter: blur(20px) saturate(165%);
  border: 1px solid var(--nav-border);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12), inset 0 1px 0 rgba(255, 255, 255, 0.12);
  overflow-x: auto;
  scrollbar-width: none;
}
.lg-nav::-webkit-scrollbar { display: none; }
.lg-pill {
  position: absolute;
  top: 5px;
  left: 5px;
  height: calc(100% - 10px);
  width: 0;
  border-radius: 11px;
  background: var(--pill-bg);
  backdrop-filter: blur(18px) saturate(190%);
  -webkit-backdrop-filter: blur(18px) saturate(190%);
  border: 1px solid var(--pill-border);
  box-shadow: var(--pill-shadow);
  pointer-events: none;
  z-index: 1;
  opacity: 0;
  transition: transform 0.44s cubic-bezier(0.22, 1.24, 0.36, 1), width 0.44s cubic-bezier(0.22, 1.24, 0.36, 1), opacity 0.22s ease;
}
.lg-pill::after {
  content: "";
  position: absolute;
  inset: 1px 10% auto 10%;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.72), transparent);
  border-radius: 99px;
}
.lg-tab {
  position: relative;
  z-index: 2;
  flex: 1 1 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 10px 16px;
  border: none;
  border-radius: 11px;
  background: transparent;
  color: var(--sub-txt);
  font-family: 'Plus Jakarta Sans', sans-serif;
  font-size: 0.85rem;
  font-weight: 600;
  white-space: nowrap;
  cursor: pointer;
  transition: color 0.22s ease;
}
.lg-tab:hover, .lg-tab.active { color: var(--txt); }
.tab-badge {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.68rem;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 999px;
  background: rgba(225, 29, 72, 0.16);
  color: #fb7185;
  border: 1px solid rgba(225, 29, 72, 0.38);
}
html[data-theme="light"] .tab-badge { color: #be123c; background: rgba(225, 29, 72, 0.10); }

.hud-divider {
  height: 1px;
  background: linear-gradient(90deg, var(--cyan), var(--accent), transparent);
  opacity: 0.45;
  margin: 16px 0 22px 0;
}

.main-content { flex: 1; }
.tab-panel { display: none; }
.tab-panel.active { display: block; animation: panelFadeIn 0.24s ease-out; }
@keyframes panelFadeIn {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Tuiles KPI */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}
.kpi-card {
  background: var(--card-glass);
  backdrop-filter: blur(12px) saturate(140%);
  border: 1px solid var(--border);
  border-top: 2px solid var(--cyan);
  border-radius: 12px;
  padding: 15px 18px;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.08);
  transition: transform 0.18s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}
.kpi-card:hover { transform: translateY(-2px); border-color: var(--cyan); box-shadow: 0 8px 24px var(--cyan-soft); }
.kpi-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.70rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--sub-txt);
  margin-bottom: 5px;
}
.kpi-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.75rem;
  font-weight: 600;
  color: var(--txt);
}

/* Cartes HUD génériques */
.hud-card {
  position: relative;
  background: var(--card-glass);
  backdrop-filter: blur(12px) saturate(140%);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 22px 24px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
  overflow: hidden;
}
.hud-card::before {
  content: "";
  position: absolute;
  top: 0; left: 0;
  width: 15px; height: 15px;
  border-top: 1.5px solid var(--cyan);
  border-left: 1.5px solid var(--cyan);
  border-top-left-radius: 12px;
  opacity: 0.65;
  pointer-events: none;
}
.hud-card::after {
  content: "";
  position: absolute;
  bottom: 0; right: 0;
  width: 15px; height: 15px;
  border-bottom: 1.5px solid var(--accent);
  border-right: 1.5px solid var(--accent);
  border-bottom-right-radius: 12px;
  opacity: 0.65;
  pointer-events: none;
}
.hud-card h2 { margin: 4px 0 10px 0; font-size: 1.3rem; font-weight: 700; color: var(--txt); }
.muted-text { margin: 0; color: var(--sub-txt); font-size: 0.92rem; line-height: 1.6; }
.muted-small { color: var(--sub-txt); font-size: 0.78rem; }

/* Barre de filtres du catalogue */
.filter-bar {
  display: grid;
  grid-template-columns: 2.2fr 1.2fr 1.2fr auto auto;
  gap: 10px;
  align-items: center;
  margin-bottom: 16px;
}
@media (max-width: 960px) {
  .filter-bar { grid-template-columns: 1fr 1fr; }
}
.catalog-meta-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.76rem;
  color: var(--sub-txt);
}

/* Grille de cartes molécules */
.catalog-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
@media (max-width: 900px) {
  .catalog-grid { grid-template-columns: 1fr; }
}
.mol-card {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  background: var(--card-glass);
  backdrop-filter: blur(12px) saturate(145%);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  cursor: pointer;
  overflow: hidden;
  transition: transform 0.2s cubic-bezier(0.22, 1, 0.36, 1), border-color 0.2s ease, box-shadow 0.25s ease;
  animation: panelFadeIn 0.22s ease-out;
}
.mol-card::before {
  content: "";
  position: absolute;
  top: 0; left: 0;
  width: 14px; height: 14px;
  border-top: 1.5px solid var(--cyan);
  border-left: 1.5px solid var(--cyan);
  border-top-left-radius: 14px;
  opacity: 0.55;
  pointer-events: none;
}
.mol-card:hover {
  transform: translateY(-3px);
  border-color: var(--cyan);
  box-shadow: 0 12px 30px var(--cyan-soft);
}
.hex-watermark {
  position: absolute;
  right: -18px;
  bottom: -18px;
  width: 115px;
  height: 115px;
  color: var(--cyan);
  opacity: 0.05;
  pointer-events: none;
}
.mol-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.mol-title {
  margin: 0;
  font-size: 1.12rem;
  font-weight: 700;
  color: var(--txt);
  line-height: 1.25;
}
.mol-subrow {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 4px;
}
.mono-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  color: var(--cyan);
  background: var(--cyan-soft);
  border: 1px solid var(--border);
  padding: 2px 7px;
  border-radius: 6px;
}
.yield-tag {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  color: var(--accent);
  background: var(--accent-soft);
  border: 1px solid rgba(16, 185, 129, 0.30);
  padding: 2px 7px;
  border-radius: 6px;
}
.stock-pill {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.69rem;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
}
.stock-ok { background: rgba(16, 185, 129, 0.14); color: var(--accent); border: 1px solid rgba(16, 185, 129, 0.34); }
.stock-low { background: rgba(245, 158, 11, 0.14); color: var(--warn); border: 1px solid rgba(245, 158, 11, 0.34); }
.stock-empty { background: rgba(225, 29, 72, 0.14); color: var(--danger); border: 1px solid rgba(225, 29, 72, 0.34); }

.fav-btn {
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--sub-txt);
  font-size: 1rem;
  flex-shrink: 0;
  transition: all 0.18s ease;
}
.fav-btn:hover { border-color: #f59e0b; color: #f59e0b; }
.fav-btn.is-fav { background: rgba(245, 158, 11, 0.14); border-color: rgba(245, 158, 11, 0.45); color: #f59e0b; }

.mol-card-body {
  display: grid;
  grid-template-columns: 1fr 145px;
  gap: 14px;
  align-items: center;
}
@media (max-width: 520px) {
  .mol-card-body { grid-template-columns: 1fr; }
}
.mol-preview-box {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 118px;
  border-radius: 10px;
  background: var(--sub-card);
  border: 1px solid var(--border);
  padding: 6px;
  overflow: hidden;
}
.mol-preview-box img {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
}

/* Structures 2D & équations 100 % transparentes en mode sombre (couleurs atomes préservées) */
html[data-theme="dark"] .mol-2d-adaptive,
html[data-theme="dark"] .rxn-svg-adaptive {
  filter: invert(1) hue-rotate(180deg) brightness(1.08) contrast(1.10);
  mix-blend-mode: screen;
}
html[data-theme="light"] .mol-2d-adaptive,
html[data-theme="light"] .rxn-svg-adaptive {
  mix-blend-mode: multiply;
}

.rx-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.rx-pill {
  font-size: 0.76rem;
  font-weight: 600;
  color: var(--txt);
  background: var(--sub-card);
  border: 1px solid var(--border);
  padding: 3px 9px;
  border-radius: 7px;
}
.rx-pill-click {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 0.80rem;
  font-weight: 600;
  color: var(--cyan);
  background: var(--cyan-soft);
  border: 1px solid var(--border);
  padding: 5px 11px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.rx-pill-click:hover {
  border-color: var(--cyan);
  box-shadow: 0 0 12px var(--cyan-soft);
  transform: translateY(-1px);
}
.rea-pill-click {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 0.80rem;
  font-weight: 600;
  color: var(--txt);
  background: var(--sub-card);
  border: 1px solid var(--border);
  padding: 5px 11px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.rea-pill-click:hover {
  border-color: var(--accent);
  color: var(--accent);
  box-shadow: 0 0 12px var(--accent-soft);
  transform: translateY(-1px);
}

.mol-info-line {
  font-size: 0.80rem;
  color: var(--sub-txt);
  margin: 4px 0;
  line-height: 1.45;
}
.mol-info-line strong { color: var(--txt); font-weight: 600; }

/* Pictogrammes SGH */
.sgh-row { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; margin-top: 6px; }
.sgh-item {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 4px 6px;
  border-radius: 7px;
  background: var(--sub-card);
  border: 1px solid var(--border);
}
.sgh-item img { width: 32px; height: 32px; object-fit: contain; }
.sgh-item span { font-family: 'JetBrains Mono', monospace; font-size: 0.62rem; color: var(--sub-txt); }
.sgh-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  border-radius: 7px;
  background: rgba(245, 158, 11, 0.12);
  border: 1px solid rgba(245, 158, 11, 0.35);
  font-size: 0.72rem;
  color: var(--txt);
}
.sgh-badge strong { font-family: 'JetBrains Mono', monospace; color: var(--warn); }

/* Modales Fiche Technique & Vue Inspecteur */
.cb-modal-card {
  width: min(1040px, 94vw) !important;
  max-width: 94vw !important;
  max-height: 90vh;
  overflow-y: auto;
  background: var(--modal-bg) !important;
  backdrop-filter: blur(22px) saturate(160%);
  border: 1px solid var(--border) !important;
  border-radius: 16px !important;
  padding: 24px 26px !important;
  color: var(--txt) !important;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.50) !important;
}
.cb-inspector-card {
  width: min(860px, 92vw) !important;
  max-width: 92vw !important;
  max-height: 88vh;
  overflow-y: auto;
  background: var(--modal-bg) !important;
  backdrop-filter: blur(24px) saturate(170%);
  border: 1px solid var(--cyan) !important;
  border-radius: 16px !important;
  padding: 24px 26px !important;
  color: var(--txt) !important;
  box-shadow: 0 28px 72px rgba(0, 0, 0, 0.60) !important;
}
.modal-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 18px;
}
.modal-grid {
  display: grid;
  grid-template-columns: 1.25fr 1fr;
  gap: 18px;
}
@media (max-width: 820px) {
  .modal-grid { grid-template-columns: 1fr; }
}
.detail-box {
  background: var(--sub-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 15px 17px;
  margin-bottom: 14px;
}
.detail-title {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--cyan);
  font-weight: 600;
  margin-bottom: 10px;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.kv-item {
  background: var(--card-glass);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 9px 11px;
}
.kv-label {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.66rem;
  text-transform: uppercase;
  color: var(--sub-txt);
}
.kv-val {
  font-size: 0.86rem;
  font-weight: 600;
  color: var(--txt);
  margin-top: 2px;
  word-break: break-word;
}
.rxn-canvas-box {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  border-radius: 10px;
  background: var(--card-glass);
  border: 1px solid var(--border);
  min-height: 110px;
  overflow: hidden;
}
.rxn-canvas-box img { max-width: 100%; max-height: 170px; object-fit: contain; }
.viewer-3d-frame {
  width: 100%;
  height: 245px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--card-solid);
}

/* Formulaire Nouvelle Fiche */
.form-grid-2 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
@media (max-width: 760px) {
  .form-grid-2 { grid-template-columns: 1fr; }
}

.app-footer {
  margin-top: 28px;
  padding-top: 14px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.71rem;
  letter-spacing: 0.06em;
  color: var(--sub-txt);
}
</style>
"""


THEME_ENGINE_JS = """
<script>
(function() {
  function startMoleculeCanvas() {
    let cvs = document.getElementById("mol-canvas");
    if (!cvs) {
      cvs = document.createElement("canvas");
      cvs.id = "mol-canvas";
      document.body.prepend(cvs);
    }
    if (cvs.dataset.running === "1") return;
    cvs.dataset.running = "1";

    const ctx = cvs.getContext("2d");
    let W = cvs.width = window.innerWidth;
    let H = cvs.height = window.innerHeight;
    const mouse = { x: -9999, y: -9999 };

    window.addEventListener("resize", () => {
      W = cvs.width = window.innerWidth;
      H = cvs.height = window.innerHeight;
      if (typeof window.cbMovePill === "function") window.cbMovePill(true);
    });
    document.addEventListener("mousemove", (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
    document.addEventListener("mouseleave", () => { mouse.x = -9999; mouse.y = -9999; });

    const mols = [];
    for (let i = 0; i < 12; i++) {
      mols.push({
        x: Math.random() * W, y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.45, vy: (Math.random() - 0.5) * 0.45,
        angle: Math.random() * Math.PI * 2, vAngle: (Math.random() - 0.5) * 0.0058,
        size: 24 + Math.random() * 24, type: i % 3, useCyan: i % 2 === 0
      });
    }

    function drawHex(cx, cy, r, doubleBonds) {
      ctx.beginPath();
      for (let k = 0; k < 6; k++) {
        const a = (Math.PI / 3) * k - Math.PI / 2;
        const px = cx + r * Math.cos(a), py = cy + r * Math.sin(a);
        if (k === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath();
      ctx.stroke();
      if (doubleBonds) {
        for (let k = 0; k < 6; k += 2) {
          const a1 = (Math.PI / 3) * k - Math.PI / 2;
          const a2 = (Math.PI / 3) * (k + 1) - Math.PI / 2;
          ctx.beginPath();
          ctx.moveTo(cx + r * 0.74 * Math.cos(a1), cy + r * 0.74 * Math.sin(a1));
          ctx.lineTo(cx + r * 0.74 * Math.cos(a2), cy + r * 0.74 * Math.sin(a2));
          ctx.stroke();
        }
      }
      for (let k = 0; k < 6; k++) {
        const a = (Math.PI / 3) * k - Math.PI / 2;
        ctx.beginPath();
        ctx.arc(cx + r * Math.cos(a), cy + r * Math.sin(a), 2.4, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    function drawMolecule(m, isDark, boost) {
      ctx.save();
      ctx.translate(m.x, m.y);
      ctx.rotate(m.angle);
      const alpha = isDark ? (0.16 + boost * 0.30) : (0.15 + boost * 0.28);
      const col = m.useCyan
        ? (isDark ? `rgba(56, 189, 248, ${alpha})` : `rgba(2, 132, 199, ${alpha})`)
        : (isDark ? `rgba(16, 185, 129, ${alpha})` : `rgba(5, 150, 105, ${alpha})`);
      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      ctx.lineWidth = 1.45 + boost * 0.9;
      const r = m.size;
      if (m.type === 0) {
        drawHex(0, 0, r, true);
        ctx.beginPath();
        ctx.moveTo(0, -r); ctx.lineTo(0, -r * 1.55); ctx.lineTo(r * 0.45, -r * 1.85);
        ctx.stroke();
        ctx.beginPath(); ctx.arc(r * 0.45, -r * 1.85, 2.8, 0, Math.PI * 2); ctx.fill();
      } else if (m.type === 1) {
        const dx = r * Math.cos(Math.PI / 6);
        drawHex(-dx, 0, r, true); drawHex(dx, 0, r, false);
      } else {
        const pts = [[-r*1.4, r*0.3], [-r*0.7, -r*0.3], [0, r*0.3], [r*0.7, -r*0.3], [r*1.4, r*0.3]];
        ctx.beginPath();
        pts.forEach((pt, idx) => idx === 0 ? ctx.moveTo(pt[0], pt[1]) : ctx.lineTo(pt[0], pt[1]));
        ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, r * 0.3); ctx.lineTo(0, r * 0.95); ctx.stroke();
        pts.forEach((pt) => { ctx.beginPath(); ctx.arc(pt[0], pt[1], 2.5, 0, Math.PI * 2); ctx.fill(); });
        ctx.beginPath(); ctx.arc(0, r * 0.95, 2.8, 0, Math.PI * 2); ctx.fill();
      }
      ctx.restore();
    }

    function animate() {
      const isDark = document.documentElement.getAttribute("data-theme") !== "light";
      ctx.clearRect(0, 0, W, H);
      for (let i = 0; i < mols.length; i++) {
        const m = mols[i];
        const dx = m.x - mouse.x, dy = m.y - mouse.y;
        const dist = Math.hypot(dx, dy);
        let boost = 0;
        if (dist < 220 && dist > 1) {
          boost = 1 - (dist / 220);
          const force = boost * 0.65;
          m.x += (dx / dist) * force; m.y += (dy / dist) * force;
          m.angle += m.vAngle * (1 + boost * 3.5);
        } else {
          m.angle += m.vAngle;
        }
        m.x += m.vx; m.y += m.vy;
        const pad = m.size * 2.2;
        if (m.x < -pad) m.x = W + pad;
        if (m.x > W + pad) m.x = -pad;
        if (m.y < -pad) m.y = H + pad;
        if (m.y > H + pad) m.y = -pad;
        drawMolecule(m, isDark, boost);
      }
      requestAnimationFrame(animate);
    }
    animate();
  }

  window.cbMovePill = function(instant) {
    const nav = document.getElementById("lg-nav");
    const pill = document.getElementById("lg-pill");
    if (!nav || !pill) return;
    const activeTab = nav.querySelector(".lg-tab.active");
    if (!activeTab) return;
    const left = activeTab.offsetLeft - 5;
    const width = activeTab.offsetWidth;
    if (instant) {
      const prev = pill.style.transition;
      pill.style.transition = "none";
      pill.style.width = width + "px";
      pill.style.transform = "translateX(" + left + "px)";
      pill.style.opacity = "1";
      pill.offsetHeight;
      pill.style.transition = prev;
    } else {
      pill.style.width = width + "px";
      pill.style.transform = "translateX(" + left + "px)";
      pill.style.opacity = "1";
    }
  };

  window.cbApplyTheme = function(mode) {
    const isDark = mode !== "light";
    document.documentElement.setAttribute("data-theme", isDark ? "dark" : "light");
    const sun = document.getElementById("icon-sun");
    const moon = document.getElementById("icon-moon");
    const toggleBtn = document.getElementById("theme-toggle");
    if (sun && moon) {
      sun.style.display = isDark ? "block" : "none";
      moon.style.display = isDark ? "none" : "block";
    }
    if (toggleBtn) toggleBtn.title = isDark ? "Passer en mode clair" : "Passer en mode sombre";

    const palette = isDark
      ? ["#0f766e", "#34d399", "#38bdf8", "#1d4ed8"]
      : ["#065f46", "#10b981", "#0284c7", "#1e3a8a"];
    const [c1, c2, c3, c4] = palette;
    [
      ["lg-s1", "lg-a1", c1, `${c1};${c3};${c4};${c2};${c1}`],
      ["lg-s2", "lg-a2", c2, `${c2};${c4};${c1};${c3};${c2}`],
      ["lg-s3", "lg-a3", c3, `${c3};${c1};${c2};${c4};${c3}`],
      ["lg-s4", "lg-a4", c4, `${c4};${c2};${c3};${c1};${c4}`],
    ].forEach(([sid, aid, col, vals]) => {
      const s = document.getElementById(sid), a = document.getElementById(aid);
      if (s) s.setAttribute("stop-color", col);
      if (a) a.setAttribute("values", vals);
    });
    const logoText = document.getElementById("cb-logo-text");
    if (logoText) logoText.setAttribute("fill", isDark ? "#f8fafc" : "#0f172a");
  };

  function boot() {
    document.documentElement.setAttribute("data-theme", "dark");
    startMoleculeCanvas();
    setTimeout(() => window.cbMovePill(true), 60);
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(() => window.cbMovePill(true));
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
</script>
"""


LOGO_SVG = """
<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="ChemBase">
  <defs>
    <linearGradient id="cbLiveGrad" gradientUnits="userSpaceOnUse" x1="-120" y1="-40" x2="120" y2="120" spreadMethod="reflect">
      <animate attributeName="x1" values="-120;120;-120" dur="5.5s" repeatCount="indefinite" />
      <animate attributeName="x2" values="120;360;120" dur="5.5s" repeatCount="indefinite" />
      <animate attributeName="y1" values="-40;80;-40" dur="5.5s" repeatCount="indefinite" />
      <animate attributeName="y2" values="120;240;120" dur="5.5s" repeatCount="indefinite" />
      <stop id="lg-s1" offset="0%" stop-color="#0f766e">
        <animate id="lg-a1" attributeName="stop-color" values="#0f766e;#38bdf8;#1d4ed8;#34d399;#0f766e" dur="6s" repeatCount="indefinite" />
      </stop>
      <stop id="lg-s2" offset="35%" stop-color="#34d399">
        <animate id="lg-a2" attributeName="stop-color" values="#34d399;#1d4ed8;#0f766e;#38bdf8;#34d399" dur="6s" repeatCount="indefinite" />
      </stop>
      <stop id="lg-s3" offset="70%" stop-color="#38bdf8">
        <animate id="lg-a3" attributeName="stop-color" values="#38bdf8;#0f766e;#34d399;#1d4ed8;#38bdf8" dur="6s" repeatCount="indefinite" />
      </stop>
      <stop id="lg-s4" offset="100%" stop-color="#1d4ed8">
        <animate id="lg-a4" attributeName="stop-color" values="#1d4ed8;#34d399;#38bdf8;#0f766e;#1d4ed8" dur="6s" repeatCount="indefinite" />
      </stop>
    </linearGradient>
  </defs>
  <polygon points="60,16 98.1,38 98.1,82 60,104 21.9,82 21.9,38" fill="none" stroke="url(#cbLiveGrad)" stroke-width="6.2" stroke-linejoin="round" stroke-linecap="round"/>
  <line x1="31.5" y1="43.5" x2="54" y2="30.5" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="88.5" y1="45" x2="88.5" y2="75" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="88" y1="77" x2="66" y2="89.8" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="54" y1="89.8" x2="32" y2="77" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="21.9" y1="38" x2="35" y2="45.6" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="98.1" y1="38" x2="85" y2="45.6" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <line x1="21.9" y1="82" x2="35" y2="74.4" stroke="url(#cbLiveGrad)" stroke-width="4.5" stroke-linecap="round"/>
  <circle cx="60" cy="16" r="8.8" fill="url(#cbLiveGrad)"/>
  <circle cx="98.1" cy="38" r="8.8" fill="url(#cbLiveGrad)"/>
  <circle cx="98.1" cy="82" r="8.8" fill="url(#cbLiveGrad)"/>
  <circle cx="60" cy="104" r="8.8" fill="url(#cbLiveGrad)"/>
  <circle cx="21.9" cy="82" r="8.8" fill="url(#cbLiveGrad)"/>
  <circle cx="21.9" cy="38" r="8.8" fill="url(#cbLiveGrad)"/>
  <text id="cb-logo-text" x="60" y="70.5" text-anchor="middle" font-family="'Plus Jakarta Sans', sans-serif" font-size="33" font-weight="800" letter-spacing="-1.2" fill="#f8fafc">CB</text>
</svg>
"""


THEME_TOGGLE_SVGS = """
<svg id="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="12" r="4"></circle>
  <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"></path>
</svg>
<svg id="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="display:none;">
  <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>
</svg>
"""


def inject_theme():
    ui.add_head_html(THEME_HEAD_HTML)
    ui.add_body_html(THEME_ENGINE_JS)