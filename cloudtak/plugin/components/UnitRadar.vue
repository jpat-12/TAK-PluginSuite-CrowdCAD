<!--
  Where the units are from one incident: incident in the middle, north up. The inner disc is a
  zoomed-in map of the venue (fixed MAP_M radius; the basemap continues dimmed out to the corners
  for context, tracker R24.1) with each nearby unit at its true bearing and
  scaled distance. Units farther than that sit in the outer band on their true bearing, hollow and
  dimmed, labelled "far" with their distance, so the map stays zoomed in on the venue whatever a
  stray unit does. Clicking a unit emits `pick` (the panel fits both on the map).
-->
<template>
    <svg
        :viewBox='`0 0 ${SIZE} ${SIZE}`'
        class='iucad-radar'
        role='img'
        :aria-label='`Units around the incident, map radius ${formatMeters(MAP_M)}`'
    >
        <defs>
            <clipPath :id='clipId'>
                <circle
                    :cx='C'
                    :cy='C'
                    :r='RM'
                />
            </clipPath>
            <clipPath :id='`${clipId}-sq`'>
                <rect
                    width='100%'
                    height='100%'
                    rx='6'
                />
            </clipPath>
            <g :id='`${clipId}-tiles`'>
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
        </defs>
        <!-- tracker R24.1: context around the venue. The same tiles, same scale, carry on past the
             disc out to the corners, dimmed, so the surroundings read without zooming the map out.
             Only the imagery is true-scale out here: far units on the band are NOT (see placed). -->
        <use
            v-if='tiles.length'
            :href='`#${clipId}-tiles`'
            opacity='0.35'
            :clip-path='`url(#${clipId}-sq)`'
        />
        <!-- The far band: everything past MAP_M, compressed onto one rim. Translucent over the
             context imagery (tracker R24.1) so the dashed far dots still stand out. -->
        <circle
            :cx='C'
            :cy='C'
            :r='R'
            :fill='tiles.length ? "rgba(29,29,29,0.55)" : "#1d1d1d"'
            stroke='#3a3a3a'
        />
        <!-- The venue: CloudTAK's own basemap (e.g. satellite) under the call, at the radar's
             scale, so a unit "close" across the stadium reads as the long walk it is. The opaque
             disc under it keeps the venue looking as it did before the context imagery. -->
        <circle
            v-if='tiles.length'
            :cx='C'
            :cy='C'
            :r='RM'
            fill='#1d1d1d'
        />
        <use
            v-if='tiles.length'
            :href='`#${clipId}-tiles`'
            opacity='0.6'
            :clip-path='`url(#${clipId})`'
        />
        <!-- The venue outlines a dispatcher drew: the stadium as walls, not just distance. -->
        <g :clip-path='`url(#${clipId})`'>
            <polygon
                v-for='(pts, i) in outlines'
                :key='"b" + i'
                :points='pts'
                fill='rgba(0,229,255,0.08)'
                stroke='#00E5FF'
                stroke-width='1.5'
            />
        </g>
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
        <text
            :x='C + 3'
            :y='C - R + 11'
            class='ring-label'
        >far</text>
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
            :opacity='p.stale || p.outside ? 0.6 : 1'
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
                :stroke-dasharray='p.outside ? "3 2" : undefined'
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
                :y='p.labelY'
                text-anchor='middle'
                class='callsign'
            >{{ p.label }}</text>
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
const R = C - PAD;       // outer edge of the far band, px
const BAND = 26;         // the far band's width, px
const RM = R - BAND;     // the map disc's radius, px
const FAR_R = RM + BAND / 2;

// The map disc always shows MAP_M around the call: venue scale (a stadium and its lots), so the
// satellite picture is readable. Jon asked for this zoomed in (tracker R24, then ~20% more: 160 m);
// units farther out go to the far band instead of shrinking the map to fit them.
const MAP_M = 160;
const rings = [0.5, 1].map(f => ({ m: MAP_M * f, px: RM * f }));
const metresPerPx = MAP_M / RM;

// Each radar instance needs its own clipPath id (the panel can show several calls at once).
const clipId = 'crowdcad-radar-clip-' + Math.random().toString(36).slice(2, 9);

// Basemap tiles under the radar: the first raster source CloudTAK's map is drawing (its tile
// links already carry CloudTAK's token), at the zoom whose metres-per-pixel best fits the radar.
const TILE = 256;
// CloudTAK 13.102 adds every basemap / raster overlay as { type: 'raster', url:
// 'cloudtak-tilejson://<overlay id>' } (base/overlay-class.ts sourceSpec), so the style spec has no
// `tiles`. Its TileJSON protocol (stores/modules/tilejson.ts) hands MapLibre the tile list with the
// session token already appended for CloudTAK hosts (utils/tilejson.ts authorizeTileJSON), and
// MapLibre keeps it on the live source object. Offline / profile assets come back as
// cloudtak-pmtiles:// templates, which an <image> can't fetch: those are skipped.
// The basemap is the bottom-most visible raster layer, so walk the layers from the bottom up.
function basemapTemplate(): string | null {
    try {
        const map = getPluginApi()?.map;
        const style = map?.getStyle();
        if (!map || !style) return null;
        for (const layer of style.layers ?? []) {
            const l = layer as { id: string; type: string; source?: string };
            if (l.type !== 'raster' || !l.source) continue;
            if (map.getLayoutProperty(l.id, 'visibility') === 'none') continue;
            const live = map.getSource(l.source) as unknown as { tiles?: string[] } | undefined;
            const spec = style.sources?.[l.source] as { tiles?: string[] } | undefined;
            const template = live?.tiles?.[0] ?? spec?.tiles?.[0];
            if (template && /^https?:\/\//.test(template)) return template;
        }
    } catch { /* map not ready */ }
    return null;
}

const tiles = computed(() => {
    const c = props.center;
    const template = props.satellite ? basemapTemplate() : null;
    if (!c || !template || !Number.isFinite(c.lat) || (c.lat === 0 && c.lon === 0)) return [];
    const cos = Math.cos(c.lat * Math.PI / 180);
    // Sharpness: pick the zoom whose tile pixels are no bigger than a SCREEN pixel (radar px ÷
    // devicePixelRatio), so tiles are only ever shrunk, never magnified (floor() here blurred them).
    const dpr = Math.min(3, Math.max(1, globalThis.devicePixelRatio || 1));
    const z = Math.max(0, Math.min(19, Math.ceil(Math.log2(156543.03392 * cos * dpr / metresPerPx))));
    const n = 2 ** z;
    const tileMetresPx = 156543.03392 * cos / n;                  // metres per tile pixel at z
    const scale = tileMetresPx / metresPerPx;                      // tile px → radar px
    const wx = (c.lon + 180) / 360 * n * TILE;                     // the call in world pixels at z
    const latRad = c.lat * Math.PI / 180;
    const wy = (1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2 * n * TILE;
    // tracker R24.1: cover the whole square (half-side C), not just the disc (RM), for the dimmed
    // context imagery. Same zoom, so the venue stays as sharp; a few more tiles (~4x4 vs ~3x3).
    const half = C / scale;                                        // square half-side in world px
    const out: { key: string; href: string; x: number; y: number; size: number }[] = [];
    for (let tx = Math.floor((wx - half) / TILE); tx <= Math.floor((wx + half) / TILE); tx++) {
        for (let ty = Math.floor((wy - half) / TILE); ty <= Math.floor((wy + half) / TILE); ty++) {
            if (ty < 0 || ty >= n) continue;
            const x = ((tx % n) + n) % n;
            out.push({
                key: z + '/' + tx + '/' + ty,
                href: template.replace('{z}', String(z)).replace('{x}', String(x)).replace('{y}', String(ty))
                    .replace('{-y}', String(n - 1 - ty)),
                x: C + (tx * TILE - wx) * scale, y: C + (ty * TILE - wy) * scale, size: TILE * scale,
            });
        }
    }
    return out;
});

// Venue outlines in radar pixels: each corner's offset from the call (metres, locally flat) at the
// same scale as the unit dots; clipped to the map disc.
const outlines = computed(() => {
    const c = props.center;
    if (!c || !props.boundaries?.length) return [];
    const mLat = 110_540, mLon = 111_320 * Math.cos(c.lat * Math.PI / 180);
    return props.boundaries.map(poly => poly.map(([lat, lon]) => {
        const x = C + ((lon - c.lon) * mLon) / metresPerPx;
        const y = C - ((lat - c.lat) * mLat) / metresPerPx;
        return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' '));
});

const placed = computed(() => props.units.map(({ unit, rel, assigned, stale }) => {
    const outside = rel.meters > MAP_M;
    const d = outside ? FAR_R : rel.meters / metresPerPx;
    const a = rel.bearing * Math.PI / 180;
    const y = C - d * Math.cos(a);
    const name = unit.callsign.length > 12 ? unit.callsign.slice(0, 11) + '…' : unit.callsign;
    const short = unit.callsign.length > 8 ? unit.callsign.slice(0, 7) + '…' : unit.callsign;
    return {
        uid: unit.uid,
        x: C + d * Math.sin(a),
        y,
        // Far labels on the top half go under the dot (inward), on the bottom half above it, so
        // they stay inside the picture.
        labelY: outside && y > C ? y - 14 : y + 22,
        color: UNIT_STATUS[unit.status].color,
        letter: UNIT_STATUS[unit.status].letter,
        label: outside ? short + ' · far ' + formatMeters(rel.meters) : name,
        title: unit.callsign + ' · ' + UNIT_STATUS[unit.status].label + ' · ' + describeRelative(rel)
            + (outside ? ' (beyond the ' + formatMeters(MAP_M) + ' map)' : ''),
        outside, assigned, stale,
    };
}));
</script>

<style scoped>
.iucad-radar { display:block; width:100%; max-width:300px; margin:4px auto 0; background:#151515; border-radius:6px; }
.ring-label { fill:#777; font-size:10px; }
.north { fill:#aaa; font-size:11px; font-weight:700; }
.letter { font-size:11px; font-weight:800; pointer-events:none; }
.callsign { fill:#ddd; font-size:10px; pointer-events:none; paint-order:stroke; stroke:#151515; stroke-width:3px; }
.unit { cursor:pointer; }
</style>
