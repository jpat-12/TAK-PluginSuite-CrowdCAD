// The board content: open calls of the live CrowdCAD event (priority first), its teams, and
// anything CrowdCAD couldn't place. Builds INTO a host element, so the same class fills a real
// WebTAK docked drawer (../index.js) or the floating fallback (./floating-panel.js) — the
// pattern from WebTAK-Plugin-Channels.
//
// The board is read-only; its Dispatch button opens CrowdCAD's own dispatch screen in a floating
// window (./dispatch-window.js), where the dispatcher signs in to CrowdCAD as themselves. The
// markers reach WebTAK as ordinary CoT from TAK Server; this panel draws nothing on the map
// (WebTAK exposes no map API to plugins that we've verified).

import { fetchBoard } from './board-client.js';
import { getConfig, setConfig } from './config.js';
import { openDispatchWindow, safeDispatchUrl } from './dispatch-window.js';
import { INCIDENT, UNIT, age, bridgeWarning, escapeHtml, pickEvent } from './format.js';

// A plain alias, not `import … as h`: build.py concatenates modules and drops import lines.
const h = escapeHtml;

export class BoardPanel {
  constructor(host) {
    this.host = host;
    this.board = null;
    this.error = null;
    this.eventId = '';
    this.settingsOpen = !getConfig().bridgeUrl || !getConfig().token;

    host.classList.add('wcad-content');
    host.innerHTML = `
      <div class="wcad-toolbar">
        <select class="wcad-event" hidden></select>
        <span class="wcad-spacer"></span>
        <button class="wcad-btn wcad-settings-btn" title="Settings">⚙</button>
      </div>
      <form class="wcad-settings" hidden>
        <label>Bridge URL<input name="bridgeUrl" type="text" placeholder="https://crowdcad-tak.example.org"></label>
        <label>Board token<input name="token" type="password" autocomplete="off"></label>
        <button class="wcad-btn" type="submit">Save</button>
      </form>
      <div class="wcad-body"><div class="wcad-empty">Loading…</div></div>
      <div class="wcad-foot"></div>`;
    this.body = host.querySelector('.wcad-body');
    this.foot = host.querySelector('.wcad-foot');
    this.select = host.querySelector('.wcad-event');
    this.form = host.querySelector('.wcad-settings');

    this.select.addEventListener('change', () => { this.eventId = this.select.value; this._render(); });
    this.body.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-dispatch]');
      if (btn) openDispatchWindow(btn.getAttribute('data-dispatch'), btn.getAttribute('data-name'));
    });
    host.querySelector('.wcad-settings-btn').addEventListener('click', () => this._toggleSettings());
    this.form.addEventListener('submit', (e) => {
      e.preventDefault();
      setConfig({ bridgeUrl: this.form.bridgeUrl.value.trim(), token: this.form.token.value.trim() });
      this._toggleSettings(false);
      this.refresh();
    });
    this._toggleSettings(this.settingsOpen);

    this.refresh();
    this.timer = setInterval(() => this.refresh(), getConfig().pollMs);
  }

  destroy() {
    clearInterval(this.timer);
    this.host.innerHTML = '';
  }

  _toggleSettings(open = this.form.hidden) {
    const cfg = getConfig();
    this.form.bridgeUrl.value = cfg.bridgeUrl;
    this.form.token.value = cfg.token;
    this.form.hidden = !open;
  }

  async refresh() {
    try {
      this.board = await fetchBoard(getConfig());
      this.error = null;
    } catch (err) {
      this.error = err.message;   // keep the last good board under the error
    }
    this._render();
  }

  _render() {
    const now = Date.now();
    const board = this.board;
    const events = (board && board.events) || [];
    if (events.length && !events.some((e) => e.id === this.eventId)) this.eventId = events[0].id;
    this.select.hidden = events.length < 2;
    this.select.innerHTML = events.map((e) =>
      `<option value="${h(e.id)}"${e.id === this.eventId ? ' selected' : ''}>${h(eventLabel(e))}</option>`).join('');

    const parts = [];
    if (this.error) parts.push(`<div class="wcad-error">${h(this.error)}</div>`);
    const warning = board && bridgeWarning(board.bridge);
    if (warning) parts.push(`<div class="wcad-warn">${h(warning)}</div>`);
    const event = pickEvent(board, this.eventId);
    if (!board && !this.error) parts.push('<div class="wcad-empty">Loading…</div>');
    else if (board && !event) {
      const site = safeDispatchUrl(board.crowdcadUrl);
      parts.push(`<div class="wcad-empty">No live CrowdCAD event.${site
        ? ` <a class="wcad-link" href="${h(site)}" target="_blank" rel="noopener">Open CrowdCAD ↗</a>` : ''}</div>`);
    }
    if (event) parts.push(renderEvent(event, now));
    this.body.innerHTML = parts.join('');
    this.foot.textContent = board
      ? `Updated ${age(board.generated, now)} ago · ${event && safeDispatchUrl(event.dispatchUrl) ? 'dispatch opens CrowdCAD' : 'read-only view of CrowdCAD'}`
      : '';
  }
}

// "IU Football · Nov 21 · TAK · 2 calls": same-named events must be tellable apart.
export function eventLabel(e) {
  const parts = [e.name];
  const d = e.date ? new Date(e.date) : null;
  if (d && !Number.isNaN(d.getTime())) parts.push(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }));
  if (e.endable) parts.push('TAK');
  parts.push(`${e.calls.length} ${e.calls.length === 1 ? 'call' : 'calls'}`);
  return parts.join(' · ');
}

const NOT_ON_MAP = '<span class="wcad-chip" title="Its location isn\'t a post on a GeoJSON-imported venue layer">not on map</span>';

function heard(u, now) {
  if (!u.device) return u.placed === false ? ` · ${NOT_ON_MAP}` : '';
  if (!u.lastHeard) {
    return ' · <span class="wcad-yellow" title="No reports from this device reach the CrowdCAD bridge: check it is connected and in the bridge\'s TAK group">📡 no reports</span>';
  }
  const s = Math.max(0, Math.floor((now - u.lastHeard) / 1000));
  return ` · 📡 ${s < 90 ? `${s}s` : age(u.lastHeard, now)} ago`;
}

export function renderEvent(event, now) {
  const calls = event.calls.length ? event.calls.map((c) => {
    const s = INCIDENT[c.status] || { label: c.status || '—', color: '#9aa3b5' };
    const who = c.assigned.length
      ? h(c.assigned.map((a) => a.callsign).join(', '))
      : '<span class="wcad-red">no unit</span>';
    return `
      <div class="wcad-row">
        <div class="wcad-row-main">
          <div class="wcad-row-name">${c.priority === 1 ? '<span class="wcad-p1">P1</span>' : ''}
            <b>${h(c.id)}</b> ${h(c.type)}</div>
          <div class="wcad-row-meta">${h(c.location || 'No location')}${c.created ? ` · ${age(c.created, now)}` : ''} · ${who}${c.placed === false ? ` · ${NOT_ON_MAP}` : ''}</div>
        </div>
        <span class="wcad-badge" style="color:${s.color}">${h(s.label)}</span>
      </div>`;
  }).join('') : '<div class="wcad-empty">No open calls.</div>';

  const units = event.units.map((u) => {
    const s = u.status ? UNIT[u.status] : null;
    return `
      <div class="wcad-row wcad-unit">
        <div class="wcad-row-main"><div class="wcad-row-name">${h(u.callsign)}${u.supervisor ? ' <span class="wcad-dim">supervisor</span>' : ''}</div>
          <div class="wcad-row-meta">${h(u.incident || u.location || '—')}${heard(u, now)}</div></div>
        ${s ? `<span class="wcad-badge" style="color:${s.color}">${h(s.label)}</span>` : '<span class="wcad-dim">—</span>'}
      </div>`;
  }).join('');

  const off = event.calls.filter((c) => c.placed === false).length + event.units.filter((u) => u.placed === false && !u.device).length;
  const unplaced = off ? `<div class="wcad-note">${off} not on the map: their location isn't a post on a GeoJSON-imported venue layer.</div>` : '';

  const n = event.calls.length;
  const dispatch = safeDispatchUrl(event.dispatchUrl);
  return `
    <div class="wcad-head wcad-event-head"><span>${h(event.name)} · ${n} open ${n === 1 ? 'call' : 'calls'}</span>${dispatch
      ? `<button class="wcad-btn wcad-dispatch-btn" data-dispatch="${h(dispatch)}" data-name="${h(event.name)}" title="Open CrowdCAD's dispatch screen for this event">Dispatch</button>` : ''}</div>
    ${calls}
    <div class="wcad-head">Units</div>
    ${units || '<div class="wcad-empty">No units in this event.</div>'}
    ${unplaced}`;
}
