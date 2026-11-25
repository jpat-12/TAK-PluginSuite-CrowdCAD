// Pure display rules for the dispatcher (no Vue, no IO). The bridge owns every rule that changes
// data (CrowdCAD's own dispatch handlers, ported in bridge/crowdcad_tak/dispatch.py); this file
// only shapes what the board says for the screen.
//
// Words follow CrowdCAD's own screen (v1.6.0: Calls, Teams, Supervisors, Add Call, Add Team, En
// Route, On Scene, ...). Status codes are IU Event CAD's (docs/COT_FORMAT.md) and pick the colour
// and letter; the text shown is CrowdCAD's own status whenever the board carries it.
import type { BoardCall, BoardUnit, IncidentStatus, UnitStatus } from './types.ts';

export const STALE_AFTER_MS = 3 * 60_000;    // a device unit not heard for 3 min fades (same as ATAK)
export const WALK_M_PER_S = 1.2;
export const MAX_WALK_ETA_M = 3_000;

export interface StatusDef { label: string; letter: string; color: string }

// Colours match the ATAK plugin and IU Event CAD; labels are CrowdCAD's words for each group.
export const UNIT_STATUS: Record<UnitStatus, StatusDef> = {
    AVL:  { label: 'Available',    letter: 'A', color: '#43A047' },
    RESP: { label: 'En Route',     letter: 'E', color: '#FFB300' },
    ONSC: { label: 'On Scene',     letter: 'S', color: '#E53935' },
    TRAN: { label: 'Transporting', letter: 'T', color: '#E53935' },
    OOS:  { label: 'On Break',     letter: 'B', color: '#9E9E9E' },   // also In Clinic, Detached
};
export const UNKNOWN_STATUS: StatusDef = { label: '—', letter: '?', color: '#616161' };

// CrowdCAD's call statuses for each IU incident status (Pending → Assigned → On Scene → Transporting).
export const CALL_STATUS: Record<IncidentStatus, StatusDef> = {
    NEW:  { label: 'Pending',      letter: 'P', color: '#FFFFFF' },
    DISP: { label: 'Assigned',     letter: 'A', color: '#FFB300' },
    ONSC: { label: 'On Scene',     letter: 'S', color: '#E53935' },
    TRAN: { label: 'Transporting', letter: 'T', color: '#E53935' },
};

// Incident icon disc colour by priority — the same three as the ATAK plugin's IncidentStyler
// (model/Priority.java). CrowdCAD only flags priority, so its calls are P1 (red) or P2 (orange).
export const PRIORITY_COLOR: Record<number, string> = { 1: '#E03131', 2: '#F76707', 3: '#FCC419' };
export function priorityColor(p: number): string {
    return PRIORITY_COLOR[p <= 1 ? 1 : p === 2 ? 2 : 3];
}

export function unitStatus(u: BoardUnit): StatusDef {
    const def = u.status ? UNIT_STATUS[u.status] : UNKNOWN_STATUS;
    return u.crowdcadStatus ? { ...def, label: u.crowdcadStatus } : def;
}

export function callStatus(c: BoardCall): StatusDef {
    const def = c.status ? CALL_STATUS[c.status] : { ...UNKNOWN_STATUS, color: '#FFFFFF' };
    return c.crowdcadStatus ? { ...def, label: c.crowdcadStatus } : def;
}

// Floors: IU Event CAD's rule (1–8, -1 basement, none).
export const FLOOR_BASEMENT = -1;
export const FLOOR_MAX = 8;
export const FLOORS: (number | null)[] = [null, FLOOR_BASEMENT, ...Array.from({ length: FLOOR_MAX }, (_, i) => i + 1)];

export function floorLabel(f: number | null | undefined): string {
    return !f ? '' : f === FLOOR_BASEMENT ? 'Basement' : 'Floor ' + f;
}
export function floorShort(f: number | null | undefined): string {
    return !f ? '—' : f === FLOOR_BASEMENT ? 'B' : 'F' + f;
}

/** "#7": how CrowdCAD numbers a call on its own screen (and on the radio). */
export function callNumber(c: BoardCall): string {
    return c.number ? '#' + c.number : c.id;
}

/** "P1 · Chest pain · Sec 104 · Floor 3". */
export function headline(c: BoardCall): string {
    let s = 'P' + c.priority + ' · ' + (c.type || 'Call');
    if (c.location) s += ' · ' + c.location;
    if (c.floor) s += ' · ' + floorLabel(c.floor);
    return s;
}

/** Warn the dispatcher when the pin isn't a real place yet: get the location by radio. */
export function positionWarning(c: BoardCall): string {
    if (c.placed === false || c.lat === null) return 'Not on the map: set a location (post, map point, what3words or coordinates)';
    if (c.positionFrom === 'estimate') return 'Position is an estimate (map centre)';
    return '';
}

/** Priority first, then the oldest (CrowdCAD's board order). */
export function sortCalls(calls: BoardCall[]): BoardCall[] {
    return calls.slice().sort((a, b) => a.priority - b.priority || (a.created ?? 0) - (b.created ?? 0));
}

export function isStale(u: BoardUnit, now: number): boolean {
    return u.device && (!u.lastHeard || now - u.lastHeard > STALE_AFTER_MS);
}

export function ago(ms: number): string {
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return s + ' s';
    const m = Math.floor(s / 60);
    if (m < 60) return m + ' min';
    const h = Math.floor(m / 60);
    return m % 60 === 0 ? h + ' h' : h + ' h ' + (m % 60) + ' min';
}

export interface Point { lat: number; lon: number }

/** A real fix: ATAK reports 0,0 until the phone has GPS, and that is not a place to send anyone. */
export function hasPosition(p: { lat: number | null; lon: number | null }): p is Point {
    return p.lat !== null && p.lon !== null && Number.isFinite(p.lat) && Number.isFinite(p.lon)
        && !(p.lat === 0 && p.lon === 0);
}

export function meters(a: Point, b: Point): number {
    const r = 6_371_000, rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(h)));
}

export function formatMeters(m: number): string {
    return m < 1000 ? Math.round(m) + ' m' : (m / 1000).toFixed(1) + ' km';
}

/** Initial bearing from a to b, degrees clockwise from true north. */
export function bearing(a: Point, b: Point): number {
    const rad = Math.PI / 180;
    const y = Math.sin((b.lon - a.lon) * rad) * Math.cos(b.lat * rad);
    const x = Math.cos(a.lat * rad) * Math.sin(b.lat * rad)
        - Math.sin(a.lat * rad) * Math.cos(b.lat * rad) * Math.cos((b.lon - a.lon) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export function compass(deg: number): string {
    return COMPASS[Math.round(deg / 45) % 8];
}

/** Where a unit is from the call, for the radar and the rows. */
export interface Relative { meters: number; bearing: number; dir: string; etaSeconds: number; hasWalkEta: boolean }

export function relativeTo(call: { lat: number | null; lon: number | null }, u: { lat: number | null; lon: number | null }): Relative | null {
    if (!hasPosition(call) || !hasPosition(u)) return null;
    const m = meters(call, u);
    const b = bearing(call, u);
    return { meters: m, bearing: b, dir: compass(b), etaSeconds: Math.round(m / WALK_M_PER_S), hasWalkEta: m <= MAX_WALK_ETA_M };
}

/** "180 m NE · ~3 min walk": the unit as seen from the call. */
export function describeRelative(r: Relative | null): string {
    if (!r) return 'no position';
    return formatMeters(r.meters) + ' ' + r.dir + (r.hasWalkEta ? ' · ~' + ago(r.etaSeconds * 1000) + ' walk' : '');
}

export interface RankedUnit extends Relative { unit: BoardUnit }

/** Available units first, then nearest. Units without a position are left out. */
export function rankClosest(call: { lat: number | null; lon: number | null }, units: BoardUnit[]): RankedUnit[] {
    return units
        .map((u) => ({ u, r: relativeTo(call, u) }))
        .filter((x): x is { u: BoardUnit; r: Relative } => x.r !== null)
        .map(({ u, r }) => ({ unit: u, ...r }))
        .sort((a, b) => {
            const av = a.unit.status === 'AVL', bv = b.unit.status === 'AVL';
            return av !== bv ? (av ? -1 : 1) : a.meters - b.meters;
        });
}

/** "lat, lon" typed by a dispatcher → a point, or null. */
export function parseCoords(text: string): Point | null {
    const m = text.match(/^\s*(-?\d{1,2}(?:\.\d+)?)\s*[,\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*$/);
    if (!m) return null;
    const p = { lat: Number(m[1]), lon: Number(m[2]) };
    return Math.abs(p.lat) <= 90 && Math.abs(p.lon) <= 180 && hasPosition(p) ? p : null;
}

/** CrowdCAD's getNextTeamName (addteammodal.tsx): the last team's trailing number + 1. */
export function nextTeamName(existing: string[]): string {
    if (!existing.length) return 'Team 1';
    const last = existing[existing.length - 1].trim();
    const m = last.match(/^(.*?)(\d+)$/);
    return m ? m[1] + (parseInt(m[2], 10) + 1) : last + ' 1';
}
