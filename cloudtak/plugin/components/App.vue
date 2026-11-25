<!--
  CrowdCAD dispatcher panel: a copy of IU EMS Dispatch (TAK-PluginSuite-IndianaUniversity/
  CloudTAK-Eventcad) without IU branding, on the CrowdCAD bridge (lib/bridge.ts).
  Board → Incident → New incident.
  Everything shown comes from the bridge's board (lib/bridge.ts); every button is one bridge
  action followed by a refresh. Nothing is edited locally.
-->
<template>
    <div class='iucad'>
        <div class='d-flex align-items-center px-3 py-2 iucad-header'>
            <IconAmbulance :size='22' />
            <div
                class='ms-2 fw-bold'
                style='font-size:15px'
            >
                CrowdCAD Dispatch
            </div>
            <button
                class='ms-auto small px-2 iucad-conn'
                :class='store.conn.ok ? "ok" : "bad"'
                :title='store.conn.error || "Bridge connected"'
                @click='refresh()'
            >
                {{ store.conn.ok ? 'Bridge OK' : 'Bridge offline' }}
            </button>
        </div>
        <div
            v-if='!store.conn.ok'
            class='px-2 py-1 iucad-warn'
        >
            {{ store.conn.error }}{{ store.conn.at ? ' · last good ' + ago(Date.now() - store.conn.at) + ' ago' : '' }}
        </div>
        <div
            v-if='actionError'
            class='px-2 py-1 iucad-warn'
        >
            {{ actionError }}
        </div>

        <!-- ═══════════════════════════════ BOARD ═══════ -->
        <template v-if='view.screen === "board"'>
            <div class='d-flex gap-1 px-2 pt-2'>
                <button
                    v-for='(def, code) in UNIT_STATUS'
                    :key='code'
                    class='iucad-sum flex-fill'
                    :class='{ on: view.filter === code }'
                    :style='view.filter === code ? `background:${def.color};border-color:${def.color}` : `border-color:${def.color}`'
                    :title='(view.filter === code ? "Showing only " : "Show only ") + def.label'
                    @click='toggleFilter(code)'
                >
                    {{ def.letter }} {{ unitCountByStatus[code] ?? 0 }}
                </button>
            </div>
            <div
                v-if='view.filter'
                class='d-flex align-items-center px-2 pt-1 iucad-filter-note'
            >
                <span>Showing {{ UNIT_STATUS[view.filter as UnitStatusCode].label }} units only</span>
                <button
                    class='iucad-btn ms-auto'
                    @click='store.view.filter = null'
                >
                    Clear
                </button>
            </div>

            <div class='iucad-sec px-2 mt-2'>
                <span>Incidents ({{ openIncidents.length }})</span>
                <button
                    class='iucad-btn primary'
                    @click='startNew'
                >
                    + New
                </button>
            </div>
            <div
                v-if='!openIncidents.length'
                class='px-2 iucad-dim'
            >
                No open incidents.
            </div>
            <div
                v-for='inc in openIncidents'
                :key='inc.id'
                class='iucad-row iucad-filled px-2'
                :style='rowStyle(INCIDENT_STATUS[inc.status].color)'
                @click='openIncident(inc.id)'
            >
                <span class='iucad-chip iucad-chip-on me-2'>
                    {{ shortForm(inc.id) }}
                </span>
                <div class='flex-fill'>
                    <div>{{ headline(inc) }}</div>
                    <div class='iucad-dim'>
                        {{ INCIDENT_STATUS[inc.status].label }} · {{ ago(now - inc.created) }} ago ·
                        {{ unitsOn(inc.id).length }} on it{{ waiting(inc).length ? ' · ' + waiting(inc).length + ' assigned, not moving' : '' }}
                    </div>
                </div>
            </div>

            <div class='iucad-sec px-2 mt-3'>
                <span>Units ({{ filteredUnits.length }})</span>
                <button
                    class='iucad-btn primary'
                    @click='startAddUnit'
                >
                    + Add
                </button>
            </div>
            <div
                v-if='!store.units.length'
                class='px-2 iucad-dim'
            >
                No units in this event yet. Add one, or add teams in CrowdCAD.
            </div>
            <div
                v-for='u in filteredUnits'
                :key='u.uid'
                class='iucad-row iucad-filled px-2'
                :class='{ "iucad-stale": isStale(u) }'
                :style='rowStyle(UNIT_STATUS[u.status].color)'
                @click='panTo(u)'
            >
                <span class='iucad-badge iucad-chip-on me-2'>
                    {{ UNIT_STATUS[u.status].letter }}
                </span>
                <div class='flex-fill'>
                    <div>{{ u.callsign }}</div>
                    <div class='iucad-dim'>
                        {{ UNIT_STATUS[u.status].label }}{{ u.incident ? ' · ' + shortForm(u.incident) : '' }}{{ isStale(u) ? (u.seen ? ' · last heard ' + ago(now - u.seen) + ' ago' : ' · not heard yet') : '' }}{{ hasPosition(u) ? '' : ' · no GPS fix' }}
                    </div>
                </div>
                <button
                    class='iucad-x ms-2'
                    :disabled='busy'
                    :title='"Remove " + u.callsign + " from the event"'
                    @click.stop='removeUnit(u)'
                >
                    ✕
                </button>
            </div>
        </template>

        <!-- ═══════════════════════════════ INCIDENT ════ -->
        <template v-else-if='view.screen === "incident"'>
            <div class='px-2 pt-2'>
                <button
                    class='iucad-btn mb-2'
                    @click='show("board")'
                >
                    ◀ Board
                </button>
            </div>

            <div
                v-if='!active'
                class='px-2 iucad-dim'
            >
                {{ view.incidentId }} is closed or no longer on the board.
            </div>
            <template v-else>
                <div class='d-flex align-items-center gap-2 px-2 pb-1'>
                    <span
                        class='fw-bold'
                        style='font-size:18px'
                    >{{ active.id }}</span>
                    <span
                        class='iucad-chip'
                        :style='`background:${INCIDENT_STATUS[active.status].color};color:${textOn(INCIDENT_STATUS[active.status].color)}`'
                    >
                        {{ INCIDENT_STATUS[active.status].label }}
                    </span>
                </div>
                <div
                    class='px-2 pb-2'
                    style='color:#e5e7eb;font-weight:600'
                >
                    {{ headline(active) }}
                </div>

                <div class='iucad-sec px-2'>
                    Location
                </div>
                <div class='px-2'>
                    {{ active.location }}
                </div>
                <div
                    v-if='active.floor !== FLOOR_NONE'
                    class='px-2'
                    style='font-size:18px;font-weight:700'
                >
                    {{ floorLabel(active.floor) }}
                </div>
                <div
                    v-if='positionWarning(active)'
                    class='px-2 iucad-warn-text'
                >
                    {{ positionWarning(active) }}
                </div>
                <div class='px-2 iucad-dim'>
                    {{ active.lat.toFixed(5) }}, {{ active.lon.toFixed(5) }}
                </div>
                <div
                    v-if='activeWords'
                    class='px-2 iucad-w3w'
                >
                    ///{{ activeWords }}
                </div>

                <div class='iucad-sec px-2'>
                    <span>Units around it</span>
                    <button
                        v-if='radarUnits.length'
                        class='iucad-btn'
                        @click='fitAll'
                    >
                        Show all on map
                    </button>
                </div>
                <UnitRadar
                    v-if='radarUnits.length'
                    :units='radarUnits'
                    @pick='panToUid'
                />
                <div
                    v-else
                    class='px-2 iucad-dim'
                >
                    No units with a GPS position yet.
                </div>
                <div
                    v-if='radarUnits.length'
                    class='px-2 iucad-dim text-center'
                >
                    North up · tap a unit to pan the map to it
                </div>

                <div class='iucad-sec px-2'>
                    Details
                </div>
                <div class='px-2'>
                    Opened {{ ago(now - active.created) }} ago{{ active.eventTitle ? ' · ' + active.eventTitle : '' }}
                </div>
                <div
                    v-if='active.notes'
                    class='px-2'
                >
                    {{ active.notes }}
                </div>
                <div class='d-flex flex-wrap gap-1 px-2 py-1'>
                    <button
                        class='iucad-btn'
                        @click='flyTo(active.lat, active.lon)'
                    >
                        Show on map
                    </button>
                </div>

                <div class='iucad-sec px-2'>
                    Status
                </div>
                <div class='d-flex flex-wrap gap-1 px-2 pb-1'>
                    <button
                        v-for='[code, label] in STATUS_ACTIONS'
                        :key='code'
                        class='iucad-btn'
                        :class='{ on: active.status === code, primary: code === "CLOSED" }'
                        :disabled='busy'
                        @click='setStatus(code)'
                    >
                        {{ label }}
                    </button>
                </div>
                <div class='px-2 iucad-dim'>
                    Status also follows the medics: Respond → Dispatched, On Scene, Transporting.
                </div>

                <div class='iucad-sec px-2'>
                    On this incident ({{ unitsOn(active.id).length }})
                </div>
                <div
                    v-if='!unitsOn(active.id).length && !waiting(active).length'
                    class='px-2 iucad-dim'
                >
                    No units yet.
                </div>
                <template
                    v-for='u in unitsOn(active.id)'
                    :key='u.uid'
                >
                    <div
                        class='iucad-row px-2'
                        @click='panTo(u)'
                    >
                        <span
                            class='iucad-badge me-2'
                            :class='{ "iucad-stale": isStale(u) }'
                            :style='`background:${UNIT_STATUS[u.status].color}`'
                        >
                            {{ UNIT_STATUS[u.status].letter }}
                        </span>
                        <div class='flex-fill'>
                            <div>{{ u.callsign }} · {{ UNIT_STATUS[u.status].label }} for {{ ago(now - u.since) }}</div>
                            <div class='iucad-dim'>
                                {{ describeRelative(relativeTo(active, u)) }}
                            </div>
                        </div>
                    </div>
                    <div class='d-flex flex-wrap gap-1 px-2 pb-2 iucad-unit-strip'>
                        <button
                            v-for='code in UNIT_CODES'
                            :key='code'
                            class='iucad-btn iucad-unit-btn'
                            :class='{ on: u.status === code }'
                            :style='`border-color:${UNIT_STATUS[code].color}` + (u.status === code ? `;background:${UNIT_STATUS[code].color};color:${textOn(UNIT_STATUS[code].color)}` : "")'
                            :disabled='busy || u.status === code'
                            @click='setUnitStatus(u.uid, code)'
                        >
                            {{ UNIT_STATUS[code].label }}
                        </button>
                    </div>
                </template>
                <template
                    v-for='uid in waiting(active)'
                    :key='uid'
                >
                    <div class='iucad-row px-2'>
                        <span
                            class='iucad-badge me-2'
                            style='background:#555;color:#eee'
                        >?</span>
                        <div
                            class='flex-fill'
                            @click='panToUid(uid)'
                        >
                            <div>{{ callsignFor(uid) }} · assigned, not yet responding</div>
                            <div class='iucad-dim'>
                                {{ describeRelativeUid(uid) }}
                            </div>
                        </div>
                        <button
                            class='iucad-btn ms-2'
                            :disabled='busy'
                            @click='unassign(uid)'
                        >
                            Unassign
                        </button>
                    </div>
                    <div class='d-flex flex-wrap gap-1 px-2 pb-2 iucad-unit-strip'>
                        <button
                            v-for='code in UNIT_CODES'
                            :key='code'
                            class='iucad-btn iucad-unit-btn'
                            :class='{ on: statusOf(uid) === code }'
                            :style='`border-color:${UNIT_STATUS[code].color}` + (statusOf(uid) === code ? `;background:${UNIT_STATUS[code].color};color:${textOn(UNIT_STATUS[code].color)}` : "")'
                            :disabled='busy || statusOf(uid) === code'
                            @click='setUnitStatus(uid, code)'
                        >
                            {{ UNIT_STATUS[code].label }}
                        </button>
                    </div>
                </template>

                <div class='iucad-sec px-2'>
                    Closest units
                </div>
                <div
                    v-if='!closest.length'
                    class='px-2 iucad-dim'
                >
                    No units with a GPS position.
                </div>
                <div
                    v-for='c in closest'
                    :key='c.unit.uid'
                    class='iucad-row px-2'
                >
                    <span
                        class='iucad-badge me-2'
                        :class='{ "iucad-stale": isStale(c.unit) }'
                        :style='`background:${UNIT_STATUS[c.unit.status].color}`'
                    >
                        {{ UNIT_STATUS[c.unit.status].letter }}
                    </span>
                    <div
                        class='flex-fill'
                        @click='panTo(c.unit)'
                    >
                        <div>{{ c.unit.callsign }}</div>
                        <div class='iucad-dim'>
                            {{ describeRelative(c) }} ·
                            {{ UNIT_STATUS[c.unit.status].label }}{{ c.unit.incident ? ' ' + shortForm(c.unit.incident) : '' }}
                        </div>
                    </div>
                    <span
                        v-if='active.assigned.includes(c.unit.uid)'
                        class='iucad-dim ms-2'
                    >Assigned</span>
                    <button
                        v-else
                        class='iucad-btn primary ms-2'
                        :disabled='busy'
                        @click='assign(c.unit.uid)'
                    >
                        Assign
                    </button>
                </div>
            </template>
        </template>

        <!-- ═══════════════════════════════ NEW INCIDENT ════ -->
        <template v-else-if='view.screen === "new" && form'>
            <div class='px-2 pt-2 pb-1'>
                <button
                    class='iucad-btn'
                    @click='show("board")'
                >
                    ◀ Board
                </button>
                <div
                    class='fw-bold mt-1'
                    style='font-size:18px'
                >
                    New incident
                </div>
                <div class='iucad-dim'>
                    Adds the call to CrowdCAD. It gets CrowdCAD's next call number.
                </div>
            </div>

            <div class='iucad-sec px-2'>
                Type
            </div>
            <div class='d-flex flex-wrap gap-1 px-2 pb-1'>
                <button
                    v-for='t in TYPES'
                    :key='t'
                    class='iucad-btn'
                    :class='{ on: form.type === t }'
                    @click='form.type = t'
                >
                    {{ t }}
                </button>
            </div>

            <div class='iucad-sec px-2'>
                Priority (1 = most urgent)
            </div>
            <div class='d-flex gap-1 px-2 pb-1'>
                <button
                    v-for='p in [1, 2, 3]'
                    :key='p'
                    class='iucad-btn'
                    :class='{ on: form.priority === p }'
                    @click='form.priority = p'
                >
                    P{{ p }}
                </button>
            </div>

            <div class='iucad-sec px-2'>
                Location
            </div>
            <input
                v-model='form.location'
                class='iucad-input mx-2'
                maxlength='120'
                placeholder='Sec 104 Row 22 · Gate 3 · Concourse N'
            >

            <div class='iucad-sec px-2'>
                Floor (— = none, B = basement)
            </div>
            <div class='d-flex flex-wrap gap-1 px-2 pb-1'>
                <button
                    v-for='fl in floors'
                    :key='fl'
                    class='iucad-btn'
                    :class='{ on: form.floor === fl }'
                    @click='form.floor = fl'
                >
                    {{ floorShort(fl) }}
                </button>
            </div>

            <div class='iucad-sec px-2'>
                Map position
            </div>
            <div class='d-flex flex-wrap gap-1 px-2 pb-1'>
                <button
                    v-for='[src, label] in SOURCES'
                    :key='src'
                    class='iucad-btn'
                    :class='{ on: form.source === src }'
                    @click='setSource(src)'
                >
                    {{ label }}
                </button>
            </div>
            <div
                v-if='form.source === "pick"'
                class='px-2'
            >
                <button
                    class='iucad-btn'
                    :class='{ primary: !picking }'
                    @click='picking ? stopPicking() : startPicking()'
                >
                    {{ picking ? 'Cancel' : (point ? 'Pick again' : 'Click a point on the map') }}
                </button>
                <span
                    v-if='picking'
                    class='ms-2 iucad-filter-note'
                >Click the map where the incident is…</span>
            </div>
            <div
                v-else-if='form.source === "w3w"'
                class='d-flex gap-1 px-2'
            >
                <input
                    v-model='form.w3wInput'
                    class='iucad-input flex-fill'
                    placeholder='///filled.count.soap'
                    @keyup.enter='findWords'
                >
                <button
                    class='iucad-btn'
                    :disabled='busy'
                    @click='findWords'
                >
                    Find
                </button>
            </div>
            <input
                v-else-if='form.source === "coords"'
                v-model='form.coords'
                class='iucad-input mx-2'
                placeholder='39.18085, -86.52540'
                @change='useCoords'
            >
            <div
                v-else
                class='px-2 iucad-dim'
            >
                Pan the map so the incident is in the middle.
            </div>
            <div
                v-if='point && form.source !== "centre"'
                class='px-2 pt-1'
            >
                <span class='iucad-dim'>{{ point.lat.toFixed(5) }}, {{ point.lon.toFixed(5) }}</span>
                <span
                    v-if='form.w3w'
                    class='ms-2 iucad-w3w'
                >///{{ form.w3w }}</span>
                <span
                    v-if='form.w3wPlace'
                    class='ms-1 iucad-dim'
                >near {{ form.w3wPlace }}</span>
            </div>

            <div class='iucad-sec px-2'>
                Complaint (no names, DOB or MRN)
            </div>
            <input
                v-model='form.notes'
                class='iucad-input mx-2'
                maxlength='200'
                placeholder='Chest pain, conscious'
            >

            <div class='iucad-sec px-2'>
                Reported by
            </div>
            <input
                v-model='form.reportedBy'
                class='iucad-input mx-2'
                maxlength='60'
                placeholder='Event Services'
            >

            <div class='d-flex gap-1 px-2 py-2'>
                <button
                    class='iucad-btn primary'
                    :disabled='busy'
                    @click='createIncident'
                >
                    Create
                </button>
                <button
                    class='iucad-btn'
                    @click='show("board")'
                >
                    Cancel
                </button>
            </div>
        </template>

        <!-- ═══════════════════════════════ ADD UNIT ════ -->
        <template v-else-if='view.screen === "add-unit"'>
            <div class='px-2 pt-2 pb-1'>
                <button
                    class='iucad-btn'
                    @click='show("board")'
                >
                    ◀ Board
                </button>
                <div
                    class='fw-bold mt-1'
                    style='font-size:18px'
                >
                    Add unit
                </div>
                <div class='iucad-dim'>
                    Adds a team or supervisor to the CrowdCAD event. Pick the TAK contact who carries it so its
                    position shows here and assignments alert that phone.
                </div>
            </div>
            <div class='iucad-sec px-2'>
                Kind
            </div>
            <div class='d-flex gap-1 px-2 pb-1'>
                <button
                    v-for='[k, label] in UNIT_KINDS'
                    :key='k'
                    class='iucad-btn'
                    :class='{ on: unitForm.kind === k }'
                    @click='unitForm.kind = k'
                >
                    {{ label }}
                </button>
            </div>
            <div class='iucad-sec px-2'>
                {{ unitForm.kind === 'team' ? 'Team name' : 'Supervisor call sign' }}
            </div>
            <input
                v-model='unitForm.name'
                class='iucad-input mx-2'
                maxlength='80'
                placeholder='Medic 1'
            >
            <template v-if='unitForm.kind === "supervisor"'>
                <div class='iucad-sec px-2'>
                    Certification
                </div>
                <input
                    v-model='unitForm.cert'
                    class='iucad-input mx-2'
                    maxlength='40'
                    placeholder='Paramedic'
                >
            </template>
            <div class='iucad-sec px-2'>
                Carried by TAK contact
            </div>
            <select
                v-model='unitForm.takUid'
                class='iucad-input mx-2'
            >
                <option value=''>
                    No device
                </option>
                <option
                    v-for='c in unitContacts'
                    :key='c.uid'
                    :value='c.uid'
                >
                    {{ c.callsign }}
                </option>
            </select>
            <div class='d-flex gap-1 px-2 py-2'>
                <button
                    class='iucad-btn primary'
                    :disabled='busy || !unitForm.name.trim()'
                    @click='addUnit'
                >
                    Add
                </button>
                <button
                    class='iucad-btn'
                    @click='show("board")'
                >
                    Cancel
                </button>
            </div>
        </template>
    </div>
</template>

<script setup lang='ts'>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue';
import { IconAmbulance } from '@tabler/icons-vue';
import UnitRadar from './UnitRadar.vue';
import { store } from '../lib/store.ts';
import { act, contacts, refresh, w3wAt, w3wFind, type TakContact } from '../lib/bridge.ts';
import { pickPoint, cancelPick, showPin, clearPin } from '../lib/map-pick.ts';
import { getPluginApi } from '../lib/plugin-api.ts';
import {
    UNIT_STATUS, INCIDENT_STATUS, TYPES, STALE_AFTER_MS,
    FLOOR_NONE, FLOOR_BASEMENT, FLOOR_MAX,
    headline, shortForm, floorLabel, floorShort, positionWarning, textOn,
    sortOpen, rankClosest, ago, hasPosition, relativeTo, describeRelative,
    type Incident, type Unit, type UnitStatusCode, type Relative,
} from '../lib/core.ts';
import type { NewIncidentForm } from '../lib/store.ts';

const view = computed(() => store.view);
const form = computed(() => store.form);

// Bridge-clock "now", so ages don't drift with the browser's clock.
const tick = ref(Date.now());
const now = computed(() => tick.value + store.skewMs);
let timer: ReturnType<typeof setInterval> | undefined;
onMounted(() => {
    timer = setInterval(() => { tick.value = Date.now(); }, 5_000);
});
onUnmounted(() => {
    clearInterval(timer);
    stopPicking();
    clearPin();
});

const busy = ref(false);
const actionError = ref('');

// ── Board ────────────────────────────────────────────────────────────────────────

const openIncidents = computed(() => sortOpen(store.incidents));

const unitCountByStatus = computed(() => {
    const counts: Record<string, number> = {};
    for (const u of store.units) counts[u.status] = (counts[u.status] ?? 0) + 1;
    return counts;
});

const filteredUnits = computed(() => {
    const list = view.value.filter ? store.units.filter(u => u.status === view.value.filter) : store.units.slice();
    return list.sort((a, b) => (a.status === 'AVL' ? 0 : 1) - (b.status === 'AVL' ? 0 : 1)
        || a.callsign.localeCompare(b.callsign));
});

// The unit's own report says it's on this incident.
const unitsOn = (id: string): Unit[] => store.units.filter(u => u.incident === id);

// Assigned by dispatch but not (yet) on it by their own report.
const waiting = (inc: Incident): string[] => {
    const on = new Set(unitsOn(inc.id).map(u => u.uid));
    return inc.assigned.filter(uid => !on.has(uid));
};

const isStale = (u: Unit): boolean => now.value - u.seen > STALE_AFTER_MS;

const callsignFor = (uid: string): string => store.units.find(u => u.uid === uid)?.callsign ?? uid;

// A whole board row in its status colour, with text that reads on it.
function rowStyle(color: string): string {
    return `background:${color};color:${textOn(color)}`;
}

function toggleFilter(code: string): void {
    store.view.filter = store.view.filter === code ? null : code;
}

// ── Incident ─────────────────────────────────────────────────────────────────────

const active = computed(() => store.incidents.find(i => i.id === view.value.incidentId) ?? null);

const STATUS_ACTIONS: ['DISP' | 'ONSC' | 'TRAN' | 'CLOSED' | 'CXL', string][] = [
    ['DISP', 'Dispatched'], ['ONSC', 'On Scene'], ['TRAN', 'Transporting'],
    ['CLOSED', 'Close'], ['CXL', 'Cancel'],
];

const closest = computed(() => {
    const inc = active.value;
    if (!inc) return [];
    return rankClosest(inc, store.units.filter(u => u.status !== 'OOS' && u.incident !== inc.id)).slice(0, 8);
});

// Every unit with a fix, placed around the active incident.
const radarUnits = computed(() => {
    const inc = active.value;
    if (!inc) return [];
    return store.units
        .map(u => ({ unit: u, rel: relativeTo(inc, u), assigned: inc.assigned.includes(u.uid), stale: isStale(u) }))
        .filter((x): x is { unit: Unit; rel: Relative; assigned: boolean; stale: boolean } => x.rel !== null);
});

// what3words of the open incident: sent with it (walk-ups), else looked up once on the bridge.
const activeWords = computed(() => (active.value ? active.value.w3w || store.w3wCache[active.value.id] || '' : ''));
watch(active, async (inc) => {
    if (!inc || inc.w3w || store.w3wCache[inc.id] !== undefined || !hasPosition(inc)) return;
    store.w3wCache[inc.id] = '';   // one lookup per incident, even if it fails
    try { store.w3wCache[inc.id] = (await w3wAt(inc.lat, inc.lon)).words; } catch { /* no key on the bridge: no words */ }
});

function describeRelativeUid(uid: string): string {
    const u = store.units.find(x => x.uid === uid);
    return active.value && u ? describeRelative(relativeTo(active.value, u)) : 'not heard yet';
}

const floors = [FLOOR_NONE, FLOOR_BASEMENT, ...Array.from({ length: FLOOR_MAX }, (_, i) => i + 1)];

// ── Actions ──────────────────────────────────────────────────────────────────────

function show(screen: 'board'): void {
    stopPicking();
    clearPin();
    store.form = null;
    store.view = { screen, incidentId: null, filter: view.value.filter };
}

function openIncident(id: string): void {
    store.view = { screen: 'incident', incidentId: id, filter: view.value.filter };
}

// ── Units ────────────────────────────────────────────────────────────────────────

const UNIT_KINDS: ['team' | 'supervisor', string][] = [['team', 'Team'], ['supervisor', 'Supervisor']];
const unitForm = ref({ kind: 'team' as 'team' | 'supervisor', name: '', cert: '', takUid: '' });
const unitContacts = ref<TakContact[]>([]);

async function startAddUnit(): Promise<void> {
    unitForm.value = { kind: 'team', name: '', cert: '', takUid: '' };
    store.view = { screen: 'add-unit', incidentId: null, filter: view.value.filter };
    // Contacts already carrying a unit aren't offered again.
    const taken = new Set(store.units.filter(u => u.device).map(u => u.uid));
    try { unitContacts.value = (await contacts()).filter(c => !taken.has(c.uid)); } catch { unitContacts.value = []; }
}

async function addUnit(): Promise<void> {
    const f = unitForm.value;
    const ok = await run(() => act({ action: 'add_unit', unit: {
        name: f.name.trim(), kind: f.kind,
        ...(f.kind === 'supervisor' && f.cert.trim() ? { cert: f.cert.trim() } : {}),
        ...(f.takUid ? { takUid: f.takUid } : {}),
    } }));
    if (ok) show('board');
}

async function removeUnit(u: Unit): Promise<void> {
    const on = u.incident ? ' It comes off ' + shortForm(u.incident) + '.' : '';
    if (!window.confirm('Remove ' + u.callsign + ' from the CrowdCAD event?' + on)) return;
    await run(() => act({ action: 'remove_unit', unitUid: u.uid }));
}

function startNew(): void {
    store.form = {
        type: TYPES[0], priority: 2, floor: FLOOR_NONE, source: 'pick',
        location: '', notes: '', reportedBy: 'Event Services', coords: '',
        w3wInput: '', w3w: '', w3wPlace: '',
    };
    point.value = null;
    store.view = { screen: 'new', incidentId: null, filter: view.value.filter };
    startPicking();
}

// ── New incident position ───────────────────────────────────────────────────────

const SOURCES: [NewIncidentForm['source'], string][] = [
    ['pick', 'Click on map'], ['w3w', 'what3words'], ['centre', 'Map centre'], ['coords', 'Coordinates'],
];
const point = ref<{ lat: number; lon: number } | null>(null);
const picking = ref(false);

function setSource(src: NewIncidentForm['source']): void {
    if (!form.value) return;
    form.value.source = src;
    stopPicking();
    if (src === 'pick' && !point.value) startPicking();
}

// Place the chosen point: pin it on the map, and fill in its what3words (best effort).
async function setPoint(lat: number, lon: number, words = '', place = ''): Promise<void> {
    point.value = { lat, lon };
    showPin(lat, lon);
    if (!form.value) return;
    form.value.w3w = words;
    form.value.w3wPlace = place;
    if (!words) {
        try {
            const r = await w3wAt(lat, lon);
            if (form.value && point.value?.lat === lat && point.value?.lon === lon) form.value.w3w = r.words;
        } catch { /* no what3words on the bridge: coordinates are enough */ }
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
    const f = form.value;
    if (!f) return;
    await run(async () => {
        const r = await w3wFind(f.w3wInput);
        await setPoint(r.lat, r.lon, r.words, r.nearestPlace);
        flyTo(r.lat, r.lon);
    });
}

function useCoords(): void {
    const f = form.value;
    if (!f) return;
    const m = f.coords.match(/^\s*(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)\s*$/);
    if (m && Math.abs(+m[1]) <= 90 && Math.abs(+m[2]) <= 180) void setPoint(+m[1], +m[2]);
}

// Clicking a unit anywhere pans the map to it. Without a GPS fix there's nowhere to go, so
// say so rather than doing nothing.
function panTo(u: Unit): void {
    actionError.value = '';
    if (!hasPosition(u)) {
        actionError.value = u.callsign + ' has no GPS position yet';
        return;
    }
    flyTo(u.lat, u.lon);
}

function panToUid(uid: string): void {
    const u = store.units.find(x => x.uid === uid);
    if (u) panTo(u);
    else actionError.value = callsignFor(uid) + ' has not reported yet';
}

// The incident and every unit with a fix in one view.
function fitAll(): void {
    const inc = active.value;
    if (!inc) return;
    const pts = [inc, ...radarUnits.value.map(x => x.unit)].filter(hasPosition);
    if (!pts.length) return;
    const lons = pts.map(p => p.lon), lats = pts.map(p => p.lat);
    try {
        getPluginApi()?.map.fitBounds(
            [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
            { padding: 80, maxZoom: 18 },
        );
    } catch { /* map not ready */ }
}

function flyTo(lat: number, lon: number): void {
    if (!hasPosition({ lat, lon })) return;
    // Zoom in to street level, but never zoom out a dispatcher who is already closer.
    try {
        const map = getPluginApi()?.map;
        map?.flyTo({ center: [lon, lat], zoom: Math.max(map.getZoom(), 17) });
    } catch { /* map not ready */ }
}

// One action at a time; the bridge's answer (or its error) is what the dispatcher sees.
async function run(fn: () => Promise<unknown>): Promise<boolean> {
    busy.value = true;
    actionError.value = '';
    try {
        await fn();
        return true;
    } catch (e) {
        actionError.value = (e as Error).message;
        return false;
    } finally {
        busy.value = false;
    }
}

async function setStatus(status: 'DISP' | 'ONSC' | 'TRAN' | 'CLOSED' | 'CXL'): Promise<void> {
    const inc = active.value;
    if (!inc) return;
    const closing = status === 'CLOSED' || status === 'CXL';
    if (closing && !window.confirm((status === 'CLOSED' ? 'Close ' : 'Cancel ') + inc.id + '? It disappears from every map.')) return;
    if (await run(() => act({ action: 'status', id: inc.id, status })) && closing) show('board');
}

async function assign(uid: string): Promise<void> {
    const inc = active.value;
    if (inc) await run(() => act({ action: 'assign', id: inc.id, unitUid: uid }));
}

// One unit on the active call: CrowdCAD's own status on the call (Available frees it back to its
// post and, if it was the last unit, CrowdCAD resolves the call; Out of Service also puts it On Break).
const UNIT_CODES: UnitStatusCode[] = ['AVL', 'RESP', 'ONSC', 'TRAN', 'OOS'];

function statusOf(uid: string): UnitStatusCode | '' {
    return store.units.find(u => u.uid === uid)?.status ?? '';
}

async function setUnitStatus(uid: string, status: UnitStatusCode): Promise<void> {
    const inc = active.value;
    if (!inc) return;
    if ((status === 'AVL' || status === 'OOS') && inc.assigned.length <= 1
        && !window.confirm(callsignFor(uid) + ' is the last unit on ' + inc.id + ': CrowdCAD closes the call. Continue?')) return;
    await run(() => act({ action: 'unit_status', id: inc.id, unitUid: uid, status }));
}

async function unassign(uid: string): Promise<void> {
    const inc = active.value;
    if (inc) await run(() => act({ action: 'unassign', id: inc.id, unitUid: uid }));
}

async function createIncident(): Promise<void> {
    const f = form.value;
    if (!f) return;
    let lat: number, lon: number;
    if (f.source === 'centre') {
        const c = (() => { try { return getPluginApi()?.map.getCenter(); } catch { return undefined; } })();
        if (!c) { actionError.value = 'Could not read the map centre.'; return; }
        lat = c.lat; lon = c.lng;
    } else {
        if (f.source === 'coords') useCoords();
        if (!point.value) {
            actionError.value = f.source === 'pick' ? 'Click the map where the incident is first.'
                : f.source === 'w3w' ? 'Find the three words first.'
                    : 'Enter coordinates as "lat, lon", e.g. 39.18085, -86.52540';
            return;
        }
        ({ lat, lon } = point.value);
    }
    let id = '';
    const ok = await run(async () => {
        id = await act({ action: 'create', incident: {
            type: f.type, priority: f.priority, location: f.location, floor: f.floor,
            notes: f.notes, reportedBy: f.reportedBy, lat, lon,
            w3w: f.source === 'centre' ? '' : f.w3w,
        } });
    });
    if (ok) {
        clearPin();
        store.form = null;
        openIncident(id);
    }
}

</script>

<style scoped>
/* Fill CloudTAK's menu drawer and scroll inside it (the drawer itself doesn't scroll). */
.iucad { font-size:14px; color:#eee; background:#000; padding-bottom:12px; height:100%; overflow-y:auto; overscroll-behavior:contain; }
.iucad-header { background:#000; color:#fff; border-bottom:1px solid #333; }
.iucad-conn { border:0; border-radius:10px; color:#fff; cursor:pointer; }
.iucad-conn.ok  { background:#1b5e20; }
.iucad-conn.bad { background:#555; }
.iucad-warn { background:#5d1a1a; color:#fff; font-size:12px; }
.iucad-warn-text { color:#ffb4a9; font-size:13px; }

/* Dark until picked; a picked filter fills with its status colour so it can't be missed. */
.iucad-sum {
    background:#000; color:#bbb; border:2px solid; border-radius:4px;
    padding:6px 0; font-weight:600; cursor:pointer; font-size:13px;
}
.iucad-sum:hover { background:#1c1c1c; color:#eee; }
.iucad-sum.on { color:#000; font-weight:800; }
.iucad-filter-note { font-size:12px; color:#e5e7eb; }
.iucad-w3w { color:#E11F26; font-weight:700; }

.iucad-sec {
    display:flex; align-items:center; justify-content:space-between;
    margin:10px 0 4px; font-size:11px; font-weight:700;
    letter-spacing:.06em; text-transform:uppercase; color:#aaa;
}

.iucad-row {
    display:flex; align-items:center; padding:6px 8px;
    border-bottom:1px solid #333; cursor:pointer;
}
.iucad-row:hover { background:#2a2a2a; }
/* Board rows filled with their status colour; text colour comes from rowStyle(). */
.iucad-filled { border-bottom:1px solid #000; }
.iucad-filled:hover { filter:brightness(1.12); }
.iucad-filled .iucad-dim { color:inherit; opacity:.85; }
.iucad-chip-on { background:rgba(0,0,0,.28); color:inherit; }
.iucad-x { background:transparent; border:0; color:inherit; opacity:.75; cursor:pointer; font-size:14px; }
.iucad-x:hover { opacity:1; }
.iucad-unit-btn { padding:3px 8px; min-height:28px; font-size:12px; border-width:2px; }
.iucad-unit-btn:disabled { opacity:1; }

.iucad-dim { color:#aaa; font-size:12px; }

.iucad-chip {
    display:inline-block; padding:2px 8px; border-radius:10px;
    font-size:12px; font-weight:700; white-space:nowrap;
}

.iucad-badge {
    display:inline-flex; width:26px; height:26px; border-radius:50%;
    align-items:center; justify-content:center;
    color:#000; font-weight:800; flex:none;
}
.iucad-stale { opacity:.4; }

.iucad-btn {
    background:#333; color:#eee; border:1px solid #555; border-radius:4px;
    padding:6px 10px; min-height:34px; cursor:pointer; white-space:nowrap;
}
.iucad-btn:disabled { opacity:.5; cursor:default; }
.iucad-btn.on      { background:#e5e7eb; color:#000; border-color:#e5e7eb; }
.iucad-btn.primary { background:#2563eb; border-color:#2563eb; color:#fff; }

.iucad-input {
    width:calc(100% - 16px); box-sizing:border-box;
    background:#1d1d1d; color:#eee; border:1px solid #555;
    border-radius:4px; padding:8px; margin:2px 0;
}
</style>
