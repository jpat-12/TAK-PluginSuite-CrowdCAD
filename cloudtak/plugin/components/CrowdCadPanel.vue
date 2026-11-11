<template>
    <MenuTemplate name='CrowdCAD'>
        <div class='px-2 py-2'>
            <div
                v-if='error'
                class='alert alert-danger py-2 mb-2'
            >
                {{ error }}
            </div>
            <div
                v-if='!board && !error'
                class='text-secondary small'
            >
                Connecting to the CrowdCAD bridge…
            </div>

            <template v-if='board'>
                <div
                    v-if='bridgeWarning'
                    class='alert alert-warning py-2 mb-2 small'
                >
                    {{ bridgeWarning }}
                </div>
                <div
                    v-if='!board.events.length'
                    class='text-secondary small'
                >
                    No live CrowdCAD event.
                </div>
                <select
                    v-if='board.events.length > 1'
                    v-model='eventId'
                    class='form-select form-select-sm mb-2'
                >
                    <option
                        v-for='e in board.events'
                        :key='e.id'
                        :value='e.id'
                    >
                        {{ e.name }}
                    </option>
                </select>

                <template v-if='event'>
                    <div class='subheader mb-1'>
                        {{ event.name }} · {{ event.calls.length }} open {{ event.calls.length === 1 ? 'call' : 'calls' }}
                    </div>
                    <div
                        v-if='!event.calls.length'
                        class='text-secondary small mb-2'
                    >
                        No open calls.
                    </div>
                    <div
                        v-for='c in event.calls'
                        :key='c.uid'
                        class='card card-sm mb-1 cursor-pointer'
                        :title='"Show " + c.id + " on the map"'
                        @click='zoomTo(c.lon, c.lat)'
                    >
                        <div class='card-body py-2'>
                            <div class='d-flex align-items-center'>
                                <span
                                    v-if='c.priority === 1'
                                    class='badge bg-red text-white me-1'
                                >P1</span>
                                <strong class='me-1'>{{ c.id }}</strong>
                                <span class='text-truncate'>{{ c.type }}</span>
                                <span
                                    class='badge ms-auto'
                                    :class='INCIDENT_BADGE[c.status]'
                                >{{ INCIDENT_LABEL[c.status] }}</span>
                            </div>
                            <div class='small text-secondary'>
                                {{ c.location }} · {{ age(c.created) }}
                                <template v-if='c.assigned.length'>
                                    · {{ c.assigned.map((a) => a.callsign).join(', ') }}
                                </template>
                                <template v-else>
                                    · <span class='text-danger'>no unit</span>
                                </template>
                            </div>
                        </div>
                    </div>

                    <div class='subheader mt-3 mb-1'>
                        Teams
                    </div>
                    <table class='table table-sm table-vcenter small mb-2'>
                        <tbody>
                            <tr
                                v-for='u in event.units'
                                :key='u.callsign'
                                :class='{ "cursor-pointer": u.lat !== null }'
                                @click='u.lat !== null && u.lon !== null && zoomTo(u.lon, u.lat)'
                            >
                                <td>
                                    {{ u.callsign }}
                                    <span
                                        v-if='u.device'
                                        class='text-secondary'
                                        title='Carried on an ATAK device — its own position report is on the map'
                                    >(device)</span>
                                </td>
                                <td>
                                    <span
                                        v-if='u.status'
                                        class='badge'
                                        :class='UNIT_BADGE[u.status]'
                                    >{{ UNIT_LABEL[u.status] }}</span>
                                    <span
                                        v-else
                                        class='text-secondary'
                                    >—</span>
                                </td>
                                <td class='text-secondary'>
                                    {{ u.incident || u.location || '' }}
                                </td>
                            </tr>
                        </tbody>
                    </table>

                    <div
                        v-if='event.unplaced.length'
                        class='alert alert-warning py-2 small'
                    >
                        <strong>Not on the map</strong> (location isn't a post on a georeferenced venue layer):
                        <div
                            v-for='u in event.unplaced'
                            :key='u.kind + u.label'
                        >
                            {{ u.kind }} {{ u.label }} — “{{ u.location }}”
                        </div>
                    </div>
                </template>
                <div class='text-secondary small'>
                    Updated {{ age(board.generated) }} ago · read-only view of CrowdCAD
                </div>
            </template>
        </div>
    </MenuTemplate>
</template>

<script setup lang='ts'>
import { computed, onMounted, onUnmounted, ref } from 'vue';
import MenuTemplate from '../../../src/components/CloudTAK/util/MenuTemplate.vue';
import * as crowdcad from '../lib/client.ts';
import { pluginApi } from '../lib/plugin-api.ts';
import { INCIDENT_BADGE, INCIDENT_LABEL, UNIT_BADGE, UNIT_LABEL, type Board } from '../lib/types.ts';

const POLL_MS = 5000;

const board = ref<Board | null>(null);
const error = ref<string | null>(null);
const eventId = ref('');
const now = ref(Date.now());
let timer: ReturnType<typeof setInterval> | null = null;

const event = computed(() => {
    const events = board.value?.events ?? [];
    return events.find((e) => e.id === eventId.value) ?? events[0] ?? null;
});

const bridgeWarning = computed(() => {
    const bridge = board.value?.bridge;
    if (!bridge) return null;
    if (bridge.crowdcad === 'down') return 'The bridge can’t reach CrowdCAD — this board may be out of date.';
    if (bridge.crowdcad === 'polling') return 'CrowdCAD realtime unavailable — updates every ~30 s.';
    if (bridge.tak === false) return 'The bridge isn’t connected to TAK Server — map markers may be stale.';
    return null;
});

function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

function age(ms: number): string {
    const minutes = Math.max(0, Math.floor((now.value - ms) / 60000));
    return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`;
}

function zoomTo(lon: number, lat: number): void {
    pluginApi().map.flyTo({ center: [lon, lat], zoom: Math.max(pluginApi().map.getZoom(), 17) });
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
