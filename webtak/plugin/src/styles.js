// Injected stylesheet (a JS string, so the plugin stays one self-contained bundle with no CSS
// fetch — friendly to WebTAK's CSP). Same dark theme as WebTAK-Plugin-Channels.

const CSS = `
.wcad-content { display: flex; flex-direction: column; height: 100%; background: #111114; color: #e8ebf2;
  overflow: hidden; font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; font-size: 12px; }
.wcad-content * { box-sizing: border-box; }
.wcad-toolbar { display: flex; gap: 8px; padding: 8px 12px; border-bottom: 1px solid #242424; align-items: center; }
.wcad-spacer { flex: 1; }
.wcad-event { flex: 1; background: #0b0b0e; color: #e8ebf2; border: 1px solid #2a2a30; border-radius: 6px; padding: 4px 6px; }
.wcad-btn { background: transparent; color: #9aa3b5; border: 1px solid #2a2a30; padding: 4px 10px; border-radius: 6px; cursor: pointer; }
.wcad-btn:hover { color: #fff; border-color: #444; }
.wcad-settings { padding: 8px 12px; border-bottom: 1px solid #242424; display: grid; gap: 6px; }
.wcad-settings label { display: grid; gap: 2px; color: #7c8598; }
.wcad-settings input { background: #0b0b0e; color: #e8ebf2; border: 1px solid #2a2a30; border-radius: 6px; padding: 5px 8px; }
.wcad-body { overflow: auto; flex: 1 1 auto; }
.wcad-head { padding: 10px 12px 4px; color: #7c8598; font-size: 11px; text-transform: uppercase; letter-spacing: .05em; }
.wcad-row { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid #1c1c20; }
.wcad-row-main { flex: 1; min-width: 0; }
.wcad-row-name { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wcad-row-meta { color: #7c8598; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wcad-badge { padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 700; background: #1c1c20; white-space: nowrap; }
.wcad-p1 { background: #e03131; color: #fff; border-radius: 3px; padding: 0 4px; font-size: 10px; font-weight: 700; margin-right: 4px; }
.wcad-red { color: #ff5c5c; }
.wcad-dim { color: #7c8598; }
.wcad-empty { padding: 16px; text-align: center; color: #7c8598; }
.wcad-error { margin: 8px 12px; padding: 8px; border-radius: 6px; background: rgba(255,92,92,.1); color: #ff8a8a; }
.wcad-warn { margin: 8px 12px; padding: 8px; border-radius: 6px; background: rgba(255,212,59,.08); color: #ffd43b; }
.wcad-foot { padding: 6px 12px; border-top: 1px solid #242424; color: #7c8598; font-size: 11px; }
.wcad-launch { position: fixed; right: 16px; bottom: 16px; z-index: 9999; background: #1b1b20; color: #e8ebf2;
  border: 1px solid #333; border-radius: 8px; padding: 8px 12px; cursor: pointer; }
.wcad-panel-wrap { position: fixed; inset: 0; pointer-events: none; z-index: 9998; }
.wcad-panel { position: absolute; top: 70px; right: 20px; width: 380px; height: 70vh; display: flex; flex-direction: column;
  pointer-events: auto; border: 1px solid #2a2a30; border-radius: 10px; overflow: hidden; box-shadow: 0 8px 30px rgba(0,0,0,.5); }
.wcad-panel-head { display: flex; align-items: center; padding: 8px 12px; background: #17171b; cursor: move; color: #e8ebf2; }
.wcad-panel-head span { flex: 1; font-weight: 600; }
.wcad-host { flex: 1; min-height: 0; }
.wcad-event-head { display: flex; align-items: center; gap: 8px; }
.wcad-event-head span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wcad-dispatch-btn { color: #fff; background: #1f6feb; border-color: #1f6feb; text-transform: none; letter-spacing: 0; font-size: 12px; }
.wcad-dispatch-btn:hover { background: #388bfd; border-color: #388bfd; }
.wcad-link { color: #58a6ff; }
.wcad-chip { background: rgba(255,212,59,.12); color: #ffd43b; border-radius: 3px; padding: 0 5px; font-size: 10px; }
.wcad-yellow { color: #ffd43b; }
.wcad-note { margin: 8px 12px; color: #ffd43b; font-size: 11px; }
.wcad-dispatch-wrap { z-index: 9999; }
.wcad-dispatch { resize: both; min-width: 400px; min-height: 300px; background: #111114; }
.wcad-dispatch .wcad-panel-head { gap: 8px; }
.wcad-dispatch .wcad-panel-head span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wcad-dispatch-open { text-decoration: none; white-space: nowrap; }
.wcad-dispatch-frame { flex: 1; width: 100%; border: 0; background: #fff; }
`;

let injected = false;

export function injectStyles() {
  if (injected || document.getElementById('wcad-styles')) return;
  const style = document.createElement('style');
  style.id = 'wcad-styles';
  style.textContent = CSS;
  document.head.appendChild(style);
  injected = true;
}
