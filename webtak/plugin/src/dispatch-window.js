// CrowdCAD's own dispatch screen for one event, in a large floating window over the WebTAK map
// (draggable by its header, resizable from its corner). Dispatching is CrowdCAD itself: the
// dispatcher signs in to CrowdCAD inside the frame, every change follows CrowdCAD's rules and
// lands in its call log under their name. Nothing here writes to CrowdCAD.
//
// One window at a time: Dispatch on another event just points the frame at that event.

let win = null;

// Only ever frame an https URL (it comes from the bridge's board, but never trust a string into
// an iframe src blindly — a javascript: URL would run in WebTAK's page).
export function safeDispatchUrl(url) {
  return typeof url === 'string' && /^https:\/\/[^\s"'<>]+$/.test(url) ? url : null;
}

export function openDispatchWindow(url, name) {
  const safe = safeDispatchUrl(url);
  if (!safe) return null;
  if (!win) win = create();
  win.title.textContent = `CrowdCAD dispatch — ${name || ''}`;
  win.link.href = safe;
  if (win.frame.getAttribute('src') !== safe) win.frame.setAttribute('src', safe);
  win.panel.style.display = 'flex';
  return win;
}

export function closeDispatchWindow() {
  if (!win) return;
  win.wrap.remove();
  win = null;
}

function create() {
  const wrap = document.createElement('div');
  wrap.className = 'wcad-panel-wrap wcad-dispatch-wrap';
  wrap.innerHTML = `
    <div class="wcad-panel wcad-dispatch">
      <div class="wcad-panel-head">
        <span class="wcad-dispatch-title"></span>
        <a class="wcad-btn wcad-dispatch-open" target="_blank" rel="noopener" title="Open in a new browser window">Open in new window ↗</a>
        <button class="wcad-btn wcad-close" title="Close">&#10005;</button>
      </div>
      <iframe class="wcad-dispatch-frame" allow="clipboard-read; clipboard-write; fullscreen"
        referrerpolicy="strict-origin-when-cross-origin"></iframe>
    </div>`;
  document.body.appendChild(wrap);
  const panel = wrap.querySelector('.wcad-panel');
  const head = wrap.querySelector('.wcad-panel-head');
  const frame = wrap.querySelector('iframe');
  wrap.querySelector('.wcad-close').addEventListener('click', closeDispatchWindow);

  // Size to the window: CrowdCAD's dispatch screen is laid out for a desktop.
  panel.style.left = '60px';
  panel.style.top = '60px';
  panel.style.right = 'auto';
  panel.style.width = Math.max(400, Math.min(1280, window.innerWidth - 120)) + 'px';
  panel.style.height = Math.max(300, Math.min(860, window.innerHeight - 100)) + 'px';

  let sx, sy, ox, oy, dragging = false;
  head.addEventListener('pointerdown', (e) => {
    if (e.target.closest('.wcad-btn')) return;
    dragging = true;
    head.setPointerCapture(e.pointerId);
    frame.style.pointerEvents = 'none';   // the iframe would swallow pointermove mid-drag
    sx = e.clientX; sy = e.clientY;
    const r = panel.getBoundingClientRect();
    ox = r.left; oy = r.top;
  });
  head.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    panel.style.left = Math.min(Math.max(0, ox + (e.clientX - sx)), window.innerWidth - 80) + 'px';
    panel.style.top = Math.min(Math.max(0, oy + (e.clientY - sy)), window.innerHeight - 40) + 'px';
  });
  const endDrag = (e) => {
    if (!dragging) return;
    dragging = false;
    frame.style.pointerEvents = '';
    try { head.releasePointerCapture(e.pointerId); } catch { /* already released */ }
  };
  head.addEventListener('pointerup', endDrag);
  head.addEventListener('pointercancel', endDrag);

  return { wrap, panel, frame, title: wrap.querySelector('.wcad-dispatch-title'), link: wrap.querySelector('.wcad-dispatch-open') };
}
