// Floating draggable chrome around a BoardPanel, used only when WebTAK's docked drawer isn't
// available (standalone demo, or the drawer API missing/failing) — see ../index.js.

import { BoardPanel } from './ui.js';

export function mountFloatingPanel() {
  const wrap = document.createElement('div');
  wrap.className = 'wcad-panel-wrap';
  wrap.innerHTML = `
    <div class="wcad-panel">
      <div class="wcad-panel-head"><span>🚑 CrowdCAD</span><button class="wcad-btn wcad-close" title="Close">&#10005;</button></div>
      <div class="wcad-host"></div>
    </div>`;
  const panel = wrap.querySelector('.wcad-panel');
  const head = wrap.querySelector('.wcad-panel-head');
  document.body.appendChild(wrap);
  const content = new BoardPanel(wrap.querySelector('.wcad-host'));

  const destroy = () => { content.destroy(); wrap.remove(); };
  wrap.querySelector('.wcad-close').addEventListener('click', destroy);

  let sx, sy, ox, oy, dragging = false;
  head.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.wcad-btn')) return;
    dragging = true;
    head.setPointerCapture(e.pointerId);
    sx = e.clientX; sy = e.clientY;
    const r = panel.getBoundingClientRect();
    ox = r.left; oy = r.top;
    panel.style.right = 'auto';
  });
  head.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    panel.style.left = Math.min(Math.max(0, ox + (e.clientX - sx)), window.innerWidth - 80) + 'px';
    panel.style.top = Math.min(Math.max(0, oy + (e.clientY - sy)), window.innerHeight - 40) + 'px';
  });
  const endDrag = (e) => { if (dragging) { dragging = false; try { head.releasePointerCapture(e.pointerId); } catch { /* already released */ } } };
  head.addEventListener('pointerup', endDrag);
  head.addEventListener('pointercancel', endDrag);

  return { show() { panel.style.display = 'flex'; content.refresh(); }, destroy };
}
