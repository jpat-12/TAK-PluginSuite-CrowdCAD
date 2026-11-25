// The EMS incident icon, its white disc tinted by priority — the same picture ATAK plugin users
// see on their map (atak/…/IncidentStyler.java): MULTIPLY turns the white disc into the colour
// and leaves the black ring and star dark; the icon's own alpha keeps the corners clear.
import { reactive } from 'vue';
import { INCIDENT_ICON_PNG, INCIDENT_ICON_SIZE } from './incident-icon-data.ts';
import { priorityColor } from './core.ts';

// colour → tinted data URL. Reactive so <IncidentIcon> re-renders once the image has loaded.
const tinted = reactive<Record<string, string>>({});
let source: HTMLImageElement | null = null;
const waiting = new Set<string>();

function draw(color: string): void {
    if (!source) return;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = INCIDENT_ICON_SIZE;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.drawImage(source, 0, 0, INCIDENT_ICON_SIZE, INCIDENT_ICON_SIZE);
    ctx.globalCompositeOperation = 'multiply';
    ctx.fillStyle = color;
    ctx.fillRect(0, 0, INCIDENT_ICON_SIZE, INCIDENT_ICON_SIZE);
    ctx.globalCompositeOperation = 'destination-in';
    ctx.drawImage(source, 0, 0, INCIDENT_ICON_SIZE, INCIDENT_ICON_SIZE);
    tinted[color] = canvas.toDataURL('image/png');
}

/** Data URL of the icon for this priority; the untinted icon until the tint is ready. */
export function incidentIcon(priority: number): string {
    const color = priorityColor(priority);
    if (tinted[color]) return tinted[color];
    if (source?.complete) {
        draw(color);
    } else {
        waiting.add(color);
        if (!source) {
            source = new Image();
            source.onload = () => {
                for (const c of waiting) draw(c);
                waiting.clear();
            };
            source.src = INCIDENT_ICON_PNG;
        }
    }
    return tinted[color] ?? INCIDENT_ICON_PNG;
}
