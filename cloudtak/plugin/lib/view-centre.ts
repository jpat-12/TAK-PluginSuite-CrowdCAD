// The centre of the part of CloudTAK's map the dispatcher can actually see. With the plugin's
// drawer open, the map's own centre sits under the drawer; the crosshair (App.vue) and "Map
// centre" for a new call use this point instead. Recalculated whenever the drawer opens, closes or
// is resized, and when the window or map resizes.
import { getPluginApi } from './plugin-api.ts';

export interface ScreenPoint { x: number; y: number }

/** Screen (client) coordinates of the visible map's centre, beside `panel`; null if no map. */
export function visibleCentre(panel: HTMLElement | null): ScreenPoint | null {
    let canvas: DOMRect;
    try {
        const c = getPluginApi()?.map.getCanvas();
        if (!c) return null;
        canvas = c.getBoundingClientRect();
    } catch {
        return null;
    }
    let left = canvas.left, right = canvas.right;
    const box = panel?.getBoundingClientRect();
    if (box && box.width > 0 && box.right > canvas.left && box.left < canvas.right) {
        // The drawer covers part of the map: the wider uncovered side is what the dispatcher sees.
        const leftSpace = box.left - canvas.left, rightSpace = canvas.right - box.right;
        if (leftSpace >= rightSpace) right = box.left;
        else left = box.right;
    }
    return { x: (left + right) / 2, y: canvas.top + canvas.height / 2 };
}

/** The map position under that point. */
export function visibleCentreLatLon(panel: HTMLElement | null): { lat: number; lon: number } | null {
    const p = visibleCentre(panel);
    if (!p) return null;
    try {
        const map = getPluginApi()?.map;
        if (!map) return null;
        const canvas = map.getCanvas().getBoundingClientRect();
        const ll = map.unproject([p.x - canvas.left, p.y - canvas.top]);
        return { lat: ll.lat, lon: ll.lng };
    } catch {
        return null;
    }
}
