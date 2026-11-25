// A call's location as the dispatcher enters it, and what that becomes in CrowdCAD:
//
//   a post                → CrowdCAD `location` = the post name (CrowdCAD places it itself)
//   a point (map click, what3words, coordinates, map centre)
//                         → CrowdCAD `location` = "lat, lon" (the bridge sets it; mapping.py
//                           places any call whose location is a coordinate pair)
//   description, floor, what3words
//                         → one "[TAK] …" line in the call's CrowdCAD notes, plus the bridge's
//                           own copy, which is what TAK maps and boards show
import { parseCoords, type Point } from './core.ts';
import type { CallDetails, PointSource } from './types.ts';

export interface LocationDraft {
    source: PointSource;
    post: string;
    description: string;
    floor: number | null;
    point: Point | null;      // the chosen point (map / what3words / coordinates)
    coords: string;           // what the dispatcher typed for 'coords'
    w3wInput: string;         // what the dispatcher typed for 'w3w'
    w3w: string;              // words of the chosen point ('' unknown)
    w3wPlace: string;         // what3words' nearest place, a sanity check
}

export const SOURCES: [PointSource, string][] = [
    ['post', 'Post'], ['map', 'Click on map'], ['w3w', 'what3words'], ['coords', 'Coordinates'], ['centre', 'Map centre'],
];

export function emptyDraft(source: PointSource = 'post'): LocationDraft {
    return { source, post: '', description: '', floor: null, point: null, coords: '', w3wInput: '', w3w: '', w3wPlace: '' };
}

/** The draft for an existing call, from its board entry and the bridge's stored details. */
export function draftFor(callLocation: string, details: Partial<CallDetails> | undefined, isPost: boolean): LocationDraft {
    const d = emptyDraft(isPost ? 'post' : (details?.source && details.source !== 'post' ? details.source : 'map'));
    d.post = isPost ? callLocation : '';
    d.description = details?.description ?? '';
    d.floor = details?.floor ?? null;
    d.w3w = details?.w3w ?? '';
    if (details?.lat != null && details?.lon != null) d.point = { lat: details.lat, lon: details.lon };
    else {
        const p = parseCoords(callLocation);
        if (p) d.point = p;
    }
    if (d.point) d.coords = d.point.lat.toFixed(5) + ', ' + d.point.lon.toFixed(5);
    return d;
}

/**
 * → what to send: `location` (a post or a place name for CrowdCAD's own field; the bridge
 * replaces it with "lat, lon" when `details` carries a point) and `details`, or an error to show.
 * `centre` is read at submit time, so the dispatcher can pan until the last moment.
 */
export function toPayload(d: LocationDraft, centre: Point | null): { location: string; details: CallDetails } | { error: string } {
    const base = {
        description: d.description.trim() || null,
        floor: d.floor,
        w3w: null as string | null,
    };
    if (d.source === 'post') {
        const post = d.post.trim();
        if (!post && !base.description) return { error: 'Pick a post, or describe the spot.' };
        return { location: post, details: { ...base, post: post || null, lat: null, lon: null, source: post ? 'post' : null } };
    }
    let point = d.point;
    if (d.source === 'centre') point = centre;
    if (d.source === 'coords') point = parseCoords(d.coords);
    if (!point) {
        return { error: d.source === 'map' ? 'Click the map where the call is first.'
            : d.source === 'w3w' ? 'Find the three words first.'
                : d.source === 'coords' ? 'Enter coordinates as "lat, lon", e.g. 39.18085, -86.52540'
                    : 'Could not read the map centre.' };
    }
    return {
        location: '',
        details: { ...base, w3w: d.source === 'centre' ? null : (d.w3w || null), lat: point.lat, lon: point.lon, source: d.source },
    };
}
