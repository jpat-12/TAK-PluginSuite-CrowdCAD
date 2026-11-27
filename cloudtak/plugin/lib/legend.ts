// The CrowdCAD legend, floating on CloudTAK's map just above its GPS / user-location panel
// (bottom-left, components/CloudTAK/GPSPanel: left 8px, bottom 8px, --map-gps-panel-size 84px).
// Open by default (Jon, tracker R22); its header collapses it to a small "Legend ▸" pill, and that
// choice is remembered per browser. Mounted by enable(), removed by
// disable(). Plain DOM like notify.ts: it lives outside the drawer, so it's there with the drawer
// closed. Colours come from CloudTAK's Tabler theme variables, so it reads in light and dark.
import { INCIDENT_STATUS, UNIT_STATUS, textOn } from './core.ts';

const ID = 'plugin-crowdcad-legend';
const OPEN_KEY = 'crowdcad-dispatch:legend-open';

function chip(colour: string, text: string, faded = false): string {
    return `<span style="display:inline-block;padding:1px 7px;border-radius:9px;margin:1px 2px;font-weight:700;`
        + `background:${colour};color:${textOn(colour)};${faded ? 'opacity:.45;filter:grayscale(1);' : ''}">${text}</span>`;
}

function body(): string {
    const calls = (['NEW', 'DISP', 'ONSC', 'TRAN'] as const)
        .map(c => chip(INCIDENT_STATUS[c].color, c === 'NEW' ? 'New · no unit sent' : INCIDENT_STATUS[c].label)).join('')
        + chip('#9E9E9E', 'History', true);
    const units = (Object.keys(UNIT_STATUS) as (keyof typeof UNIT_STATUS)[])
        .map(c => chip(UNIT_STATUS[c].color, UNIT_STATUS[c].letter + ' · ' + UNIT_STATUS[c].label)).join('');
    const head = (t: string): string => `<div style="font-size:10px;font-weight:700;letter-spacing:.06em;`
        + `text-transform:uppercase;opacity:.7;margin:6px 0 2px">${t}</div>`;
    return head('Calls') + calls
        + head('Units') + units
        + `<div style="opacity:.8;margin-top:3px">Tasked = assigned, waiting for the medic to acknowledge.</div>`
        + head('Map')
        + `<div><span style="display:inline-block;width:20px;border-top:3px dashed #FFB300;vertical-align:middle"></span>`
        + ` unit → its call · <span style="display:inline-block;width:9px;height:9px;border-radius:50%;`
        + `background:#9E9E9E;opacity:.5;vertical-align:middle"></span> closed call (History)</div>`
        + `<div>Unit icons ALS / BLS / SUP: <b style="color:#43A047">green</b> available, `
        + `<b style="color:#9E9E9E">grey</b> out of service, <b style="color:#EF9A9A">light red</b> busy</div>`
        + `<div>Radar: map shows 160 m around the call; a dashed, hollow unit on the rim is farther out (“far”)</div>`
        + `<div>Call icons: <b style="color:#E03131">P1</b> · <b style="color:#F76707">P2</b> · <b style="color:#FCC419">P3</b></div>`;
}

// Open unless this browser collapsed it ('0'); no saved choice, or storage blocked, = open.
function isOpen(): boolean {
    try { return localStorage.getItem(OPEN_KEY) !== '0'; } catch { return true; }
}

let sessionOpen: boolean | null = null;     // used when storage is blocked: lasts until reload

function toggle(el: HTMLElement): void {
    const next = !(sessionOpen ?? isOpen());
    sessionOpen = next;
    try { localStorage.setItem(OPEN_KEY, next ? '1' : '0'); } catch { /* storage blocked: sessionOpen covers it */ }
    render(el);
}

const SURFACE = 'background:var(--tblr-bg-surface, #1d1d1d);color:var(--tblr-body-color, #eee);';

function render(el: HTMLElement): void {
    const open = sessionOpen ?? isOpen();
    el.replaceChildren();
    if (!open) {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.textContent = 'Legend ▸';
        pill.title = 'Show the CrowdCAD legend';
        pill.setAttribute('aria-expanded', 'false');
        pill.setAttribute('style', 'border:1px solid var(--tblr-border-color, #555);border-radius:12px;padding:3px 10px;'
            + SURFACE + 'font:600 12px system-ui,sans-serif;cursor:pointer;box-shadow:0 1px 4px rgba(0,0,0,.35)');
        pill.onclick = () => toggle(el);
        el.appendChild(pill);
        return;
    }
    const panel = document.createElement('div');
    panel.setAttribute('style', 'padding:6px 10px 8px;border-radius:6px;max-width:330px;' + SURFACE
        + 'border:1px solid var(--tblr-border-color, #444);font:12px/1.45 system-ui,sans-serif;'
        + 'box-shadow:0 2px 10px rgba(0,0,0,.4)');
    // Header row: the title, and a collapse control that shrinks it back to the pill.
    const head = document.createElement('div');
    head.setAttribute('style', 'display:flex;align-items:center;justify-content:space-between;gap:12px');
    const title = document.createElement('span');
    title.textContent = 'CrowdCAD legend';
    title.setAttribute('style', 'font-weight:700');
    const collapse = document.createElement('button');
    collapse.type = 'button';
    collapse.textContent = 'Collapse ▾';
    collapse.title = 'Collapse the legend';
    collapse.setAttribute('aria-expanded', 'true');
    collapse.setAttribute('style', 'border:1px solid var(--tblr-border-color, #555);border-radius:10px;padding:1px 8px;'
        + 'background:transparent;color:inherit;font:600 11px system-ui,sans-serif;cursor:pointer');
    collapse.onclick = () => toggle(el);
    head.append(title, collapse);
    const content = document.createElement('div');
    content.innerHTML = body();     // static markup built here from constants: no outside data
    panel.append(head, content);
    el.appendChild(panel);
}

/** enable(): put the legend on the map, above CloudTAK's GPS panel. */
export function startLegend(): void {
    let el = document.getElementById(ID);
    if (!el) {
        el = document.createElement('div');
        el.id = ID;
        el.setAttribute('style', 'position:fixed;z-index:5;'
            + 'left:calc(8px + env(safe-area-inset-left, 0px));'
            + 'bottom:calc(var(--map-gps-panel-size, 84px) + 16px + env(safe-area-inset-bottom, 0px));');
        document.body.appendChild(el);
    }
    render(el);
}

/** disable(): take it off the map. */
export function stopLegend(): void {
    document.getElementById(ID)?.remove();
}
