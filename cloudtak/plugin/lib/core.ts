// Pure display rules for the dispatcher. The bridge owns the incident rules (status,
// assignment, ids); this file only shapes what it serves for the screen.
// Codes and colours match ATAK's UnitStatus / IncidentStatus (ATAK5.6-Eventcad/docs/COT_FORMAT.md).

export const STALE_AFTER_MS = 3 * 60_000;   // same as ATAK UnitBoard.STALE_AFTER_MS
export const WALK_M_PER_S = 1.2;
export const MAX_WALK_ETA_M = 3_000;

export type UnitStatusCode = 'AVL' | 'RESP' | 'ONSC' | 'TRAN' | 'OOS';
export interface UnitStatusDef { label: string; letter: string; color: string }
export const UNIT_STATUS: Record<UnitStatusCode, UnitStatusDef> = {
    AVL:  { label: 'Available',      letter: 'A', color: '#43A047' },
    RESP: { label: 'Responding',     letter: 'R', color: '#FFB300' },
    ONSC: { label: 'On Scene',       letter: 'S', color: '#E53935' },
    TRAN: { label: 'Transporting',   letter: 'T', color: '#E53935' },
    OOS:  { label: 'Out of Service', letter: 'O', color: '#9E9E9E' },
};

export type IncidentStatusCode = 'NEW' | 'DISP' | 'ONSC' | 'TRAN' | 'CLOSED' | 'CXL';
export const INCIDENT_STATUS: Record<IncidentStatusCode, { label: string; color: string }> = {
    // Whole board rows take these colours: red = no unit sent yet.
    NEW:    { label: 'New',          color: '#E53935' },
    DISP:   { label: 'Dispatched',   color: '#FFB300' },
    ONSC:   { label: 'On Scene',     color: '#1E88E5' },
    TRAN:   { label: 'Transporting', color: '#8E24AA' },
    CLOSED: { label: 'Closed',       color: '#9E9E9E' },
    CXL:    { label: 'Cancelled',    color: '#9E9E9E' },
};

// Types offered for a call made here; they become its CrowdCAD chief complaint. Calls made in CrowdCAD come through as sent.
export const TYPES = [
    'Medical', 'Injury / Fall', 'Cardiac', 'Breathing',
    'Heat / Cold', 'Intoxication', 'Behavioral', 'Other',
];
export const FLOOR_NONE = 0;
export const FLOOR_BASEMENT = -1;
export const FLOOR_MAX = 8;

/** An open call as the bridge serves it (GET /api/plugin-crowdcad/dispatcher/board). */
export interface Incident {
    id: string;                  // CC-007: the call's CrowdCAD number with the event's prefix
    cadId: string;               // CrowdCAD's own call id
    status: IncidentStatusCode;
    type: string; typeAbbrv: string; medical: boolean;
    priority: number;
    location: string; floor: number; eventTitle: string; notes: string;
    w3w: string;                 // what3words when the incident carries one (walk-ups)
    lat: number; lon: number;
    positionFrom: string;        // geocode | table | table (estimated) | section | facility | dispatch
    created: number; updated: number;
    assigned: string[];          // unit UIDs
}

/** A unit the bridge has heard on its position report. Times are the bridge's clock. */
export interface Unit {
    uid: string; callsign: string;
    status: UnitStatusCode; incident: string;
    since: number; lat: number; lon: number; seen: number;   // seen 0 = never heard
    device?: boolean;            // carried by a phone (position + seen come from its reports)
}

export interface Board { now: number; incidents: Incident[]; units: Unit[] }

/** Black or white text, whichever reads on this background colour. */
export function textOn(hex: string): string {
    const n = parseInt(hex.replace('#', ''), 16);
    const r = (n >> 16) & 255, g = (n >> 8) & 255, b = n & 255;
    return (0.299 * r + 0.587 * g + 0.114 * b) > 150 ? '#000' : '#fff';
}

export function floorLabel(f: number): string {
    return f === FLOOR_NONE ? '' : f === FLOOR_BASEMENT ? 'Basement' : 'Floor ' + f;
}
export function floorShort(f: number): string {
    return f === FLOOR_NONE ? '—' : f === FLOOR_BASEMENT ? 'B' : 'F' + f;
}

/** "CC-007" → "007": what gets said on the radio. */
export function shortForm(id: string): string {
    const dash = id.lastIndexOf('-');
    return dash > 0 ? id.slice(dash + 1) : id;
}

export function headline(i: Incident): string {
    let s = 'P' + i.priority + ' · ' + i.type;
    if (i.location) s += ' · ' + i.location;
    if (i.floor !== FLOOR_NONE) s += ' · ' + floorLabel(i.floor);
    return s;
}

/** True when the pin is only a venue centre or an estimate: get the location by radio. */
export function positionWarning(i: Incident): string {
    if (i.positionFrom === 'facility') return 'Location unknown: pin is the venue centre only';
    if (i.positionFrom === 'table (estimated)' || i.positionFrom === 'section') return 'Position is an estimate';
    return '';
}

/** Most urgent first, then newest (same order as ATAK's board). */
export function sortOpen(incidents: Incident[]): Incident[] {
    return incidents.slice().sort((a, b) => a.priority - b.priority || b.created - a.created);
}

export function meters(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const r = 6_371_000, rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
    return 2 * r * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function formatMeters(m: number): string {
    return m < 1000 ? Math.round(m) + ' m' : (m / 1000).toFixed(1) + ' km';
}

export function ago(ms: number): string {
    const s = Math.max(0, Math.floor(ms / 1000));
    if (s < 60) return s + ' s';
    const m = Math.floor(s / 60);
    if (m < 60) return m + ' min';
    const h = Math.floor(m / 60);
    return m % 60 === 0 ? h + ' h' : h + ' h ' + (m % 60) + ' min';
}

/** A real fix: ATAK reports 0,0 until the phone has GPS, and that is not a place to send anyone. */
export function hasPosition(p: { lat: number; lon: number }): boolean {
    return Number.isFinite(p.lat) && Number.isFinite(p.lon) && !(p.lat === 0 && p.lon === 0);
}

/** Initial bearing from 1 to 2, degrees clockwise from true north. */
export function bearing(lat1: number, lon1: number, lat2: number, lon2: number): number {
    const rad = Math.PI / 180;
    const y = Math.sin((lon2 - lon1) * rad) * Math.cos(lat2 * rad);
    const x = Math.cos(lat1 * rad) * Math.sin(lat2 * rad)
        - Math.sin(lat1 * rad) * Math.cos(lat2 * rad) * Math.cos((lon2 - lon1) * rad);
    return (Math.atan2(y, x) / rad + 360) % 360;
}

const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export function compass(deg: number): string {
    return COMPASS[Math.round(deg / 45) % 8];
}

/** Where a unit is from the incident, for the radar and the rows. */
export interface Relative { meters: number; bearing: number; dir: string; etaSeconds: number; hasWalkEta: boolean }

export function relativeTo(inc: { lat: number; lon: number }, u: { lat: number; lon: number }): Relative | null {
    if (!hasPosition(inc) || !hasPosition(u)) return null;
    const m = meters(inc.lat, inc.lon, u.lat, u.lon);
    const b = bearing(inc.lat, inc.lon, u.lat, u.lon);
    return { meters: m, bearing: b, dir: compass(b), etaSeconds: Math.round(m / WALK_M_PER_S), hasWalkEta: m <= MAX_WALK_ETA_M };
}

/** "180 m NE · ~3 min walk": the unit as seen from the incident. */
export function describeRelative(r: Relative | null): string {
    if (!r) return 'no position';
    return formatMeters(r.meters) + ' ' + r.dir + (r.hasWalkEta ? ' · ~' + ago(r.etaSeconds * 1000) + ' walk' : '');
}

export interface RankedUnit extends Relative { unit: Unit }

/** Available units first, then nearest. Units without a position are left out. */
export function rankClosest(inc: { lat: number; lon: number }, units: Unit[]): RankedUnit[] {
    return units
        .map(u => ({ u, r: relativeTo(inc, u) }))
        .filter((x): x is { u: Unit; r: Relative } => x.r !== null)
        .map(({ u, r }) => ({ unit: u, ...r }))
        .sort((a, b) => {
            const av = a.unit.status === 'AVL', bv = b.unit.status === 'AVL';
            return av !== bv ? (av ? -1 : 1) : a.meters - b.meters;
        });
}
