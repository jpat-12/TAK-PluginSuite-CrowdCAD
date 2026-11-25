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
    /** How good the point is: a CrowdCAD post, a point a dispatcher placed, or the map centre. */
    positionFrom?: 'post' | 'coords' | 'estimate' | null;
    created: number | null;
    updated: number | null;
    /** CrowdCAD's own call id (dispatch actions) and its #number. */
    callId?: string | null;
    number?: number | null;
    /** CrowdCAD's call status text ("Pending", "Assigned", "En Route", ...). */
    crowdcadStatus?: string | null;
    /** TAK details (bridge calldetails.py): 1–8, -1 basement, null none. */
    floor?: number | null;
    w3w?: string | null;
    description?: string | null;
    /** The call's CrowdCAD `location` field as stored (a post, a place, or "lat, lon"). */
    callLocation?: string | null;
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
    /** CrowdCAD's own status text ("Available", "En Route", "On Break", ...). */
    crowdcadStatus?: string | null;
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
    /** TAK details from the bridge's store (never read back out of CrowdCAD's notes). */
    details?: Partial<CallDetails>;
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
    /** The bridge has a what3words key: offer ///word lookups. */
    w3w?: boolean;
}

export type PointSource = 'map' | 'w3w' | 'coords' | 'centre' | 'post';

/** A call's TAK details. The point becomes the call's CrowdCAD location ("lat, lon"); the rest
 *  goes into one "[TAK] …" line of its notes (bridge calldetails.py). */
export interface CallDetails {
    /** A CrowdCAD post: becomes the call's location as-is (instead of a point). */
    post?: string | null;
    lat: number | null;
    lon: number | null;
    source: PointSource | null;
    description: string | null;
    floor: number | null;
    w3w: string | null;
}

/** CrowdCAD's Add Call. */
export interface NewCall {
    location: string;
    chiefComplaint: string;
    priority: boolean;
    source?: string;
    assign?: string;
    details?: CallDetails;
}

/** CrowdCAD's Add Team (members "Name [Cert] (Lead)"), optionally carried by a TAK contact. */
export interface NewTeam {
    name: string;
    members: { name: string; cert: string; lead: boolean }[];
    takUid?: string;
}

/** CrowdCAD's Add Supervisor. */
export interface NewSupervisor {
    callSign: string;
    cert: string;
    name?: string;
    takUid?: string;
}

export interface W3w { words: string; lat: number; lon: number; nearestPlace: string }
