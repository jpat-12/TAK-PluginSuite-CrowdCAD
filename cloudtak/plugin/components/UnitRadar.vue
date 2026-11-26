<!--
  Where the units are from one incident: incident in the middle, north up, each unit at its
  true bearing and (scaled) distance, rings for scale. Units past the outer ring sit on its
  edge as hollow markers. Clicking a unit emits `pick` (the panel fits both on the map).
-->
<template>
    <svg
        :viewBox='`0 0 ${SIZE} ${SIZE}`'
        class='iucad-radar'
        role='img'
        :aria-label='`Units around the incident, outer ring ${formatMeters(range)}`'
    >
        <!-- The venue: CloudTAK's own basemap (e.g. satellite) under the call, at the radar's
             scale, so a unit "close" across the stadium reads as the long walk it is. -->
        <g
            v-if='tiles.length'
            opacity='0.6'
        >
            <image
                v-for='t in tiles'
                :key='t.key'
                :href='t.href'
                :x='t.x'
                :y='t.y'
                :width='t.size'
                :height='t.size'
                preserveAspectRatio='none'
            />
        </g>
        <!-- The venue outlines a dispatcher drew: the stadium as walls, not just distance. -->
        <polygon
            v-for='(pts, i) in outlines'
            :key='"b" + i'
            :points='pts'
            fill='rgba(0,229,255,0.08)'
            stroke='#00E5FF'
            stroke-width='1.5'
        />
        <circle
            v-for='(r, i) in rings'
            :key='i'
            :cx='C'
            :cy='C'
            :r='r.px'
            fill='none'
            stroke='#3a3a3a'
        />
        <text
            v-for='(r, i) in rings'
            :key='`l${i}`'
            :x='C + 3'
            :y='C - r.px + 11'
            class='ring-label'
        >{{ formatMeters(r.m) }}</text>
        <line
            :x1='C'
            :y1='PAD - 4'
            :x2='C'
            :y2='SIZE - PAD + 4'
            stroke='#2c2c2c'
        />
        <line
            :x1='PAD - 4'
            :y1='C'
            :x2='SIZE - PAD + 4'
            :y2='C'
            stroke='#2c2c2c'
        />
        <text
            :x='C'
            y='11'
            text-anchor='middle'
            class='north'
        >N</text>

        <!-- the incident -->
        <rect
            :x='C - 7'
            :y='C - 7'
            width='14'
            height='14'
            :transform='`rotate(45 ${C} ${C})`'
            fill='#E03131'
            stroke='#e5e7eb'
            stroke-width='1.5'
        />

        <g
            v-for='p in placed'
            :key='p.uid'
            class='unit'
            @click='$emit("pick", p.uid)'
        >
            <title>{{ p.title }}</title>
            <circle
                :cx='p.x'
                :cy='p.y'
                r='10'
                :fill='p.outside ? "#111" : p.color'
                :stroke='p.color'
                :stroke-width='p.assigned ? 3 : 1.5'
                :opacity='p.stale ? 0.45 : 1'
            />
            <text
                :x='p.x'
                :y='p.y + 4'
                text-anchor='middle'
                class='letter'
                :fill='p.outside ? p.color : "#000"'
            >{{ p.letter }}</text>
            <text
                :x='p.x'
                :y='p.y + 22'
                text-anchor='middle'
                class='callsign'
            >{{ p.callsign }}</text>
        </g>
    </svg>
</template>

<script setup lang='ts'>
import { computed } from 'vue';
import { UNIT_STATUS, formatMeters, describeRelative, type Relative, type Unit } from '../lib/core.ts';
import { getPluginApi } from '../lib/plugin-api.ts';

const props = defineProps<{
    units: { unit: Unit; rel: Relative; assigned: boolean; stale: boolean }[];
    center?: { lat: number; lon: number } | null;
    boundaries?: [number, number][][];     // venue outlines ([lat, lon] corners), drawn in Settings
    satellite?: boolean;                   // CloudTAK's basemap under the radar
}>();
defineEmits<{ pick: [uid: string] }>();

const SIZE = 260;
const PAD = 22;
const C = SIZE / 2;
const R = C - PAD;   // outer ring, px

// Outer ring = the next "round" distance past the farthest unit, so the picture uses its space;
// capped so one unit across campus doesn't squash the ones next to the incident.
const STEPS = [50, 100, 200, 300, 500, 750, 1000];
const range = computed(() => {
    const far = Math.max(0, ...props.units.map(u => u.rel.meters));
    return STEPS.find(s => s >= far) ?? STEPS[STEPS.length - 1];
});
const rings = computed(() => [0.5, 1].map(f => ({ m: range.value * f, px: R * f })));

// Basemap tiles under the radar: the first raster source CloudTAK's map is drawing (its tile
// links already carry CloudTAK's token), at the zoom whose metres-per-pixel best fits the radar.
const TILE = 256;
function basemapTemplate(): string | null {
    try {
        const sources = getPluginApi()?.map.getStyle()?.sources ?? {};
        for (const s of Object.values(sources) as { type?: string; tiles?: string[] }[]) {
            if (s.type === 'raster' && s.tiles?.length) return s.tiles[0];
        }
    } catch { /* map not ready */ }
    return null;
}

const tiles = computed(() => {
    const c = props.center;
    const template = props.satellite ? basemapTemplate() : null;
    if (!c || !template || !Number.isFinite(c.lat) || (c.lat === 0 && c.lon === 0)) return [];
    const metresPerPx = range.value / R;                           // the radar's own scale
    const cos = Math.cos(c.lat * Math.PI / 180);
    const z = Math.max(0, Math.min(19, Math.floor(Math.log2(156543.03392 * cos / metresPerPx))));
    const n = 2 ** z;
    const tileMetresPx = 156543.03392 * cos / n;                  // metres per tile pixel at z
    const scale = tileMetresPx / metresPerPx;                      // tile px → radar px
    const wx = (c.lon + 180) / 360 * n * TILE;                     // the call in world pixels at z
    const latRad = c.lat * Math.PI / 180;
    const wy = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n * TILE;
    const half = C / scale;                                        // radar half-width in world px
    const out: { key: string; href: string; x: number; y: number; size: number }[] = [];
    for (let tx = Math.floor((wx - half) / TILE); tx <= Math.floor((wx + half) / TILE); tx++) {
        for (let ty = Math.floor((wy - half) / TILE); ty <= Math.floor((wy + half) / TILE); ty++) {
            if (ty < 0 || ty >= n) continue;
            const x = ((tx % n) + n) % n;
            out.push({
                key: z + '/' + tx + '/' + ty,
                href: template.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(ty)),
                x: C + (tx * TILE - wx) * scale, y: C + (ty * TILE - wy) * scale, size: TILE * scale,
            });
        }
    }
    return out;
});

// Venue outlines in radar pixels: each corner's offset from the call (metres, locally flat) at the
// same scale as the unit dots.
const outlines = computed(() => {
    const c = props.center;
    if (!c || !props.boundaries?.length) return [];
    const mLat = 110_540, mLon = 111_320 * Math.cos(c.lat * Math.PI / 180);
    return props.boundaries.map(poly => poly.map(([lat, lon]) => {
        const x = C + ((lon - c.lon) * mLon) / range.value * R;
        const y = C - ((lat - c.lat) * mLat) / range.value * R;
        return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' '));
});

const placed = computed(() => props.units.map(({ unit, rel, assigned, stale }) => {
    const outside = rel.meters > range.value;
    const d = Math.min(rel.meters, range.value) / range.value * R;
    const a = rel.bearing * Math.PI / 180;
    return {
        uid: unit.uid,
        x: C + d * Math.sin(a),
        y: C - d * Math.cos(a),
        color: UNIT_STATUS[unit.status].color,
        letter: UNIT_STATUS[unit.status].letter,
        callsign: unit.callsign.length > 12 ? unit.callsign.slice(0, 11) + '…' : unit.callsign,
        title: unit.callsign + ' · ' + UNIT_STATUS[unit.status].label + ' · ' + describeRelative(rel),
        outside, assigned, stale,
    };
}));
</script>

<style scoped>
.iucad-radar { display:block; width:100%; max-width:300px; margin:4px auto 0; background:#151515; border-radius:6px; }
.ring-label { fill:#777; font-size:10px; }
.north { fill:#aaa; font-size:11px; font-weight:700; }
.letter { font-size:11px; font-weight:800; pointer-events:none; }
.callsign { fill:#ddd; font-size:10px; pointer-events:none; }
.unit { cursor:pointer; }
</style>
