// The bridge is the one source of truth; this is only its latest copy plus view state. Nothing
// here is edited locally: every change is a bridge action (lib/client.ts), then a refresh.
//
//   board     GET /board (board token): calls, teams, positions, CrowdCAD status text — everyone
//   dispatch  GET /events/:id/dispatch (manage token): posts, clinics, allowed statuses, whether
//             the bridge may write this event, what3words — only when this CloudTAK can dispatch
import { reactive } from 'vue';
import * as crowdcad from './client.ts';
import type { Board, BoardEvent, DispatchView } from './types.ts';

export type Screen = 'board' | 'call' | 'add-call' | 'add-team' | 'add-supervisor';

interface DispatchState {
    board: Board | null;
    dispatch: DispatchView | null;
    manage: boolean;              // this CloudTAK holds the bridge's manage token (can dispatch)
    error: string | null;         // loading failed (the last good board stays shown under it)
    actionError: string | null;   // a refused action: stays until dismissed or the next action
    now: number;                  // browser clock, refreshed with each poll
    eventId: string;
    view: { screen: Screen; callUid: string | null; filter: string | null };
}

export const store = reactive<DispatchState>({
    board: null,
    dispatch: null,
    manage: false,
    error: null,
    actionError: null,
    now: Date.now(),
    eventId: '',
    view: { screen: 'board', callUid: null, filter: null },
});

const POLL_MS = 4_000;
const DISPATCH_EVERY = 3;          // the dispatch view changes slowly: every 3rd board poll

let keepUntil = 0;

/** Show this event, even if the bridge only lists it on a later poll (a just-created event). */
export function selectEvent(id: string): void {
    store.eventId = id;
    store.view = { screen: 'board', callUid: null, filter: null };
    keepUntil = Date.now() + 15_000;
}

export function currentEvent(): BoardEvent | null {
    const events = store.board?.events ?? [];
    return events.find((e) => e.id === store.eventId) ?? events[0] ?? null;
}

function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

export async function refresh(withDispatch = true): Promise<void> {
    try {
        store.board = await crowdcad.board();
        store.error = null;
    } catch (err) {
        store.error = errorText(err);
    }
    store.now = Date.now();
    const events = store.board?.events ?? [];
    // Keep the picker on a real choice (a blank select hides which event the board is for) —
    // except just after New event, while the bridge hasn't seen the new event yet.
    if (events.length && !events.some((e) => e.id === store.eventId) && Date.now() > keepUntil) store.eventId = events[0].id;
    const event = currentEvent();
    if (!store.manage || !event) return;
    if (!withDispatch && store.dispatch?.id === event.id) return;   // another event picked: fetch now
    try {
        store.dispatch = await crowdcad.dispatchView(event.id);
    } catch (err) {
        store.dispatch = null;
        console.warn('[plugin-crowdcad] dispatch view failed', err);
    }
}

/** One action at a time; the bridge's answer (or its refusal) is what the dispatcher sees. */
export async function act(fn: () => Promise<unknown>): Promise<boolean> {
    store.actionError = null;
    try {
        await fn();
        return true;
    } catch (err) {
        store.actionError = errorText(err);
        return false;
    } finally {
        await refresh();
    }
}

let timer: ReturnType<typeof setTimeout> | undefined;
let running = false;

/** One poll loop for the whole plugin (not per component): started by the panel, stopped on leave. */
export async function start(): Promise<void> {
    if (running) return;
    running = true;
    try {
        const info = await crowdcad.info();
        store.manage = Boolean(info.manage);
        if (Math.floor(info.api) !== crowdcad.SUPPORTED_API) {
            store.error = `The CrowdCAD bridge speaks API v${info.api}; this plugin needs v${crowdcad.SUPPORTED_API}. Update one of them.`;
            running = false;
            return;
        }
    } catch (err) {
        store.error = errorText(err);
    }
    let n = 0;
    const loop = async (): Promise<void> => {
        if (!running) return;
        await refresh(n++ % DISPATCH_EVERY === 0);
        timer = setTimeout(() => void loop(), POLL_MS);
    };
    await loop();
}

export function stop(): void {
    running = false;
    clearTimeout(timer);
}
