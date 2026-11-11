// The bridge's /api/v1/board (docs/API.md). Status codes are IU Event CAD's (docs/COT_FORMAT.md).

export type IncidentStatus = 'NEW' | 'DISP' | 'ONSC' | 'TRAN';
export type UnitStatus = 'AVL' | 'RESP' | 'ONSC' | 'TRAN' | 'OOS';

export interface BoardCall {
    uid: string;
    id: string;
    status: IncidentStatus;
    type: string;
    priority: number;
    location: string;
    reportedBy: string;
    assigned: { uid: string; callsign: string }[];
    lat: number;
    lon: number;
    created: number;
    updated: number;
}

export interface BoardUnit {
    uid: string | null;
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
    calls: BoardCall[];
    units: BoardUnit[];
    unplaced: { kind: string; label: string; location: string }[];
}

export interface Board {
    api: number;
    generated: number;
    bridge: { crowdcad?: string; tak?: boolean; version?: string };
    events: BoardEvent[];
}

export interface BridgeInfo {
    api: number;
    version: string;
    name: string;
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
