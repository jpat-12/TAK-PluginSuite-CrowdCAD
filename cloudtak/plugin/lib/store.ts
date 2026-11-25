import { reactive } from 'vue';
import type { Incident, Unit } from './core.ts';

export interface NewIncidentForm {
    type: string;
    priority: number;
    floor: number;
    source: 'pick' | 'w3w' | 'centre' | 'coords';
    location: string;
    notes: string;
    reportedBy: string;
    coords: string;
    w3wInput: string;            // what the dispatcher typed
    w3w: string;                 // words of the chosen point ('' if unknown)
    w3wPlace: string;            // what3words' nearest place, shown as a sanity check
}

// The bridge's board is the one source of truth; this is only its latest copy plus view
// state. Nothing here is edited locally - every change is a bridge action, then a refresh.
interface CadState {
    incidents: Incident[];
    units: Unit[];
    skewMs: number;              // bridge clock - browser clock, for ages
    conn: { ok: boolean; error: string; at: number };
    view: { screen: 'board' | 'incident' | 'new' | 'add-unit'; incidentId: string | null; filter: string | null };
    form: NewIncidentForm | null;
    w3wCache: Record<string, string>;   // incident id -> words, looked up once
}

export const store = reactive<CadState>({
    incidents: [],
    units: [],
    skewMs: 0,
    conn: { ok: false, error: 'Not connected yet', at: 0 },
    view: { screen: 'board', incidentId: null, filter: null },
    form: null,
    w3wCache: {},
});
