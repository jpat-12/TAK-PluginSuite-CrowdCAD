// Picking a point on CloudTAK's map for a new incident, and pinning it there until created.
// Raw MapLibre on purpose: this is a temporary marker in the dispatcher's own view, not data -
// the incident itself goes out as CoT from the bridge once created.

import { Marker } from 'maplibre-gl';
import { getPluginApi } from './plugin-api.ts';

type OnPick = (lat: number, lon: number) => void;
type ClickEvent = { lngLat: { lat: number; lng: number } };

let pending: ((e: ClickEvent) => void) | null = null;
let pin: Marker | null = null;

/** Wait for one click on the map; cancelPick() stops waiting. */
export function pickPoint(onPick: OnPick): void {
    cancelPick();
    const map = getPluginApi()?.map;
    if (!map) return;
    pending = (e: ClickEvent) => {
        cancelPick();
        onPick(e.lngLat.lat, e.lngLat.lng);
    };
    map.once('click', pending);
    map.getCanvas().style.cursor = 'crosshair';
}

export function cancelPick(): void {
    const map = getPluginApi()?.map;
    if (!map) return;
    if (pending) map.off('click', pending);
    pending = null;
    map.getCanvas().style.cursor = '';
}

/** Show (or move) the pin for the point being entered. */
export function showPin(lat: number, lon: number): void {
    const map = getPluginApi()?.map;
    if (!map) return;
    if (!pin) pin = new Marker({ color: '#E03131' });
    pin.setLngLat([lon, lat]).addTo(map);
}

export function clearPin(): void {
    pin?.remove();
    pin = null;
}
