// Picking a point on CloudTAK's map for a call's location, and pinning it there until saved.
// Raw MapLibre on purpose: this is a temporary marker in the dispatcher's own view, not data —
// the call itself reaches every map as CoT from the bridge once saved.
import { Marker } from 'maplibre-gl';
import { pluginApi } from './plugin-api.ts';

type OnPick = (lat: number, lon: number) => void;
type ClickEvent = { lngLat: { lat: number; lng: number } };

let pending: ((e: ClickEvent) => void) | null = null;
let pin: Marker | null = null;

/** Wait for one click on the map; cancelPick() stops waiting. */
export function pickPoint(onPick: OnPick): void {
    cancelPick();
    const map = pluginApi().map;
    pending = (e: ClickEvent) => {
        cancelPick();
        onPick(e.lngLat.lat, e.lngLat.lng);
    };
    map.once('click', pending);
    map.getCanvas().style.cursor = 'crosshair';
}

export function cancelPick(): void {
    try {
        const map = pluginApi().map;
        if (pending) map.off('click', pending);
        map.getCanvas().style.cursor = '';
    } catch { /* map not loaded: nothing to cancel */ }
    pending = null;
}

/** Show (or move) the pin for the point being entered. */
export function showPin(lat: number, lon: number): void {
    if (!pin) pin = new Marker({ color: '#F76707' });
    pin.setLngLat([lon, lat]).addTo(pluginApi().map);
}

export function clearPin(): void {
    pin?.remove();
    pin = null;
}

export function mapCentre(): { lat: number; lon: number } | null {
    try {
        const c = pluginApi().map.getCenter();
        return { lat: c.lat, lon: c.lng };
    } catch {
        return null;   // map not ready
    }
}

/** Zoom in to street level, but never zoom out a dispatcher who is already closer. */
export function flyTo(lat: number | null, lon: number | null): void {
    if (lat === null || lon === null) return;
    try {
        const map = pluginApi().map;
        map.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 17) });
    } catch { /* map not ready */ }
}

/** The call and every unit with a fix in one view. */
export function fitPoints(points: { lat: number; lon: number }[]): void {
    if (!points.length) return;
    const lons = points.map((p) => p.lon), lats = points.map((p) => p.lat);
    try {
        pluginApi().map.fitBounds(
            [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
            { padding: 80, maxZoom: 18 },
        );
    } catch { /* map not ready */ }
}
