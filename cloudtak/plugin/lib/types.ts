// The bridge's /api/v1/board (docs/API.md). Status codes are IU Event CAD's (docs/COT_FORMAT.md).

export type IncidentStatus = 'NEW' | 'DISP' | 'ONSC' | 'TRAN';
export type UnitStatus = 'AVL' | 'RESP' | 'ONSC' | 'TRAN' | 'OOS';

export interface BoardCall {
    uid: string | null;
    /** false: CrowdCAD can't place it (not a post on a mapped layer); listed, never on the map. */
    placed?: boolean;
    id: string;
    status: IncidentStatus;
    type: string;
    priority: number;
    location: string;
    reportedBy: string;
    assigned: { uid: string | null; callsign: string }[];
    lat: number | null;
    lon: number | null;
    created: number | null;
    updated: number | null;
}

export interface BoardUnit {
    uid: string | null;
    placed?: boolean;
    /** Device units: ms the bridge last received anything from that device (null = never). */
    lastHeard?: number | null;
    callsign: string;
    status: UnitStatus | null;
    incident: string | null;
    location: string | null;
    supervisor: boolean;
    device: boolean;
    lat: number | null;
    lon: number | null;
    since: number | null;
}

export interface BoardEvent {
    id: string;
    name: string;
    date?: string | null;
    calls: BoardCall[];
    units: BoardUnit[];
    unplaced: { kind: string; label: string; location: string }[];
    /** CrowdCAD's own dispatch screen for this event; null when the bridge doesn't know the app URL. */
    dispatchUrl?: string | null;
    /** Created from TAK (owned by the bridge account), so it can be ended from here. */
    endable?: boolean;
}

export interface Board {
    api: number;
    generated: number;
    bridge: { crowdcad?: string; tak?: boolean; version?: string };
    /** The CrowdCAD web app, or null when not configured. */
    crowdcadUrl?: string | null;
    events: BoardEvent[];
}

export interface BridgeInfo {
    api: number;
    version: string;
    name: string;
    /** This CloudTAK server holds the bridge's manage token: show New event / End event. */
    manage?: boolean;
}

export interface VenueSummary {
    id: string;
    name: string;
    posts: number;
    clinics: number;
    /** Some layer is georeferenced (GeoJSON import): calls at its posts land on the TAK map. */
    mapped: boolean;
}

/** One TAK contact picked in the New event form → one CrowdCAD team or supervisor. */
export interface NewUnit {
    name: string;
    kind: 'team' | 'supervisor';
    uid: string;
    callsign: string;
}

export interface NewEvent {
    name: string;
    date: string;            // YYYY-MM-DD
    venueId: string;
    units: NewUnit[];
}

export interface CreatedEvent {
    id: string;
    name: string;
    dispatchUrl: string | null;
}

/** CloudTAK's /api/marti/api/contacts/all entry (fields this plugin uses). */
export interface TakContact {
    uid: string;
    callsign: string;
    team?: string;
    role?: string;
}

export const INCIDENT_LABEL: Record<IncidentStatus, string> = {
    NEW: 'New', DISP: 'Dispatched', ONSC: 'On scene', TRAN: 'Transporting',
};
export const UNIT_LABEL: Record<UnitStatus, string> = {
    AVL: 'Available', RESP: 'Responding', ONSC: 'On scene', TRAN: 'Transporting', OOS: 'Out of service',
};
// Tabler's light badge classes, same meaning on every client: red = needs a unit.
export const INCIDENT_BADGE: Record<IncidentStatus, string> = {
    NEW: 'bg-red-lt', DISP: 'bg-orange-lt', ONSC: 'bg-yellow-lt', TRAN: 'bg-blue-lt',
};
export const UNIT_BADGE: Record<UnitStatus, string> = {
    AVL: 'bg-green-lt', RESP: 'bg-orange-lt', ONSC: 'bg-yellow-lt', TRAN: 'bg-blue-lt', OOS: 'bg-secondary-lt',
};

/** GET /api/plugin-crowdcad/events/:id/dispatch — CrowdCAD's own names for native dispatch. */
export interface DispatchUnit {
    name: string;
    kind: 'team' | 'supervisor';
    status: string | null;
    location: string | null;
    device: string | null;
    lat: number | null;
    lon: number | null;
}

export interface DispatchCall {
    id: string;
    number: number | null;
    status: string;
    location: string;
    chiefComplaint: string;
    priority: boolean;
    assigned: string[];
    lat: number | null;
    lon: number | null;
}

export interface DispatchView {
    id: string;
    name: string;
    ended: boolean;
    /** The bridge may write this event (owner, org event, or shared with it). */
    canDispatch: boolean;
    whyNot: string | null;
    units: DispatchUnit[];
    calls: DispatchCall[];
    posts: { name: string; lat: number | null; lon: number | null }[];
    clinics: { id: string; name: string }[];
    statuses: { onCall: string[]; availability: string[] };
}

export interface NewCall {
    location: string;
    chiefComplaint: string;
    priority: boolean;
    assign?: string;
}
