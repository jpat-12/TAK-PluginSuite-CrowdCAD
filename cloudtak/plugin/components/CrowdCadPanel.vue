<template>
    <MenuTemplate name='CrowdCAD Dispatch'>
        <div
            v-if='store.actionError'
            class='alert alert-danger py-2 mx-2 mt-2 mb-0 small d-flex align-items-start'
            role='alert'
        >
            <span class='flex-grow-1'>{{ store.actionError }}</span>
            <button
                type='button'
                class='btn-close ms-2'
                aria-label='Dismiss'
                @click='store.actionError = null'
            />
        </div>
        <div
            v-if='store.error'
            class='alert alert-danger py-2 mx-2 mt-2 mb-0 small'
        >
            {{ store.error }}
        </div>
        <div
            v-if='bridgeWarning'
            class='alert alert-warning py-2 mx-2 mt-2 mb-0 small'
        >
            {{ bridgeWarning }}
        </div>

        <!-- ═══════════ CALL ═══════════ -->
        <template v-if='view.screen === "call" && event'>
            <CallDetail
                v-if='activeCall'
                :call='activeCall'
                :event='event'
                :view='dispatchView'
                @close='show("board")'
            />
            <div
                v-else
                class='px-2 py-2'
            >
                <button
                    class='btn btn-sm btn-outline-secondary mb-2'
                    @click='show("board")'
                >
                    ◀ Board
                </button>
                <div class='small text-secondary'>
                    That call is closed or no longer on the board.
                </div>
            </div>
        </template>

        <!-- ═══════════ ADD CALL / ADD TEAM / ADD SUPERVISOR ═══════════ -->
        <AddCallForm
            v-else-if='view.screen === "add-call" && event && dispatchView'
            :event-id='event.id'
            :view='dispatchView'
            @close='show("board")'
            @created='openCreated'
        />
        <AddUnitForm
            v-else-if='(view.screen === "add-team" || view.screen === "add-supervisor") && event && dispatchView'
            :key='view.screen'
            :event-id='event.id'
            :view='dispatchView'
            :kind='view.screen === "add-team" ? "team" : "supervisor"'
            @close='show("board")'
            @added='show("board")'
        />

        <!-- ═══════════ BOARD ═══════════ -->
        <div
            v-else
            class='px-2 py-2'
        >
            <!-- Event picker + New event -->
            <div class='d-flex align-items-center gap-2 mb-2'>
                <select
                    v-if='store.board && store.board.events.length'
                    v-model='store.eventId'
                    class='form-select form-select-sm flex-grow-1'
                    aria-label='CrowdCAD event'
                >
                    <option
                        v-for='e in store.board.events'
                        :key='e.id'
                        :value='e.id'
                    >
                        {{ eventLabel(e) }}
                    </option>
                </select>
                <span
                    v-else
                    class='small text-secondary flex-grow-1'
                >
                    {{ store.board ? 'No live CrowdCAD event.' : 'Connecting to the CrowdCAD bridge…' }}
                    <a
                        v-if='store.board && store.board.crowdcadUrl'
                        :href='store.board.crowdcadUrl'
                        target='_blank'
                        rel='noopener'
                    >Open CrowdCAD ↗</a>
                </span>
                <button
                    v-if='store.manage'
                    class='btn btn-sm btn-outline-primary text-nowrap'
                    title='Create a CrowdCAD event with TAK contacts as its teams and supervisors'
                    @click='router.push({ name: "home-menu-plugin-crowdcad-new" })'
                >
                    + New event
                </button>
            </div>

            <template v-if='event'>
                <div
                    v-if='dispatchView && !dispatchView.ended && !dispatchView.canDispatch'
                    class='alert alert-warning py-2 mb-2 small'
                >
                    {{ dispatchView.whyNot }}
                </div>
                <div class='d-flex gap-1 mb-2'>
                    <button
                        v-if='event.dispatchUrl'
                        class='btn btn-sm btn-outline-secondary'
                        title='Open CrowdCAD’s own dispatch screen for this event'
                        @click='openCrowdcad'
                    >
                        CrowdCAD ↗
                    </button>
                    <button
                        v-if='store.manage && event.endable'
                        class='btn btn-sm btn-outline-danger ms-auto'
                        :disabled='ending'
                        title='End this event (created from TAK) for everyone'
                        @click='endEvent(event.id, event.name)'
                    >
                        End Event
                    </button>
                </div>

                <!-- Unit status filter: counts per status, tap to show only those -->
                <div class='d-flex gap-1 mb-1'>
                    <button
                        v-for='(def, code) in UNIT_STATUS'
                        :key='code'
                        class='crowdcad-sum flex-fill'
                        :class='{ on: view.filter === code }'
                        :style='view.filter === code ? `background:${def.color};border-color:${def.color}` : `border-color:${def.color}`'
                        :title='(view.filter === code ? "Showing only " : "Show only ") + def.label'
                        @click='store.view.filter = view.filter === code ? null : code'
                    >
                        {{ def.letter }} {{ countByStatus[code] ?? 0 }}
                    </button>
                </div>

                <!-- Calls -->
                <div class='subheader mt-2 mb-1 d-flex align-items-center'>
                    <span>Calls ({{ calls.length }})</span>
                    <button
                        v-if='canDispatch'
                        class='btn btn-sm btn-primary ms-auto py-0'
                        @click='show("add-call")'
                    >
                        + Add Call
                    </button>
                </div>
                <div
                    v-if='!calls.length'
                    class='small text-secondary mb-2'
                >
                    No open calls.
                </div>
                <div
                    v-for='c in calls'
                    :key='c.uid || c.callId || c.id'
                    class='d-flex align-items-center gap-2 py-1 border-bottom cursor-pointer'
                    @click='openCall(c)'
                >
                    <IncidentIcon :priority='c.priority' />
                    <div class='flex-grow-1 text-truncate'>
                        <div class='text-truncate'>
                            <strong>{{ callNumber(c) }}</strong> {{ headline(c) }}
                        </div>
                        <div class='small text-secondary text-truncate'>
                            {{ ago(store.now - (c.created ?? store.now)) }} ·
                            <template v-if='c.assigned.length'>
                                {{ c.assigned.map((a) => a.callsign).join(', ') }}
                            </template>
                            <span
                                v-else
                                class='text-danger'
                            >no team</span>
                            <span
                                v-if='c.placed === false || c.lat === null'
                                class='text-warning'
                            > · not on map</span>
                        </div>
                    </div>
                    <span
                        class='crowdcad-chip'
                        :style='`background:${callStatus(c).color}`'
                    >{{ callStatus(c).label }}</span>
                </div>

                <!-- Teams, then Supervisors (CrowdCAD's own split) -->
                <template
                    v-for='group in groups'
                    :key='group.title'
                >
                    <div class='subheader mt-3 mb-1 d-flex align-items-center'>
                        <span>{{ group.title }} ({{ group.units.length }})</span>
                        <button
                            v-if='canDispatch'
                            class='btn btn-sm btn-outline-primary ms-auto py-0'
                            @click='show(group.add)'
                        >
                            + {{ group.addLabel }}
                        </button>
                    </div>
                    <div
                        v-if='!group.units.length'
                        class='small text-secondary'
                    >
                        {{ view.filter ? 'None with this status.' : 'None yet.' }}
                    </div>
                    <div
                        v-for='u in group.units'
                        :key='u.callsign'
                        class='d-flex align-items-center gap-2 py-1 border-bottom'
                        :class='{ "cursor-pointer": hasPosition(u) }'
                        @click='hasPosition(u) && flyTo(u.lat, u.lon)'
                    >
                        <UnitBadge
                            :def='unitStatus(u)'
                            :stale='isStale(u, store.now)'
                        />
                        <div class='flex-grow-1 text-truncate'>
                            <div class='text-truncate'>
                                {{ u.callsign }}
                            </div>
                            <div class='small text-secondary text-truncate'>
                                {{ unitStatus(u).label }}<template v-if='u.incident'>
                                    · {{ u.incident }}
                                </template><template v-else-if='u.location'>
                                    · {{ u.location }}
                                </template>
                                <template v-if='u.device'>
                                    ·
                                    <span
                                        v-if='u.lastHeard'
                                        :class='{ "text-warning": isStale(u, store.now) }'
                                        :title='"Last report from " + u.uid'
                                    >📡 {{ ago(store.now - u.lastHeard) }} ago</span>
                                    <span
                                        v-else
                                        class='text-warning'
                                        :title='"No reports from " + u.uid + " reach the CrowdCAD bridge. Its ATAK status taps can’t update CrowdCAD until the device is connected and in the same TAK group as the bridge."'
                                    >📡 no reports</span>
                                </template>
                                <span
                                    v-else-if='!hasPosition(u)'
                                    class='text-warning'
                                > · not on map</span>
                            </div>
                        </div>
                    </div>
                </template>
            </template>

            <div
                v-if='store.board'
                class='text-secondary small mt-3'
            >
                Updated {{ ago(store.now - store.board.generated) }} ago
            </div>
        </div>
    </MenuTemplate>
</template>

<script setup lang='ts'>
// The CrowdCAD dispatcher inside CloudTAK: the event's Calls, Teams and Supervisors (CrowdCAD's
// own words), one call at a time with units around it, and Add Call / Add Team / Add Supervisor.
// Without the bridge's manage token on this CloudTAK it's the same board, read-only.
// Everything shown comes from the bridge (lib/store.ts); every button is one bridge action.
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import MenuTemplate from '../../../src/components/CloudTAK/util/MenuTemplate.vue';
import AddCallForm from './AddCallForm.vue';
import AddUnitForm from './AddUnitForm.vue';
import CallDetail from './CallDetail.vue';
import IncidentIcon from './IncidentIcon.vue';
import UnitBadge from './UnitBadge.vue';
import * as crowdcad from '../lib/client.ts';
import {
    UNIT_STATUS, ago, callNumber, callStatus, hasPosition, headline, isStale, sortCalls, unitStatus,
} from '../lib/core.ts';
import { openDispatch } from '../lib/dispatch.ts';
import { flyTo } from '../lib/map-pick.ts';
import { act, currentEvent, refresh, start, stop, store, type Screen } from '../lib/store.ts';
import type { BoardCall, BoardEvent } from '../lib/types.ts';

const router = useRouter();
const ending = ref(false);

const view = computed(() => store.view);
const event = computed(() => currentEvent());
const dispatchView = computed(() => (store.dispatch && store.dispatch.id === event.value?.id ? store.dispatch : null));
const canDispatch = computed(() => Boolean(store.manage && dispatchView.value?.canDispatch && !dispatchView.value.ended));

const calls = computed(() => sortCalls(event.value?.calls ?? []));
const activeCall = computed(() => calls.value.find((c) => (c.uid || c.callId || c.id) === view.value.callUid) ?? null);

const countByStatus = computed(() => {
    const counts: Record<string, number> = {};
    for (const u of event.value?.units ?? []) if (u.status) counts[u.status] = (counts[u.status] ?? 0) + 1;
    return counts;
});

const groups = computed(() => {
    const units = (event.value?.units ?? []).filter((u) => !view.value.filter || u.status === view.value.filter);
    return [
        { title: 'Teams', add: 'add-team' as Screen, addLabel: 'Add Team', units: units.filter((u) => !u.supervisor) },
        { title: 'Supervisors', add: 'add-supervisor' as Screen, addLabel: 'Add Supervisor', units: units.filter((u) => u.supervisor) },
    ];
});

const bridgeWarning = computed(() => {
    const bridge = store.board?.bridge;
    if (!bridge) return null;
    if (bridge.crowdcad === 'down') return 'The bridge can’t reach CrowdCAD — this board may be out of date.';
    if (bridge.crowdcad === 'polling') return 'CrowdCAD realtime unavailable — updates every ~30 s.';
    if (bridge.tak === false) return 'The bridge isn’t connected to TAK Server — map markers may be stale.';
    return null;
});

// "Homecoming · Nov 21 · TAK · 3 calls": same-named events must be tellable apart.
function eventLabel(e: BoardEvent): string {
    const parts = [e.name];
    if (e.date) {
        const d = new Date(e.date);
        if (!Number.isNaN(d.getTime())) parts.push(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }));
    }
    if (e.endable) parts.push('TAK');
    parts.push(`${e.calls.length} ${e.calls.length === 1 ? 'call' : 'calls'}`);
    return parts.join(' · ');
}

function show(screen: Screen): void {
    store.view = { screen, callUid: null, filter: view.value.filter };
}

function openCall(c: BoardCall): void {
    store.view = { screen: 'call', callUid: c.uid || c.callId || c.id, filter: view.value.filter };
}

// A new call appears on the board on the next refresh; open it once it's there.
function openCreated(callId: string | null): void {
    const c = callId ? calls.value.find((x) => x.callId === callId) : undefined;
    if (c) openCall(c);
    else show('board');
}

// CrowdCAD's own dispatch screen for this event, in a floating pane.
function openCrowdcad(): void {
    const e = event.value;
    if (e?.dispatchUrl) openDispatch(e.dispatchUrl, e.name);
}

async function endEvent(id: string, name: string): Promise<void> {
    if (!window.confirm(`End “${name}” for everyone? Its calls and teams leave every TAK map and board.`)) return;
    ending.value = true;
    await act(() => crowdcad.endEvent(id));
    ending.value = false;
}

onMounted(async () => {
    await start();
    await refresh();
});

onUnmounted(() => stop());
</script>

<style scoped>
/* Dark until picked; a picked filter fills with its status colour so it can't be missed. */
.crowdcad-sum {
    background:transparent; color:inherit; border:2px solid; border-radius:4px;
    padding:4px 0; font-weight:600; cursor:pointer; font-size:13px;
}
.crowdcad-sum.on { color:#000; font-weight:800; }
.crowdcad-chip { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; font-weight:700; color:#000; white-space:nowrap; }
</style>
