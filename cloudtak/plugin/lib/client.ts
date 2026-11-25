// Calls to this plugin's server half (api/routes/plugin-crowdcad.ts), which relays them to the
// CrowdCAD bridge with the server-side board token.
//
// Internal reach-in (CloudTAK plugin AGENTS.md §4): `std` is CloudTAK's authenticated fetch;
// the public plugin API has no HTTP client. Same import Aleph's plugin uses — re-verify it on
// every CloudTAK upgrade.
import { std } from '../../../src/std.ts';
import type {
    Board, BridgeInfo, CallDetails, CreatedEvent, DispatchView, NewCall, NewEvent, NewSupervisor, NewTeam,
    TakContact, VenueSummary, W3w,
} from './types.ts';

// The bridge API major this plugin speaks; refuse others instead of showing a wrong board.
export const SUPPORTED_API = 1;

export async function info(): Promise<BridgeInfo> {
    return await std('/api/plugin-crowdcad/info') as BridgeInfo;
}

export async function board(): Promise<Board> {
    return await std('/api/plugin-crowdcad/board') as Board;
}

export async function venues(): Promise<VenueSummary[]> {
    return (await std('/api/plugin-crowdcad/venues') as { venues: VenueSummary[] }).venues;
}

export async function createEvent(event: NewEvent): Promise<CreatedEvent> {
    return await std('/api/plugin-crowdcad/events', { method: 'POST', body: event }) as CreatedEvent;
}

export async function endEvent(id: string): Promise<void> {
    await std(`/api/plugin-crowdcad/events/${encodeURIComponent(id)}/end`, { method: 'POST', body: {} });
}

// The signed-in user's TAK contacts (CloudTAK's own route; TAK Server filters them to the
// user's groups). Each picked one becomes a CrowdCAD unit carried by that device.
export async function contacts(): Promise<TakContact[]> {
    return await std('/api/marti/api/contacts/all') as TakContact[];
}

// --- native dispatch (bridge dispatch.py, compare-and-swap) ----------------------------------

function eventPath(eventId: string): string {
    return `/api/plugin-crowdcad/events/${encodeURIComponent(eventId)}`;
}

export async function dispatchView(eventId: string): Promise<DispatchView> {
    return await std(`${eventPath(eventId)}/dispatch`) as DispatchView;
}

export async function newCall(eventId: string, call: NewCall): Promise<{ callId: string }> {
    return await std(`${eventPath(eventId)}/calls`, { method: 'POST', body: call }) as { callId: string };
}

export async function assignUnit(eventId: string, callId: string, unit: string): Promise<void> {
    await std(`${eventPath(eventId)}/calls/${encodeURIComponent(callId)}/assign`, { method: 'POST', body: { unit } });
}

export async function setStatusOnCall(eventId: string, callId: string, unit: string, status: string,
    extra: { clinicId?: string; transportUnit?: string } = {}): Promise<void> {
    await std(`${eventPath(eventId)}/calls/${encodeURIComponent(callId)}/status`, { method: 'POST', body: { unit, status, ...extra } });
}

export async function setUnitStatus(eventId: string, unit: string, status: string): Promise<void> {
    await std(`${eventPath(eventId)}/units/status`, { method: 'POST', body: { unit, status } });
}

export async function setUnitPost(eventId: string, unit: string, post: string): Promise<void> {
    await std(`${eventPath(eventId)}/units/post`, { method: 'POST', body: { unit, post } });
}

/** Set a call's point (→ its CrowdCAD location) and floor / description / what3words (→ its notes). */
export async function setCallDetails(eventId: string, callId: string, details: CallDetails): Promise<void> {
    await std(`${eventPath(eventId)}/calls/${encodeURIComponent(callId)}/details`, { method: 'POST', body: details });
}

export async function addTeam(eventId: string, team: NewTeam): Promise<void> {
    await std(`${eventPath(eventId)}/teams`, { method: 'POST', body: team });
}

export async function addSupervisor(eventId: string, supervisor: NewSupervisor): Promise<void> {
    await std(`${eventPath(eventId)}/supervisors`, { method: 'POST', body: supervisor });
}

// what3words goes through the bridge: the API key never reaches this page.
export async function w3wFind(words: string): Promise<W3w> {
    return await std('/api/plugin-crowdcad/w3w?words=' + encodeURIComponent(words.trim())) as W3w;
}

export async function w3wAt(lat: number, lon: number): Promise<W3w> {
    return await std(`/api/plugin-crowdcad/w3w?lat=${lat}&lon=${lon}`) as W3w;
}
