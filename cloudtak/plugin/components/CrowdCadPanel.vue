<template>
    <MenuTemplate name='CrowdCAD'>
        <div class='px-2 py-2'>
            <div
                v-if='actionError'
                class='alert alert-danger py-2 mb-2 small d-flex align-items-start'
                role='alert'
            >
                <span class='flex-grow-1'>{{ actionError }}</span>
                <button
                    type='button'
                    class='btn-close ms-2'
                    aria-label='Dismiss'
                    @click='actionError = null'
                />
            </div>
            <div
                v-if='error'
                class='alert alert-danger py-2 mb-2 small'
            >
                {{ error }}
            </div>
            <div
                v-if='bridgeWarning'
                class='alert alert-warning py-2 mb-2 small'
            >
                {{ bridgeWarning }}
            </div>

            <!-- Event picker + New event -->
            <div class='d-flex align-items-center gap-2 mb-2'>
                <select
                    v-if='board && board.events.length'
                    v-model='eventId'
                    class='form-select form-select-sm flex-grow-1'
                    aria-label='CrowdCAD event'
                >
                    <option
                        v-for='e in board.events'
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
                    {{ board ? 'No live CrowdCAD event.' : 'Connecting to the CrowdCAD bridge…' }}
                    <a
                        v-if='board && board.crowdcadUrl'
                        :href='board.crowdcadUrl'
                        target='_blank'
                        rel='noopener'
                    >Open CrowdCAD ↗</a>
                </span>
                <button
                    v-if='manage'
                    class='btn btn-sm btn-outline-primary text-nowrap'
                    title='Create a CrowdCAD event with TAK contacts as its teams and supervisors'
                    @click='router.push({ name: "home-menu-plugin-crowdcad-new" })'
                >
                    + New event
                </button>
            </div>

            <template v-if='event'>
                <!-- Event header -->
                <div class='card card-sm mb-3'>
                    <div class='card-body py-2'>
                        <div class='d-flex align-items-center'>
                            <div class='flex-grow-1 text-truncate'>
                                <div class='fw-bold text-truncate'>
                                    {{ event.name }}
                                </div>
                                <div class='small text-secondary'>
                                    {{ event.calls.length }} open {{ event.calls.length === 1 ? 'call' : 'calls' }}
                                    · {{ event.units.length }} {{ event.units.length === 1 ? 'unit' : 'units' }}
                                    <template v-if='event.endable'>
                                        · created from TAK
                                    </template>
                                </div>
                            </div>
                        </div>
                        <div class='d-flex gap-1 mt-2'>
                            <button
                                v-if='manage'
                                class='btn btn-sm btn-primary flex-grow-1'
                                title='Dispatch this event from CloudTAK'
                                @click='router.push({ name: "home-menu-plugin-crowdcad-dispatch", query: { event: event.id } })'
                            >
                                Dispatch
                            </button>
                            <button
                                v-if='event.dispatchUrl'
                                class='btn btn-sm'
                                :class='manage ? "btn-outline-secondary" : "btn-primary flex-grow-1"'
                                title='Open CrowdCAD’s own dispatch screen for this event'
                                @click='openDispatch(event.dispatchUrl, event.name)'
                            >
                                {{ manage ? 'CrowdCAD ↗' : 'Dispatch' }}
                            </button>
                            <button
                                v-if='manage && event.endable'
                                class='btn btn-sm btn-outline-danger'
                                :disabled='ending'
                                title='End this event (created from TAK) for everyone'
                                @click='endEvent(event.id, event.name)'
                            >
                                End
                            </button>
                        </div>
                    </div>
                </div>

                <!-- Calls -->
                <div class='subheader mb-1'>
                    Open calls
                </div>
                <div
                    v-if='!event.calls.length'
                    class='small text-secondary mb-3'
                >
                    No open calls.
                </div>
                <div
                    v-for='c in event.calls'
                    :key='c.uid || c.id'
                    class='card card-sm mb-1'
                    :class='{ "cursor-pointer": c.lat !== null && c.lon !== null }'
                    :title='c.lat !== null ? "Show " + c.id + " on the map" : "Not on the map: its location isn’t a post on a mapped venue layer"'
                    @click='zoomTo(c.lon, c.lat)'
                >
                    <div class='card-body py-2'>
                        <div class='d-flex align-items-center gap-1'>
                            <span
                                v-if='c.priority === 1'
                                class='badge bg-red text-white'
                            >P1</span>
                            <strong>{{ c.id }}</strong>
                            <span class='text-truncate'>{{ c.type }}</span>
                            <span
                                class='badge ms-auto text-nowrap'
                                :class='c.status ? INCIDENT_BADGE[c.status] : "bg-secondary-lt"'
                            >{{ c.status ? INCIDENT_LABEL[c.status] : '—' }}</span>
                        </div>
                        <div class='small text-secondary d-flex align-items-center gap-1 mt-1'>
                            <span class='text-truncate'>
                                {{ c.location || 'No location' }}<template v-if='c.created'> · {{ age(c.created) }}</template>
                                ·
                                <template v-if='c.assigned.length'>{{ c.assigned.map((a) => a.callsign).join(', ') }}</template>
                                <span
                                    v-else
                                    class='text-danger'
                                >no unit</span>
                            </span>
                            <span
                                v-if='c.placed === false'
                                class='badge bg-yellow-lt ms-auto text-nowrap'
                            >not on map</span>
                        </div>
                    </div>
                </div>

                <!-- Units -->
                <div class='subheader mt-3 mb-1'>
                    Units
                </div>
                <div
                    v-if='!event.units.length'
                    class='small text-secondary mb-2'
                >
                    No units in this event.
                </div>
                <div
                    v-for='u in event.units'
                    :key='u.callsign'
                    class='d-flex align-items-center gap-2 py-1 border-bottom'
                    :class='{ "cursor-pointer": u.lat !== null && u.lon !== null }'
                    @click='zoomTo(u.lon, u.lat)'
                >
                    <div class='flex-grow-1 text-truncate'>
                        <div class='text-truncate'>
                            {{ u.callsign }}
                            <span
                                v-if='u.supervisor'
                                class='text-secondary small'
                            >supervisor</span>
                        </div>
                        <div class='small text-secondary text-truncate'>
                            {{ u.incident || u.location || '—' }}
                            <template v-if='u.device'>
                                ·
                                <span
                                    v-if='u.lastHeard'
                                    :title='"Last report from " + u.uid'
                                >📡 {{ heardAgo(u.lastHeard) }}</span>
                                <span
                                    v-else
                                    class='text-warning'
                                    :title='"No reports from " + u.uid + " reach the CrowdCAD bridge. Its ATAK status taps can’t update CrowdCAD until the device is connected and in the same TAK group as the bridge."'
                                >📡 no reports</span>
                            </template>
                            <template v-else-if='u.placed === false'>
                                · <span class='text-warning'>not on map</span>
                            </template>
                        </div>
                    </div>
                    <span
                        class='badge text-nowrap'
                        :class='u.status ? UNIT_BADGE[u.status] : "bg-secondary-lt"'
                    >{{ u.status ? UNIT_LABEL[u.status] : '—' }}</span>
                </div>

                <div
                    v-if='unplacedCount'
                    class='small text-warning mt-2'
                >
                    {{ unplacedCount }} not on the map: their location isn’t a post on a GeoJSON-imported venue layer.
                </div>
            </template>

            <div
                v-if='board'
                class='text-secondary small mt-3'
            >
                Updated {{ age(board.generated) }} ago
            </div>
        </div>
    </MenuTemplate>
</template>

<script setup lang='ts'>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import MenuTemplate from '../../../src/components/CloudTAK/util/MenuTemplate.vue';
import * as crowdcad from '../lib/client.ts';
import { useRouter } from 'vue-router';
import { openDispatch } from '../lib/dispatch.ts';
import { pluginApi } from '../lib/plugin-api.ts';
import { INCIDENT_BADGE, INCIDENT_LABEL, UNIT_BADGE, UNIT_LABEL, type Board, type BoardEvent } from '../lib/types.ts';

const POLL_MS = 5000;

const router = useRouter();
const manage = ref(false);   // this CloudTAK can create/end events and dispatch (bridge manage token configured)
const ending = ref(false);
const actionError = ref<string | null>(null);   // a refused End: stays until dismissed

const board = ref<Board | null>(null);
const error = ref<string | null>(null);
const eventId = ref('');
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;

const event = computed(() => {
    const events = board.value?.events ?? [];
    return events.find((e) => e.id === eventId.value) ?? events[0] ?? null;
});

// Keep the picker showing a real choice (a blank select hides which event the board is for).
watch(board, (b) => {
    const events = b?.events ?? [];
    if (events.length && !events.some((e) => e.id === eventId.value)) eventId.value = events[0].id;
});

const unplacedCount = computed(() => {
    const e = event.value;
    if (!e) return 0;
    return e.calls.filter((c) => c.placed === false).length + e.units.filter((u) => u.placed === false && !u.device).length;
});

const bridgeWarning = computed(() => {
    const bridge = board.value?.bridge;
    if (!bridge) return null;
    if (bridge.crowdcad === 'down') return 'The bridge can’t reach CrowdCAD — this board may be out of date.';
    if (bridge.crowdcad === 'polling') return 'CrowdCAD realtime unavailable — updates every ~30 s.';
    if (bridge.tak === false) return 'The bridge isn’t connected to TAK Server — map markers may be stale.';
    return null;
});

// "IU Football · Nov 21 · TAK": same-named events must be tellable apart.
function eventLabel(e: BoardEvent): string {
    const parts = [e.name];
    if (e.date) {
        const d = new Date(e.date);
        if (!Number.isNaN(d.getTime())) parts.push(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }));
    }
    if (e.endable) parts.push('TAK');
    const n = e.calls.length;
    parts.push(`${n} ${n === 1 ? 'call' : 'calls'}`);
    return parts.join(' · ');
}

function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

function age(ms: number): string {
    const minutes = Math.max(0, Math.floor((now.value - ms) / 60000));
    return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`;
}

function heardAgo(ms: number): string {
    const seconds = Math.max(0, Math.floor((now.value - ms) / 1000));
    return seconds < 90 ? `${seconds}s ago` : `${age(ms)} ago`;
}

function zoomTo(lon: number | null, lat: number | null): void {
    if (lon === null || lat === null) return;
    pluginApi().map.flyTo({ center: [lon, lat], zoom: Math.max(pluginApi().map.getZoom(), 17) });
}

async function endEvent(id: string, name: string): Promise<void> {
    if (!window.confirm(`End “${name}” for everyone? Its calls and teams leave every TAK map and board.`)) return;
    ending.value = true;
    actionError.value = null;
    try {
        await crowdcad.endEvent(id);
        await refresh();
    } catch (err) {
        actionError.value = errorText(err);
    } finally {
        ending.value = false;
    }
}

async function refresh(): Promise<void> {
    try {
        board.value = await crowdcad.board();
        error.value = null;
    } catch (err) {
        error.value = errorText(err);   // keep showing the last good board under the error
    }
    now.value = Date.now();
}

onMounted(async () => {
    try {
        const info = await crowdcad.info();
        manage.value = Boolean(info.manage);
        if (Math.floor(info.api) !== crowdcad.SUPPORTED_API) {
            error.value = `The CrowdCAD bridge speaks API v${info.api}; this plugin needs v${crowdcad.SUPPORTED_API}. Update one of them.`;
            return;
        }
    } catch (err) {
        error.value = errorText(err);
        return;
    }
    await refresh();
    timer = setInterval(() => void refresh(), POLL_MS);
});

onUnmounted(() => {
    if (timer) clearInterval(timer);
});
</script>
