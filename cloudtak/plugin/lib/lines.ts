// Assignment lines on CloudTAK's map: one line from every assigned unit to its call, in the
// unit's status colour (amber en route, red on scene / transporting). Raw MapLibre, like
// map-pick.ts: a view of the board for this dispatcher, not data — nothing is sent to TAK.
// Redrawn after every board refresh (lib/bridge.ts) and re-added when CloudTAK swaps the basemap
// style (which drops custom layers).
import type { GeoJSONSource } from 'maplibre-gl';
import { getPluginApi } from './plugin-api.ts';
import { UNIT_STATUS, hasPosition, type Incident, type Unit } from './core.ts';

const SOURCE = 'plugin-crowdcad-lines';
const LAYER = 'plugin-crowdcad-lines';

type LineFeature = {
    type: 'Feature';
    properties: { color: string };
    geometry: { type: 'LineString'; coordinates: [number, number][] };
};

let current: { type: 'FeatureCollection'; features: LineFeature[] } = { type: 'FeatureCollection', features: [] };
let watching = false;

function ensure(): void {
    const map = getPluginApi()?.map;
    if (!map || !map.isStyleLoaded()) return;
    const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
    if (!source) {
        map.addSource(SOURCE, { type: 'geojson', data: current });
        map.addLayer({
            id: LAYER, type: 'line', source: SOURCE,
            layout: { 'line-cap': 'round', 'line-join': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': 3, 'line-opacity': 0.85, 'line-dasharray': [2, 1.5] },
        });
    } else {
        source.setData(current);
    }
    if (!watching) {
        watching = true;
        map.on('styledata', ensure);   // a basemap change wipes custom layers: put ours back
    }
}

/** Redraw: every assigned unit with a position → its call, if the call has one. */
export function drawLines(incidents: Incident[], units: Unit[]): void {
    const byUid = new Map(units.map(u => [u.uid, u]));
    const features: LineFeature[] = [];
    for (const inc of incidents) {
        if (!hasPosition(inc)) continue;
        for (const uid of inc.assigned) {
            const u = byUid.get(uid);
            if (!u || !hasPosition(u)) continue;
            features.push({
                type: 'Feature',
                properties: { color: UNIT_STATUS[u.status]?.color ?? '#9E9E9E' },
                geometry: { type: 'LineString', coordinates: [[u.lon, u.lat], [inc.lon, inc.lat]] },
            });
        }
    }
    current = { type: 'FeatureCollection', features };
    try { ensure(); } catch (e) { console.warn('[plugin-crowdcad] lines not drawn', e); }
}

/** Plugin disabled: take the lines off the map. */
export function clearLines(): void {
    const map = getPluginApi()?.map;
    current = { type: 'FeatureCollection', features: [] };
    if (!map) return;
    try {
        map.off('styledata', ensure);
        watching = false;
        if (map.getLayer(LAYER)) map.removeLayer(LAYER);
        if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    } catch { /* map already gone */ }
}
