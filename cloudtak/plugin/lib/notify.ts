// A notification bar across the top of CloudTAK, mounted when the plugin is enabled, so it shows
// whether or not the CrowdCAD drawer is open:
//   red    Request Supervisor (stays until a dispatcher clears it): Dispatch supervisor · Locate · Clear
//   green  "Medic 1 acknowledged CC-007" (60 s, or until Dismiss): Locate · Dismiss
// Plain DOM on purpose: it lives outside the drawer's Vue tree. Updated by lib/bridge.ts on every
// board refresh.
// Tracker R36: a new bar also plays a short sound (Settings → Notification sound), synthesized with
// WebAudio because CloudTAK's CSP allows no audio files. Only bars new since the last poll sound:
// never the requests already open when the plugin starts, never once per poll.
import { store } from './store.ts';
import type { Ack, SupRequest } from './core.ts';

const ID = 'plugin-crowdcad-notify';
const ACK_MS = 60_000;

type Handlers = {
    locate: (lat: number, lon: number) => void;
    clear: (id: string) => void;
    dispatchSupervisor: (r: SupRequest) => void;   // open the panel on that unit's call (index.ts)
};
let handlers: Handlers | null = null;
let acks: (Ack & { shownAt: number; until: number })[] = [];
let requests: SupRequest[] = [];
let timer: ReturnType<typeof setInterval> | undefined;
let knownRequests: Set<string> | null = null;   // R36: request ids seen; null until the first board

// ── Sound (R36) ─────────────────────────────────────────────────────────────────────────────────
// Browsers start an AudioContext suspended until the page has had a click or key press, so make
// one lazily and resume it on the first gesture; a notification after that can sound.
let audio: AudioContext | null = null;

function context(): AudioContext | null {
    try {
        if (!audio) audio = new AudioContext();
        if (audio.state === 'suspended') void audio.resume().catch(() => { /* needs a gesture first */ });
        return audio;
    } catch (e) {
        console.warn('[plugin-crowdcad] notification sound unavailable', e);
        return null;
    }
}

function unlock(): void {
    context();
}

/** One soft-edged sine note: start s from now, len s long. */
function tone(ctx: AudioContext, freq: number, start: number, len: number, peak: number): void {
    const t0 = ctx.currentTime + start;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, t0);
    gain.gain.linearRampToValueAtTime(peak, t0 + 0.015);
    gain.gain.setValueAtTime(peak, t0 + len - 0.04);
    gain.gain.linearRampToValueAtTime(0, t0 + len);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + len + 0.02);
}

/** 'supreq': hi-lo, two cycles (urgent). 'ack': two soft rising notes (gentle). */
function chime(kind: 'supreq' | 'ack'): void {
    if (!store.notifySound) return;
    const ctx = context();
    if (!ctx || ctx.state !== 'running') return;   // no gesture yet: stay silent rather than queue
    try {
        if (kind === 'supreq') {
            for (let k = 0; k < 2; k++) {
                tone(ctx, 960, k * 0.5, 0.22, 0.35);
                tone(ctx, 770, k * 0.5 + 0.25, 0.22, 0.35);
            }
        } else {
            tone(ctx, 880, 0, 0.16, 0.2);
            tone(ctx, 1175, 0.18, 0.22, 0.2);
        }
    } catch (e) {
        console.warn('[plugin-crowdcad] notification sound failed', e);
    }
}

function bar(): HTMLElement {
    let el = document.getElementById(ID);
    if (!el) {
        el = document.createElement('div');
        el.id = ID;
        el.setAttribute('style', 'position:fixed;top:0;left:50%;transform:translateX(-50%);z-index:10000;'
            + 'display:flex;flex-direction:column;gap:2px;max-width:min(720px,96vw);pointer-events:none;'
            + 'font:600 14px system-ui,sans-serif;');
        document.body.appendChild(el);
    }
    return el;
}

function row(colour: string, text: string, buttons: [string, () => void][]): HTMLElement {
    const r = document.createElement('div');
    r.setAttribute('style', `pointer-events:auto;display:flex;align-items:center;gap:8px;padding:8px 12px;`
        + `background:${colour};color:#fff;border-radius:0 0 6px 6px;box-shadow:0 2px 8px rgba(0,0,0,.5)`);
    const span = document.createElement('span');
    span.style.flex = '1';
    span.textContent = text;          // textContent: callsigns come from phones, never HTML
    r.appendChild(span);
    for (const [label, onClick] of buttons) {
        const b = document.createElement('button');
        b.textContent = label;
        b.setAttribute('style', 'background:rgba(0,0,0,.3);color:#fff;border:1px solid rgba(255,255,255,.5);'
            + 'border-radius:4px;padding:3px 10px;cursor:pointer;font-weight:700');
        b.onclick = onClick;
        r.appendChild(b);
    }
    return r;
}

function render(): void {
    const now = Date.now();
    acks = acks.filter(a => a.until > now);
    const el = bar();
    el.replaceChildren();
    for (const r of requests) {
        const mins = Math.max(0, Math.round((now - r.at) / 60_000));
        const buttons: [string, () => void][] = [['Dispatch supervisor', () => handlers?.dispatchSupervisor(r)]];
        if (r.lat || r.lon) buttons.push(['Locate', () => handlers?.locate(r.lat, r.lon)]);
        buttons.push(['Clear', () => handlers?.clear(r.id)]);
        el.appendChild(row('#b71c1c', `🚨 ${r.unit} (${r.callsign}) requests a supervisor · ${mins} min ago`, buttons));
    }
    for (const a of acks) {
        const secs = Math.max(0, Math.round((now - a.shownAt) / 1000));
        el.appendChild(row('#1b5e20', `✓ ${a.unit} acknowledged ${a.incident} · ${secs < 60 ? secs + ' s' : '1 min'} ago`, [
            ['Locate', () => locateAck(a)],
            ['Dismiss', () => { acks = acks.filter(x => x !== a); render(); }],
        ]));
    }
    el.style.display = el.childElementCount ? 'flex' : 'none';
}

/** Fly to the unit if the bridge has its position, else to the call. Looked up at click time
 *  so it uses the latest board. */
function locateAck(a: Ack): void {
    const unit = store.units.find(u => u.callsign === a.unit && (u.lat || u.lon));
    if (unit) { handlers?.locate(unit.lat, unit.lon); return; }
    const call = store.incidents.find(i => i.id === a.incident && (i.lat || i.lon));
    if (call) handlers?.locate(call.lat, call.lon);
}

/** enable(): show the bar; locate/clear are the dispatcher's actions. */
export function startNotify(h: Handlers): void {
    handlers = h;
    bar();
    document.addEventListener('pointerdown', unlock, { capture: true });   // R36: unlock audio
    document.addEventListener('keydown', unlock, { capture: true });
    clearInterval(timer);
    timer = setInterval(render, 1_000);    // ages + the green rows' 60 s
    render();
}

/** disable(): take it off the page. */
export function stopNotify(): void {
    clearInterval(timer);
    handlers = null;
    acks = [];
    requests = [];
    knownRequests = null;
    document.removeEventListener('pointerdown', unlock, { capture: true });
    document.removeEventListener('keydown', unlock, { capture: true });
    void audio?.close().catch(() => { /* already closed */ });
    audio = null;
    document.getElementById(ID)?.remove();
}

/** Every board refresh: the open supervisor requests, and acknowledgements not shown yet. */
export function notify(open: SupRequest[], newAcks: Ack[]): void {
    // R36: sound for a request id not seen before (the first board only records what's open).
    const ids = new Set(open.map(r => r.id));
    const known = knownRequests;
    const fresh = known !== null && open.some(r => !known.has(r.id));
    knownRequests = ids;
    requests = open;
    const now = Date.now();
    for (const a of newAcks) acks.push({ ...a, shownAt: now, until: now + ACK_MS });
    // newAcks is already only acknowledgements new since the last poll (lib/bridge.ts skips the first board).
    if (fresh) chime('supreq');
    else if (newAcks.length) chime('ack');
    if (handlers) render();
}
