<template>
    <div>
        <div class='btn-group btn-group-sm w-100 mb-1 flex-wrap'>
            <button
                v-for='[src, label] in sources'
                :key='src'
                type='button'
                class='btn'
                :class='draft.source === src ? "btn-primary" : "btn-outline-secondary"'
                @click='setSource(src)'
            >
                {{ label }}
            </button>
        </div>

        <!-- Post: CrowdCAD places it itself -->
        <template v-if='draft.source === "post"'>
            <div class='input-group input-group-sm mb-1'>
                <input
                    v-model='draft.post'
                    class='form-control'
                    list='crowdcad-posts'
                    placeholder='Post'
                    maxlength='120'
                >
                <button
                    v-if='placedPosts.length'
                    class='btn btn-outline-secondary'
                    type='button'
                    title='Nearest post to the center of the map'
                    @click='nearestPost'
                >
                    📍
                </button>
                <datalist id='crowdcad-posts'>
                    <option
                        v-for='p in posts'
                        :key='p.name'
                        :value='p.name'
                    />
                </datalist>
            </div>
            <div
                v-if='draft.post && !isPost(draft.post)'
                class='small text-warning mb-1'
            >
                Not a post: CrowdCAD keeps it, but it won’t appear on the TAK map. Pick a point instead.
            </div>
        </template>

        <div v-else-if='draft.source === "map"'>
            <button
                type='button'
                class='btn btn-sm mb-1'
                :class='picking ? "btn-outline-secondary" : "btn-primary"'
                @click='picking ? stopPicking() : startPicking()'
            >
                {{ picking ? 'Cancel' : (draft.point ? 'Pick again' : 'Click a point on the map') }}
            </button>
            <span
                v-if='picking'
                class='ms-2 small text-secondary'
            >Click the map where the call is…</span>
        </div>

        <div
            v-else-if='draft.source === "w3w"'
            class='input-group input-group-sm mb-1'
        >
            <input
                v-model='draft.w3wInput'
                class='form-control'
                placeholder='///filled.count.soap'
                @keydown.enter.prevent='findWords'
            >
            <button
                type='button'
                class='btn btn-outline-secondary'
                :disabled='looking'
                @click='findWords'
            >
                Find
            </button>
        </div>

        <input
            v-else-if='draft.source === "coords"'
            v-model='draft.coords'
            class='form-control form-control-sm mb-1'
            placeholder='39.18085, -86.52540'
            @change='useCoords'
        >

        <div
            v-else
            class='small text-secondary mb-1'
        >
            Pan the map so the call is in the middle. Saved as an estimate.
        </div>

        <div
            v-if='draft.point && draft.source !== "centre" && draft.source !== "post"'
            class='small mb-1'
        >
            <span class='text-secondary'>{{ draft.point.lat.toFixed(5) }}, {{ draft.point.lon.toFixed(5) }}</span>
            <span
                v-if='draft.w3w'
                class='ms-2 fw-bold text-danger'
            >///{{ draft.w3w }}</span>
            <span
                v-if='draft.w3wPlace'
                class='ms-1 text-secondary'
            >near {{ draft.w3wPlace }}</span>
        </div>
        <div
            v-if='lookupError'
            class='small text-warning mb-1'
        >
            {{ lookupError }}
        </div>

        <label class='form-label mb-1 small'>Description <span class='text-secondary'>(goes in the call’s notes)</span></label>
        <input
            v-model='draft.description'
            class='form-control form-control-sm mb-1'
            maxlength='120'
            placeholder='Sec 104 Row 22 · Gate 3 · Concourse N'
        >

        <label class='form-label mb-1 small'>Floor</label>
        <div class='d-flex flex-wrap gap-1 mb-1'>
            <button
                v-for='fl in FLOORS'
                :key='String(fl)'
                type='button'
                class='btn btn-sm px-2'
                :class='draft.floor === fl ? "btn-primary" : "btn-outline-secondary"'
                :title='fl === null ? "No floor" : floorLabel(fl)'
                @click='draft.floor = fl'
            >
                {{ floorShort(fl) }}
            </button>
        </div>
    </div>
</template>

<script setup lang='ts'>
// Where a call is: a CrowdCAD post, or a point (map click, what3words, coordinates, map centre),
// plus a spoken description and a floor. lib/location.ts says what each becomes in CrowdCAD.
import { computed, onUnmounted, ref } from 'vue';
import * as crowdcad from '../lib/client.ts';
import { FLOORS, floorLabel, floorShort, parseCoords } from '../lib/core.ts';
import { SOURCES, type LocationDraft } from '../lib/location.ts';
import { cancelPick, clearPin, flyTo, mapCentre, pickPoint, showPin } from '../lib/map-pick.ts';
import type { PointSource } from '../lib/types.ts';

const props = defineProps<{
    posts: { name: string; lat: number | null; lon: number | null }[];
    w3w: boolean;
}>();
const draft = defineModel<LocationDraft>({ required: true });

const picking = ref(false);
const looking = ref(false);
const lookupError = ref('');

const sources = computed(() => SOURCES.filter(([src]) => src !== 'w3w' || props.w3w));
const placedPosts = computed(() => props.posts.filter((p) => p.lat !== null && p.lon !== null));

function isPost(name: string): boolean {
    return props.posts.some((p) => p.name === name.trim());
}

function setSource(src: PointSource): void {
    draft.value.source = src;
    lookupError.value = '';
    stopPicking();
    if (src === 'post' || src === 'centre') clearPin();
    else if (draft.value.point) showPin(draft.value.point.lat, draft.value.point.lon);
    if (src === 'map' && !draft.value.point) startPicking();
}

// Place the chosen point: pin it on the map and fill in its what3words (best effort).
async function setPoint(lat: number, lon: number, words = '', place = ''): Promise<void> {
    draft.value.point = { lat, lon };
    draft.value.w3w = words;
    draft.value.w3wPlace = place;
    showPin(lat, lon);
    if (!words && props.w3w) {
        try {
            const r = await crowdcad.w3wAt(lat, lon);
            if (draft.value.point?.lat === lat && draft.value.point?.lon === lon) draft.value.w3w = r.words;
        } catch { /* what3words unavailable: coordinates are enough */ }
    }
}

function startPicking(): void {
    picking.value = true;
    pickPoint((lat, lon) => {
        picking.value = false;
        void setPoint(lat, lon);
    });
}

function stopPicking(): void {
    picking.value = false;
    cancelPick();
}

async function findWords(): Promise<void> {
    looking.value = true;
    lookupError.value = '';
    try {
        const r = await crowdcad.w3wFind(draft.value.w3wInput);
        await setPoint(r.lat, r.lon, r.words, r.nearestPlace);
        flyTo(r.lat, r.lon);
    } catch (err) {
        lookupError.value = err instanceof Error ? err.message : String(err);
    } finally {
        looking.value = false;
    }
}

function useCoords(): void {
    const p = parseCoords(draft.value.coords);
    if (p) void setPoint(p.lat, p.lon);
    else lookupError.value = 'Enter coordinates as "lat, lon", e.g. 39.18085, -86.52540';
}

function nearestPost(): void {
    const c = mapCentre();
    if (!c) return;
    let best: { name: string; d: number } | null = null;
    for (const p of placedPosts.value) {
        const dLat = (p.lat as number) - c.lat;
        const dLon = ((p.lon as number) - c.lon) * Math.cos(c.lat * Math.PI / 180);
        const d = dLat * dLat + dLon * dLon;
        if (!best || d < best.d) best = { name: p.name, d };
    }
    if (best) draft.value.post = best.name;
}

onUnmounted(() => {
    stopPicking();
    clearPin();
});
</script>
