// Client for the CrowdCAD bridge's dispatcher API (bridge/crowdcad_tak/dispatcher.py), which
// serves exactly the board and actions IU Event CAD's bridge served this panel, backed by
// CrowdCAD: every action is CrowdCAD's own dispatch handler, written compare-and-swap.
//
// Calls go through this plugin's CloudTAK server half (server/plugin-crowdcad.ts), which adds
// the bridge's manage token server-side: no address or token is ever typed into, or stored in,
// the browser. Incidents still show on CloudTAK's map as ordinary CoT markers from TAK Server.
//
// Internal reach-in (CloudTAK plugin AGENTS.md §4): `std` is CloudTAK's authenticated fetch; the
// public plugin API has no HTTP client. Re-verify the import on every CloudTAK upgrade.

import { std } from '../../../src/std.ts';
import { store } from './store.ts';
import { clearLines, drawLines } from './lines.ts';
import type { Board } from './core.ts';

const POLL_MS = 3_000;
const BASE = '/api/plugin-crowdcad';

function message(e: unknown): string {
    return e instanceof Error ? e.message : String(e);
}

export async function refresh(): Promise<void> {
    try {
        const b = await std(BASE + '/dispatcher/board') as Board;
        store.incidents.splice(0, store.incidents.length, ...b.incidents);
        store.units.splice(0, store.units.length, ...b.units);
        drawLines(store.incidents, store.units);
        store.skewMs = b.now - Date.now();
        store.conn = { ok: true, error: '', at: Date.now() };
    } catch (e) {
        store.conn = { ok: false, error: message(e), at: store.conn.at };
        console.warn('[plugin-crowdcad] board refresh failed', e);
    }
}

export type Action =
    | { action: 'assign' | 'unassign'; id: string; unitUid: string }
    | { action: 'status'; id: string; status: 'DISP' | 'ONSC' | 'TRAN' | 'CLOSED' | 'CXL' }
    | { action: 'create'; incident: { type: string; priority: number; location: string; floor: number;
        notes: string; reportedBy: string; lat: number; lon: number; w3w: string } }
    | { action: 'add_unit'; unit: { name: string; kind: 'team' | 'supervisor'; cert?: string; takUid?: string } }
    | { action: 'remove_unit'; unitUid: string }
    | { action: 'unit_status'; id: string; unitUid: string; status: 'AVL' | 'RESP' | 'ONSC' | 'TRAN' | 'OOS' };

/** Send one action; the bridge writes it to CrowdCAD and re-sends the call as CoT. Throws with its message. */
export async function act(a: Action): Promise<string> {
    const r = await std(BASE + '/dispatcher/action', { method: 'POST', body: a }) as { id: string };
    await refresh();
    return r.id;
}

export interface TakContact { uid: string; callsign: string }

/** The signed-in user's TAK contacts (CloudTAK's own route): a new unit can be carried by one. */
export async function contacts(): Promise<TakContact[]> {
    const list = await std('/api/marti/api/contacts/all') as TakContact[];
    return list.filter(c => c.uid && c.callsign).sort((a, b) => a.callsign.localeCompare(b.callsign));
}

export interface W3w { words: string; lat: number; lon: number; nearestPlace: string }

// what3words goes through the bridge: the API key stays on the server, never in this page.
export async function w3wFind(words: string): Promise<W3w> {
    return await std(BASE + '/w3w?words=' + encodeURIComponent(words.trim())) as W3w;
}

export async function w3wAt(lat: number, lon: number): Promise<W3w> {
    return await std(BASE + '/w3w?lat=' + lat + '&lon=' + lon) as W3w;
}

let timer: ReturnType<typeof setTimeout> | undefined;
let running = false;

// One poll loop for the whole plugin (not per component), started in enable().
export function startPolling(): void {
    if (running) return;
    running = true;
    const loop = async (): Promise<void> => {
        if (!running) return;
        await refresh();
        timer = setTimeout(loop, POLL_MS);
    };
    void loop();
}

export function stopPolling(): void {
    running = false;
    clearTimeout(timer);
    clearLines();
}
