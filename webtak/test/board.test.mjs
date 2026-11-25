// node --test webtak/test   (node ≥ 18, no npm packages)
//
// 1. Contract: the Python bridge builds a board from the demo fixture; the WebTAK renderer
//    must render it (catches drift between bridge/board.py and the web client).
// 2. The built bundle boots in a stub WebTAK: registers a Tool + Drawer, or falls back to a
//    launch button when WebTAK's plugin API is missing — and never throws either way.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

import { age, bridgeWarning, escapeHtml, pickEvent } from '../plugin/src/format.js';
import { renderEvent } from '../plugin/src/ui.js';
import { safeDispatchUrl } from '../plugin/src/dispatch-window.js';

const here = dirname(fileURLToPath(import.meta.url));
const repo = join(here, '..', '..');
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');

function bridgeBoard(extra = '') {
    const script = [
        'import json, sys',
        'sys.path.insert(0, "bridge"); sys.path.insert(0, "bridge/tests")',
        'from crowdcad_tak import board, config',
        'from crowdcad_tak.bridge import Publisher',
        'from test_mapping import demo',
        `p = Publisher({**config.DEFAULTS, "team_uids": {"Team 2": "ANDROID-t2"}${extra}}, lambda x: None, lambda: 1794701000000)`,
        'p.apply(demo())',
        'print(json.dumps(board.build(p, 1794701000000, {"crowdcad": "live", "tak": True})))',
    ].join('\n');
    return JSON.parse(execFileSync(python, ['-c', script], { cwd: repo, encoding: 'utf8' }));
}

test('renders the board the Python bridge produces', () => {
    const board = bridgeBoard();
    const event = pickEvent(board, 'nope');
    const html = renderEvent(event, 1794701000000 + 5 * 60000);
    assert.match(html, /Demo Football Game · 3 open calls/);       // incl. the unplaced one
    assert.match(html, /<b>CC-007<\/b> Chest pain/);
    assert.match(html, /wcad-p1/);                                // priority 1 flagged
    assert.match(html, /Sec 104 · 8m · Team 1/);                  // created 1794700800000 = 500 s earlier
    assert.match(html, /no unit/);                                // CC-008 unassigned
    assert.match(html, /Team 2<\/div>[\s\S]*?📡 no reports/);       // device unit, never heard
    assert.match(html, /not on map/);                              // unplaced call CC-009 listed with a chip
    assert.match(html, /<b>CC-009<\/b>/);
    assert.match(html, /not on the map: their location/);
    assert.doesNotMatch(html, /John|Smith|Alex Doe|Pat Quinn/);
    assert.doesNotMatch(html, /data-dispatch/);                   // no CrowdCAD app URL → no Dispatch button
});

test('Dispatch button opens the event in CrowdCAD when the bridge knows the app', () => {
    const board = bridgeBoard(', "crowdcad_app_url": "https://crowdcad.example.org"');
    const event = pickEvent(board, '');
    const html = renderEvent(event, 1794701000000);
    assert.match(html, new RegExp(`data-dispatch="https://crowdcad.example.org/events/${event.id}/dispatch"`));
    assert.match(html, /data-name="Demo Football Game"/);
});

test('only https URLs are ever framed', () => {
    assert.equal(safeDispatchUrl('https://crowdcad.example.org/events/a/dispatch'), 'https://crowdcad.example.org/events/a/dispatch');
    for (const bad of ['javascript:alert(1)', 'http://crowdcad.example.org', 'https://x" onload="alert(1)', null, undefined, 42]) {
        assert.equal(safeDispatchUrl(bad), null, String(bad));
    }
    const html = renderEvent({ name: 'E', calls: [], units: [], unplaced: [], dispatchUrl: 'javascript:alert(1)' }, 0);
    assert.doesNotMatch(html, /data-dispatch/);
});

test('CrowdCAD text is escaped', () => {
    const event = { name: '<img src=x onerror=alert(1)>', calls: [{ id: 'CC-1', status: 'NEW', type: '"><script>', priority: 2,
        location: 'Gate & A', assigned: [], created: 0 }], units: [], unplaced: [] };
    const html = renderEvent(event, 0);
    assert.doesNotMatch(html, /<img|<script/);
    assert.match(html, /Gate &amp; A/);
    assert.equal(escapeHtml(`'"`), '&#39;&quot;');
});

test('helpers', () => {
    assert.equal(age(0, 65 * 60000), '1h05');
    assert.equal(age(10, 0), '0m');                               // skew never goes negative
    assert.equal(bridgeWarning({ crowdcad: 'live', tak: true }), null);
    assert.match(bridgeWarning({ crowdcad: 'down' }), /can’t reach CrowdCAD/);
    assert.equal(pickEvent({ events: [{ id: 'a' }, { id: 'b' }] }, 'b').id, 'b');
    assert.equal(pickEvent(null, ''), null);
});

function stubPage(webtak) {
    const appended = [];
    const element = () => ({ style: {}, classList: { add() {} }, addEventListener() {}, setAttribute() {} });
    const document = {
        readyState: 'complete',
        head: { appendChild: (e) => appended.push(e) },
        body: { appendChild: (e) => appended.push(e) },
        createElement: element,
        getElementById: () => null,
        addEventListener() {},
    };
    const logs = [];
    const window = { WebTAK: webtak };
    const context = { window, document, console: { info: (...a) => logs.push(a.join(' ')), warn: (...a) => logs.push(a.join(' ')) },
        setInterval, clearInterval, fetch: async () => { throw new Error('offline'); } };
    window.document = document;
    return { context, appended, logs };
}

const bundle = execFileSync(python, [join(repo, 'webtak', 'build.py'), '--out', join(here, '..', 'dist', 'test-bundle.js')],
    { encoding: 'utf8' }) && (await import('node:fs')).readFileSync(join(here, '..', 'dist', 'test-bundle.js'), 'utf8');

test('bundle registers a WebTAK tool and drawer', () => {
    const registered = [];
    class Model { constructor(o) { Object.assign(this, o); } }
    const webtak = {
        tool: { models: { Tool: class extends Model {} } },
        drawer: { models: { Drawer: class extends Model { open() {} } } },
        plugin: { models: { Plugin: class extends Model {} }, registerPlugin: (p) => registered.push(p),
            hasPlugin: (id) => registered.some((p) => p.name === id) },
    };
    const page = stubPage(webtak);
    vm.runInNewContext(bundle, page.context);
    assert.equal(registered.length, 1);
    assert.equal(registered[0].name, 'crowdcad-board');
    assert.equal(registered[0].drawers.length, 1);
    assert.equal(registered[0].drawers[0].mount.length, 1);       // 1-arg = WebTAK's plain-DOM mode
    assert.ok(page.logs.some((l) => l.includes('Registered as a WebTAK sidebar tool')));
});

test('bundle falls back to a launch button without WebTAK', () => {
    const page = stubPage(undefined);
    vm.runInNewContext(bundle, page.context);
    assert.ok(page.appended.some((e) => e.className === 'wcad-launch'));
    assert.ok(page.logs.some((l) => l.includes('floating launch button')));
});
