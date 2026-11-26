// Drawing a venue boundary on CloudTAK's map: each click adds a corner, shown as a cyan outline
// while drawing. The finished polygons are saved on the bridge (shared by every dispatcher of the
// event) and drawn on the radar and the map. Raw MapLibre, like map-pick.ts.
import type { GeoJSONSource } from 'maplibre-gl';
import { getPluginApi } from './plugin-api.ts';

const SOURCE = 'plugin-crowdcad-draw';
type ClickEvent = { lngLat: { lat: number; lng: number } };

let points: [number, number][] = [];       // [lat, lon]
let onClick: ((e: ClickEvent) => void) | null = null;
let changed: (count: number) => void = () => {};

function render(): void {
    const map = getPluginApi()?.map;
    if (!map || !map.isStyleLoaded()) return;
    const ring = points.length >= 3 ? [...points, points[0]] : points;
    const data = {
        type: 'FeatureCollection' as const,
        features: [
            ...(ring.length >= 2 ? [{ type: 'Feature' as const, properties: {},
                geometry: { type: 'LineString' as const, coordinates: ring.map(([lat, lon]) => [lon, lat]) } }] : []),
            ...points.map(([lat, lon]) => ({ type: 'Feature' as const, properties: {},
                geometry: { type: 'Point' as const, coordinates: [lon, lat] } })),
        ],
    };
    const source = map.getSource(SOURCE) as GeoJSONSource | undefined;
    if (source) {
        source.setData(data as never);
        return;
    }
    map.addSource(SOURCE, { type: 'geojson', data: data as never });
    map.addLayer({ id: SOURCE + '-line', type: 'line', source: SOURCE, filter: ['==', '$type', 'LineString'],
        paint: { 'line-color': '#00E5FF', 'line-width': 2 } });
    map.addLayer({ id: SOURCE + '-pts', type: 'circle', source: SOURCE, filter: ['==', '$type', 'Point'],
        paint: { 'circle-radius': 4, 'circle-color': '#00E5FF' } });
}

/** Start drawing: every map click adds a corner. onChange gets the corner count. */
export function startDrawing(onChange: (count: number) => void): void {
    cancelDrawing();
    const map = getPluginApi()?.map;
    if (!map) return;
    changed = onChange;
    onClick = (e: ClickEvent) => {
        points.push([e.lngLat.lat, e.lngLat.lng]);
        render();
        changed(points.length);
    };
    map.on('click', onClick);
    map.getCanvas().style.cursor = 'crosshair';
}

export function undoPoint(): void {
    points.pop();
    render();
    changed(points.length);
}

/** The finished polygon ([lat, lon] corners), or null if it has fewer than 3. Stops drawing. */
export function finishDrawing(): [number, number][] | null {
    const done = points.length >= 3 ? points.slice() : null;
    cancelDrawing();
    return done;
}

export function cancelDrawing(): void {
    const map = getPluginApi()?.map;
    points = [];
    if (!map) return;
    try {
        if (onClick) map.off('click', onClick);
        map.getCanvas().style.cursor = '';
        if (map.getLayer(SOURCE + '-line')) map.removeLayer(SOURCE + '-line');
        if (map.getLayer(SOURCE + '-pts')) map.removeLayer(SOURCE + '-pts');
        if (map.getSource(SOURCE)) map.removeSource(SOURCE);
    } catch { /* map gone */ }
    onClick = null;
}
