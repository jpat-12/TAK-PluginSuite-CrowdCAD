<!--
  Where the units are from one call: the call (its EMS icon) in the middle, north up, each unit
  at its true bearing and scaled distance, rings for scale. Units past the outer ring sit on its
  edge as hollow markers. Clicking a unit emits `pick` with its name.
-->
<template>
    <svg
        :viewBox='`0 0 ${SIZE} ${SIZE}`'
        class='crowdcad-radar'
        role='img'
        :aria-label='`Units around the call, outer ring ${formatMeters(range)}`'
    >
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

        <image
            :href='incidentIcon(priority)'
            :x='C - 11'
            :y='C - 11'
            width='22'
            height='22'
        />

        <g
            v-for='p in placed'
            :key='p.name'
            class='unit'
            @click='$emit("pick", p.name)'
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
            >{{ p.label }}</text>
        </g>
    </svg>
</template>

<script setup lang='ts'>
import { computed } from 'vue';
import { describeRelative, formatMeters, unitStatus, type Relative } from '../lib/core.ts';
import { incidentIcon } from '../lib/incident-icon.ts';
import type { BoardUnit } from '../lib/types.ts';

const props = defineProps<{
    priority: number;
    units: { unit: BoardUnit; rel: Relative; assigned: boolean; stale: boolean }[];
}>();
defineEmits<{ pick: [name: string] }>();

const SIZE = 260;
const PAD = 22;
const C = SIZE / 2;
const R = C - PAD;   // outer ring, px

// Outer ring = the next round distance past the farthest unit, so the picture uses its space;
// capped so one unit across the venue doesn't squash the ones next to the call.
const STEPS = [50, 100, 200, 300, 500, 750, 1000];
const range = computed(() => {
    const far = Math.max(0, ...props.units.map((u) => u.rel.meters));
    return STEPS.find((s) => s >= far) ?? STEPS[STEPS.length - 1];
});
const rings = computed(() => [0.5, 1].map((f) => ({ m: range.value * f, px: R * f })));

const placed = computed(() => props.units.map(({ unit, rel, assigned, stale }) => {
    const outside = rel.meters > range.value;
    const d = Math.min(rel.meters, range.value) / range.value * R;
    const a = rel.bearing * Math.PI / 180;
    const def = unitStatus(unit);
    return {
        name: unit.callsign,
        x: C + d * Math.sin(a),
        y: C - d * Math.cos(a),
        color: def.color,
        letter: def.letter,
        label: unit.callsign.length > 12 ? unit.callsign.slice(0, 11) + '…' : unit.callsign,
        title: unit.callsign + ' · ' + def.label + ' · ' + describeRelative(rel),
        outside, assigned, stale,
    };
}));
</script>

<style scoped>
.crowdcad-radar { display:block; width:100%; max-width:300px; margin:4px auto 0; background:#151515; border-radius:6px; }
.ring-label { fill:#777; font-size:10px; }
.north { fill:#aaa; font-size:11px; font-weight:700; }
.letter { font-size:11px; font-weight:800; pointer-events:none; }
.callsign { fill:#ddd; font-size:10px; pointer-events:none; }
.unit { cursor:pointer; }
</style>
