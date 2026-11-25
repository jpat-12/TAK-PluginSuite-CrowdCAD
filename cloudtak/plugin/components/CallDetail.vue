<template>
    <div class='px-2 py-2'>
        <button
            class='btn btn-sm btn-outline-secondary mb-2'
            @click='$emit("close")'
        >
            ◀ Board
        </button>

        <div class='d-flex align-items-center gap-2'>
            <IncidentIcon
                :priority='call.priority'
                :size='34'
            />
            <span class='fw-bold fs-3'>{{ callNumber(call) }}</span>
            <span
                class='crowdcad-chip'
                :style='`background:${status.color}`'
            >{{ status.label }}</span>
            <span
                v-if='call.priority === 1'
                class='badge bg-red text-white ms-auto'
            >Priority</span>
        </div>
        <div class='fw-bold mb-2'>
            {{ headline(call) }}
        </div>

        <!-- Location -->
        <div class='subheader mt-2 mb-1 d-flex align-items-center'>
            <span>Location</span>
            <button
                v-if='canDispatch && !editing'
                class='btn btn-sm btn-link ms-auto p-0'
                @click='startEdit'
            >
                Set location
            </button>
        </div>
        <template v-if='!editing'>
            <div>{{ call.location || 'No location' }}</div>
            <div
                v-if='call.floor'
                class='fs-3 fw-bold'
            >
                {{ floorLabel(call.floor) }}
            </div>
            <div
                v-if='positionWarning(call)'
                class='small text-warning'
            >
                {{ positionWarning(call) }}
            </div>
            <div
                v-if='hasPosition(call)'
                class='small text-secondary'
            >
                {{ call.lat?.toFixed(5) }}, {{ call.lon?.toFixed(5) }}
            </div>
            <div
                v-if='call.w3w'
                class='small fw-bold text-danger'
            >
                ///{{ call.w3w }}
            </div>
        </template>
        <div
            v-else-if='view'
            class='card card-sm'
        >
            <div class='card-body py-2'>
                <LocationEditor
                    v-model='draft'
                    :posts='view.posts'
                    :w3w='Boolean(view.w3w)'
                />
                <div
                    v-if='editError'
                    class='small text-danger mb-1'
                >
                    {{ editError }}
                </div>
                <div class='d-flex gap-1'>
                    <button
                        class='btn btn-sm btn-primary flex-grow-1'
                        :disabled='busy'
                        @click='saveLocation'
                    >
                        Save
                    </button>
                    <button
                        class='btn btn-sm btn-outline-secondary'
                        @click='editing = false'
                    >
                        Cancel
                    </button>
                </div>
            </div>
        </div>

        <!-- Radar -->
        <div class='subheader mt-3 mb-1 d-flex align-items-center'>
            <span>Units around it</span>
            <button
                v-if='radarUnits.length'
                class='btn btn-sm btn-link ms-auto p-0'
                @click='fitAll'
            >
                Show all on map
            </button>
        </div>
        <template v-if='radarUnits.length'>
            <UnitRadar
                :priority='call.priority'
                :units='radarUnits'
                @pick='panToName'
            />
            <div class='small text-secondary text-center'>
                North up · tap a unit to pan the map to it
            </div>
        </template>
        <div
            v-else
            class='small text-secondary'
        >
            {{ hasPosition(call) ? 'No units with a position yet.' : 'Set a location to see units around it.' }}
        </div>

        <!-- Teams on this call -->
        <div class='subheader mt-3 mb-1'>
            On this call ({{ call.assigned.length }})
        </div>
        <div
            v-if='!call.assigned.length'
            class='small text-danger'
        >
            No team yet.
        </div>
        <div
            v-for='a in call.assigned'
            :key='a.callsign'
            class='d-flex align-items-center gap-2 py-1 border-bottom'
        >
            <UnitBadge
                :def='badgeFor(a.callsign)'
                :stale='staleFor(a.callsign)'
            />
            <div
                class='flex-grow-1 text-truncate cursor-pointer'
                @click='panToName(a.callsign)'
            >
                <div class='text-truncate'>
                    {{ a.callsign }}
                </div>
                <div class='small text-secondary'>
                    {{ describeRelative(relativeTo(call, unitOf(a.callsign) ?? { lat: null, lon: null })) }}
                </div>
            </div>
            <select
                v-if='canDispatch && view'
                class='form-select form-select-sm'
                style='width: 10.5em;'
                :disabled='busy'
                :value='dispatchStatus(a.callsign)'
                @change='changeOnCall(a.callsign, ($event.target as HTMLSelectElement))'
            >
                <option
                    v-if='!view.statuses.onCall.includes(dispatchStatus(a.callsign))'
                    :value='dispatchStatus(a.callsign)'
                    disabled
                >
                    {{ dispatchStatus(a.callsign) || '—' }}
                </option>
                <option
                    v-for='s in view.statuses.onCall'
                    :key='s'
                    :value='s'
                >
                    {{ s }}
                </option>
            </select>
        </div>
        <div
            v-if='canDispatch'
            class='small text-secondary mt-1'
        >
            Status also follows the medics’ ATAK taps (En Route, On Scene, Transporting). Detached takes a team
            off the call; Delivered, Refusal, NMM … close it.
        </div>

        <!-- Closest teams -->
        <div class='subheader mt-3 mb-1'>
            Closest teams
        </div>
        <div
            v-if='!closest.length'
            class='small text-secondary'
        >
            No free teams with a position.
        </div>
        <div
            v-for='c in closest'
            :key='c.unit.callsign'
            class='d-flex align-items-center gap-2 py-1 border-bottom'
        >
            <UnitBadge
                :def='unitStatus(c.unit)'
                :stale='isStale(c.unit, now)'
            />
            <div
                class='flex-grow-1 text-truncate cursor-pointer'
                @click='panToName(c.unit.callsign)'
            >
                <div class='text-truncate'>
                    {{ c.unit.callsign }}
                </div>
                <div class='small text-secondary'>
                    {{ describeRelative(c) }} · {{ unitStatus(c.unit).label }}
                </div>
            </div>
            <button
                v-if='canDispatch'
                class='btn btn-sm btn-primary'
                :disabled='busy'
                @click='assign(c.unit.callsign)'
            >
                Assign
            </button>
        </div>
        <select
            v-if='canDispatch && view && unplacedFree.length'
            class='form-select form-select-sm mt-2'
            :disabled='busy'
            value=''
            @change='assignFromSelect($event.target as HTMLSelectElement)'
        >
            <option value=''>
                Add Team (no position yet)
            </option>
            <option
                v-for='u in unplacedFree'
                :key='u.callsign'
                :value='u.callsign'
            >
                {{ u.callsign }} ({{ unitStatus(u).label }})
            </option>
        </select>

        <div class='d-flex gap-1 mt-3'>
            <button
                v-if='hasPosition(call)'
                class='btn btn-sm btn-outline-secondary'
                @click='flyTo(call.lat, call.lon)'
            >
                Show on map
            </button>
            <span class='small text-secondary ms-auto align-self-center'>
                Opened {{ call.created ? ago(now - call.created) + ' ago' : '—' }} · {{ call.reportedBy }}
            </span>
        </div>
    </div>
</template>

<script setup lang='ts'>
// One call: where it is (and setting that), the units around it, the teams on it with their
// CrowdCAD status on the call, and the closest free teams to assign. Every button is one bridge
// action (CrowdCAD's own dispatch handlers) followed by a refresh.
import { computed, ref } from 'vue';
import IncidentIcon from './IncidentIcon.vue';
import LocationEditor from './LocationEditor.vue';
import UnitBadge from './UnitBadge.vue';
import UnitRadar from './UnitRadar.vue';
import * as crowdcad from '../lib/client.ts';
import {
    UNKNOWN_STATUS, ago, callNumber, callStatus, describeRelative, floorLabel, hasPosition, headline,
    isStale, positionWarning, rankClosest, relativeTo, unitStatus, type Relative, type StatusDef,
} from '../lib/core.ts';
import { draftFor, toPayload } from '../lib/location.ts';
import { fitPoints, flyTo, mapCentre } from '../lib/map-pick.ts';
import { act, store } from '../lib/store.ts';
import type { BoardCall, BoardEvent, BoardUnit, DispatchView } from '../lib/types.ts';

const props = defineProps<{ call: BoardCall; event: BoardEvent; view: DispatchView | null }>();
defineEmits<{ close: [] }>();

const CLOSING = ['Delivered', 'Refusal', 'NMM', 'Unable to Locate', 'Rolled from Scene'];

const busy = ref(false);
const editing = ref(false);
const editError = ref('');
const draft = ref(draftFor('', undefined, false));
const now = computed(() => store.now);

const status = computed(() => callStatus(props.call));
const canDispatch = computed(() => Boolean(props.view && props.view.canDispatch && !props.view.ended && props.call.callId));
const assignedNames = computed(() => new Set(props.call.assigned.map((a) => a.callsign)));

function unitOf(name: string): BoardUnit | undefined {
    return props.event.units.find((u) => u.callsign === name);
}

function badgeFor(name: string): StatusDef {
    const u = unitOf(name);
    return u ? unitStatus(u) : UNKNOWN_STATUS;
}

function staleFor(name: string): boolean {
    const u = unitOf(name);
    return u ? isStale(u, now.value) : false;
}

// CrowdCAD's own status for a unit (the select's value), from the dispatch view.
function dispatchStatus(name: string): string {
    return props.view?.units.find((u) => u.name === name)?.status || '';
}

const radarUnits = computed(() => props.event.units
    .map((u) => ({ unit: u, rel: relativeTo(props.call, u), assigned: assignedNames.value.has(u.callsign), stale: isStale(u, now.value) }))
    .filter((x): x is { unit: BoardUnit; rel: Relative; assigned: boolean; stale: boolean } => x.rel !== null));

// Free = not on any open call and not on break; CrowdCAD lets dispatch add a busy team too,
// but the closest list is for sending someone now.
const freeUnits = computed(() => props.event.units.filter((u) => !assignedNames.value.has(u.callsign)
    && !u.incident && u.status !== 'OOS'));
const closest = computed(() => rankClosest(props.call, freeUnits.value).slice(0, 8));
const unplacedFree = computed(() => freeUnits.value.filter((u) => !hasPosition(u)));

function panToName(name: string): void {
    const u = unitOf(name);
    if (u && hasPosition(u)) flyTo(u.lat, u.lon);
    else store.actionError = name + ' has no position yet';
}

function fitAll(): void {
    const pts = [props.call, ...radarUnits.value.map((x) => x.unit)].filter(hasPosition);
    fitPoints(pts);
}

function startEdit(): void {
    const loc = props.call.callLocation ?? props.call.location ?? '';
    const isPost = Boolean(props.view?.posts.some((p) => p.name === loc));
    const details = props.view?.calls.find((c) => c.id === props.call.callId)?.details;
    draft.value = draftFor(loc, details, isPost);
    editError.value = '';
    editing.value = true;
}

async function run(fn: () => Promise<unknown>): Promise<boolean> {
    busy.value = true;
    const ok = await act(fn);
    busy.value = false;
    return ok;
}

async function saveLocation(): Promise<void> {
    const callId = props.call.callId;
    if (!callId) return;
    const where = toPayload(draft.value, mapCentre());
    if ('error' in where) {
        editError.value = where.error;
        return;
    }
    // A post or a point becomes the call's CrowdCAD location; the rest goes in its notes.
    if (await run(() => crowdcad.setCallDetails(props.event.id, callId, where.details))) editing.value = false;
    else editError.value = store.actionError ?? 'CrowdCAD refused it.';
}

async function assign(name: string): Promise<void> {
    const callId = props.call.callId;
    if (callId) await run(() => crowdcad.assignUnit(props.event.id, callId, name));
}

async function assignFromSelect(select: HTMLSelectElement): Promise<void> {
    const name = select.value;
    select.value = '';
    if (name) await assign(name);
}

async function changeOnCall(unit: string, select: HTMLSelectElement): Promise<void> {
    const callId = props.call.callId;
    const status = select.value;
    const restore = (): void => { select.value = dispatchStatus(unit); };
    if (!callId) return restore();
    const extra: { clinicId?: string; transportUnit?: string } = {};
    if (CLOSING.includes(status)
        && !window.confirm(`${status}: this closes call ${callNumber(props.call)} and releases every unit on it. Continue?`)) return restore();
    if (status === 'Rolled from Scene') {
        const unitNo = window.prompt('Ambulance / transport unit number (optional):', '');
        if (unitNo === null) return restore();
        if (unitNo.trim()) extra.transportUnit = unitNo.trim();
    }
    const clinics = props.view?.clinics ?? [];
    if ((status === 'Transporting' || status === 'Delivered') && clinics.length > 1) {
        const pick = window.prompt(`Which clinic?\n${clinics.map((c, i) => `${i + 1}. ${c.name}`).join('\n')}`, '1');
        const clinic = clinics[Number(pick) - 1];
        if (!clinic) return restore();
        extra.clinicId = clinic.id;
    }
    await run(() => crowdcad.setStatusOnCall(props.event.id, callId, unit, status, extra));
}
</script>

<style scoped>
.crowdcad-chip { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; font-weight:700; color:#000; white-space:nowrap; }
</style>
