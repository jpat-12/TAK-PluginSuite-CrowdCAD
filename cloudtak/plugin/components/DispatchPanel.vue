<template>
    <MenuTemplate
        :name='view ? "Dispatch · " + view.name : "Dispatch"'
        :loading='!view && !error'
    >
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
                class='alert alert-warning py-2 mb-2 small'
            >
                {{ error }}
            </div>
            <div
                v-if='view && view.ended'
                class='alert alert-warning py-2 mb-2 small'
            >
                This event has ended.
            </div>
            <div
                v-if='view && !view.ended && !view.canDispatch'
                class='alert alert-warning py-2 mb-2 small'
            >
                {{ view.whyNot }}
            </div>

            <template v-if='view && !view.ended && view.canDispatch'>
                <div class='d-flex align-items-center mb-2'>
                    <span class='small text-secondary'>Changes save to CrowdCAD as “via CloudTAK”.</span>
                    <button
                        v-if='dispatchUrl'
                        class='btn btn-sm btn-link ms-auto px-1'
                        title='Open CrowdCAD’s own dispatch screen'
                        @click='openDispatch(dispatchUrl, view.name)'
                    >
                        CrowdCAD ↗
                    </button>
                </div>

                <!-- New call -->
                <details
                    class='card card-sm mb-2'
                    :open='newOpen'
                    @toggle='newOpen = ($event.target as HTMLDetailsElement).open'
                >
                    <summary class='card-body py-2 fw-bold cursor-pointer'>
                        + New call
                    </summary>
                    <form
                        class='card-body pt-0'
                        @submit.prevent='createCall'
                    >
                        <label class='form-label mb-1 small'>Location</label>
                        <div class='input-group input-group-sm mb-1'>
                            <input
                                v-model='draft.location'
                                class='form-control'
                                list='crowdcad-posts'
                                placeholder='Post (or describe the spot)'
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
                        </div>
                        <datalist id='crowdcad-posts'>
                            <option
                                v-for='p in view.posts'
                                :key='p.name'
                                :value='p.name'
                            />
                        </datalist>
                        <div
                            v-if='draft.location && !isPost(draft.location)'
                            class='small text-warning mb-1'
                        >
                            Not a post: CrowdCAD keeps it, but it won’t appear on the TAK map.
                        </div>
                        <label class='form-label mb-1 small'>Chief complaint</label>
                        <input
                            v-model='draft.chiefComplaint'
                            class='form-control form-control-sm mb-1'
                            maxlength='120'
                            placeholder='e.g. Fall, chest pain (no names, age or sex)'
                        >
                        <div class='d-flex align-items-center gap-2 mb-2'>
                            <label class='form-check mb-0 small'>
                                <input
                                    v-model='draft.priority'
                                    type='checkbox'
                                    class='form-check-input'
                                > Priority
                            </label>
                            <select
                                v-model='draft.assign'
                                class='form-select form-select-sm ms-auto'
                                style='width: 11em;'
                            >
                                <option value=''>
                                    No unit yet
                                </option>
                                <option
                                    v-for='u in freeUnits'
                                    :key='u.name'
                                    :value='u.name'
                                >
                                    {{ u.name }} ({{ u.status }})
                                </option>
                            </select>
                        </div>
                        <button
                            class='btn btn-primary btn-sm w-100'
                            type='submit'
                            :disabled='busy'
                        >
                            Create call
                        </button>
                    </form>
                </details>

                <!-- Calls -->
                <div class='subheader mb-1'>
                    Open calls ({{ sortedCalls.length }})
                </div>
                <div
                    v-if='!sortedCalls.length'
                    class='small text-secondary mb-2'
                >
                    No open calls.
                </div>
                <div
                    v-for='c in sortedCalls'
                    :key='c.id'
                    class='card card-sm mb-1'
                >
                    <div class='card-body py-2'>
                        <div
                            class='d-flex align-items-center'
                            :class='{ "cursor-pointer": c.lat !== null }'
                            :title='c.lat !== null ? "Show on the map" : "Not on the map (location isn’t a mapped post)"'
                            @click='fly(c.lat, c.lon)'
                        >
                            <span
                                v-if='c.priority'
                                class='badge bg-red text-white me-1'
                            >P1</span>
                            <strong class='me-1'>#{{ c.number }}</strong>
                            <span class='text-truncate'>{{ c.chiefComplaint || 'Call' }}</span>
                            <span class='badge bg-secondary-lt ms-auto'>{{ c.status }}</span>
                        </div>
                        <div class='small text-secondary mb-1'>
                            {{ c.location }}
                        </div>
                        <div
                            v-for='name in c.assigned'
                            :key='name'
                            class='d-flex align-items-center gap-1 mb-1'
                        >
                            <span class='small text-truncate flex-grow-1'>{{ name }}</span>
                            <select
                                class='form-select form-select-sm'
                                style='width: 10.5em;'
                                :disabled='busy'
                                :value='unitStatus(name)'
                                @change='changeOnCall(c, name, ($event.target as HTMLSelectElement).value)'
                            >
                                <option
                                    v-if='!view.statuses.onCall.includes(unitStatus(name))'
                                    :value='unitStatus(name)'
                                    disabled
                                >
                                    {{ unitStatus(name) || '—' }}
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
                        <select
                            class='form-select form-select-sm'
                            :disabled='busy'
                            value=''
                            @change='assign(c, ($event.target as HTMLSelectElement))'
                        >
                            <option value=''>
                                {{ c.assigned.length ? '+ Add unit' : 'Assign a unit' }}
                            </option>
                            <option
                                v-for='u in view.units.filter((x) => !c.assigned.includes(x.name))'
                                :key='u.name'
                                :value='u.name'
                            >
                                {{ u.name }} ({{ busyOnOtherCall(u.name, c.id) ? 'on another call' : u.status }})
                            </option>
                        </select>
                    </div>
                </div>

                <!-- Units -->
                <div class='subheader mt-3 mb-1'>
                    Units
                </div>
                <table class='table table-sm table-vcenter small mb-2'>
                    <tbody>
                        <tr
                            v-for='u in view.units'
                            :key='u.name'
                        >
                            <td
                                :class='{ "cursor-pointer": u.lat !== null }'
                                @click='fly(u.lat, u.lon)'
                            >
                                {{ u.name }}
                                <span
                                    v-if='u.kind === "supervisor"'
                                    class='text-secondary'
                                >(sup)</span>
                            </td>
                            <td v-if='callOf(u.name)'>
                                <span class='text-secondary'>on #{{ callOf(u.name)?.number }} · {{ u.status }}</span>
                            </td>
                            <td v-else>
                                <select
                                    class='form-select form-select-sm'
                                    :disabled='busy'
                                    :value='u.status || ""'
                                    @change='changeAvailability(u.name, ($event.target as HTMLSelectElement).value)'
                                >
                                    <option
                                        v-if='!view.statuses.availability.includes(u.status || "")'
                                        :value='u.status || ""'
                                        disabled
                                    >
                                        {{ u.status || '—' }}
                                    </option>
                                    <option
                                        v-for='s in view.statuses.availability'
                                        :key='s'
                                        :value='s'
                                    >
                                        {{ s }}
                                    </option>
                                </select>
                            </td>
                            <td v-if='!callOf(u.name)'>
                                <select
                                    class='form-select form-select-sm'
                                    :disabled='busy'
                                    :value='u.location || ""'
                                    @change='changePost(u.name, ($event.target as HTMLSelectElement).value)'
                                >
                                    <option
                                        v-for='p in postChoices(u.location)'
                                        :key='p'
                                        :value='p'
                                    >
                                        {{ p }}
                                    </option>
                                </select>
                            </td>
                            <td v-else />
                        </tr>
                    </tbody>
                </table>
            </template>
        </div>
    </MenuTemplate>
</template>

<script setup lang='ts'>
// Native dispatch for one CrowdCAD event, inside CloudTAK. Every action goes to the bridge's
// dispatch API (CrowdCAD v1.6.0's own dispatch logic, bridge/crowdcad_tak/dispatch.py), written
// compare-and-swap so it never overwrites a newer change made in CrowdCAD. The record is the
// truth: this panel just re-reads it every few seconds and after each action.
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import MenuTemplate from '../../../src/components/CloudTAK/util/MenuTemplate.vue';
import * as crowdcad from '../lib/client.ts';
import { openDispatch } from '../lib/dispatch.ts';
import { pluginApi } from '../lib/plugin-api.ts';
import type { DispatchCall, DispatchView } from '../lib/types.ts';

const POLL_MS = 4000;
const CLOSING = ['Delivered', 'Refusal', 'NMM', 'Unable to Locate', 'Rolled from Scene'];

const route = useRoute();
const eventId = String(route.query.event || '');
const view = ref<DispatchView | null>(null);
const dispatchUrl = ref<string | null>(null);
const error = ref<string | null>(null);         // loading the view (cleared by the next good refresh)
const actionError = ref<string | null>(null);   // a refused action: stays until dismissed or the next action
const busy = ref(false);
const newOpen = ref(false);
const draft = ref({ location: '', chiefComplaint: '', priority: false, assign: '' });
let timer: ReturnType<typeof setInterval> | null = null;

const sortedCalls = computed(() => [...(view.value?.calls ?? [])]
    .sort((a, b) => Number(b.priority) - Number(a.priority) || (a.number ?? 0) - (b.number ?? 0)));
const placedPosts = computed(() => (view.value?.posts ?? []).filter((p) => p.lat !== null && p.lon !== null));
const freeUnits = computed(() => (view.value?.units ?? []).filter((u) => !callOf(u.name)));

function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

function callOf(name: string): DispatchCall | undefined {
    return view.value?.calls.find((c) => c.assigned.includes(name));
}

function busyOnOtherCall(name: string, callId: string): boolean {
    const call = callOf(name);
    return Boolean(call && call.id !== callId);
}

function unitStatus(name: string): string {
    return view.value?.units.find((u) => u.name === name)?.status || '';
}

function isPost(name: string): boolean {
    return (view.value?.posts ?? []).some((p) => p.name === name.trim());
}

function postChoices(current: string | null): string[] {
    const names = (view.value?.posts ?? []).map((p) => p.name);
    return [...new Set([current || '', ...names, 'Clinic', 'Roaming'].filter(Boolean))];
}

function fly(lat: number | null, lon: number | null): void {
    if (lat === null || lon === null) return;
    pluginApi().map.flyTo({ center: [lon, lat], zoom: Math.max(pluginApi().map.getZoom(), 17) });
}

function nearestPost(): void {
    const center = pluginApi().map.getCenter();
    let best: { name: string; d: number } | null = null;
    for (const p of placedPosts.value) {
        const dLat = (p.lat as number) - center.lat;
        const dLon = ((p.lon as number) - center.lng) * Math.cos(center.lat * Math.PI / 180);
        const d = dLat * dLat + dLon * dLon;
        if (!best || d < best.d) best = { name: p.name, d };
    }
    if (best) draft.value.location = best.name;
}

async function refresh(): Promise<void> {
    try {
        view.value = await crowdcad.dispatchView(eventId);
        error.value = null;
    } catch (err) {
        error.value = errorText(err);   // keep the last good view under the error
    }
}

async function act(fn: () => Promise<unknown>): Promise<boolean> {
    busy.value = true;
    actionError.value = null;
    try {
        await fn();
        return true;
    } catch (err) {
        actionError.value = errorText(err);
        return false;
    } finally {
        await refresh();
        busy.value = false;
    }
}

async function createCall(): Promise<void> {
    const call = { ...draft.value, location: draft.value.location.trim(), chiefComplaint: draft.value.chiefComplaint.trim() };
    const ok = await act(() => crowdcad.newCall(eventId, {
        location: call.location, chiefComplaint: call.chiefComplaint, priority: call.priority,
        ...(call.assign ? { assign: call.assign } : {}),
    }));
    if (ok) {
        draft.value = { location: '', chiefComplaint: '', priority: false, assign: '' };
        newOpen.value = false;
    }
}

async function assign(call: DispatchCall, select: HTMLSelectElement): Promise<void> {
    const unit = select.value;
    select.value = '';
    if (!unit) return;
    if (busyOnOtherCall(unit, call.id)
        && !window.confirm(`${unit} is on call #${callOf(unit)?.number}. Add them to #${call.number} too?`)) return;
    await act(() => crowdcad.assignUnit(eventId, call.id, unit));
}

async function changeOnCall(call: DispatchCall, unit: string, status: string): Promise<void> {
    const extra: { clinicId?: string; transportUnit?: string } = {};
    if (CLOSING.includes(status)
        && !window.confirm(`${status}: this closes call #${call.number} and releases every unit on it. Continue?`)) {
        await refresh();
        return;
    }
    if (status === 'Rolled from Scene') {
        const unitNo = window.prompt('Ambulance / transport unit number (optional):', '');
        if (unitNo === null) {
            await refresh();
            return;
        }
        if (unitNo.trim()) extra.transportUnit = unitNo.trim();
    }
    const clinics = view.value?.clinics ?? [];
    if ((status === 'Transporting' || status === 'Delivered') && clinics.length > 1) {
        const names = clinics.map((c, i) => `${i + 1}. ${c.name}`).join('\n');
        const pick = window.prompt(`Which clinic?\n${names}`, '1');
        const clinic = clinics[Number(pick) - 1];
        if (!clinic) {
            await refresh();
            return;
        }
        extra.clinicId = clinic.id;
    }
    await act(() => crowdcad.setStatusOnCall(eventId, call.id, unit, status, extra));
}

async function changeAvailability(unit: string, status: string): Promise<void> {
    await act(() => crowdcad.setUnitStatus(eventId, unit, status));
}

async function changePost(unit: string, post: string): Promise<void> {
    await act(() => crowdcad.setUnitPost(eventId, unit, post));
}

onMounted(async () => {
    if (!eventId) {
        error.value = 'No event selected.';
        return;
    }
    await refresh();
    try {
        dispatchUrl.value = (await crowdcad.board()).events.find((e) => e.id === eventId)?.dispatchUrl ?? null;
    } catch {
        dispatchUrl.value = null;
    }
    timer = setInterval(() => {
        if (!busy.value) void refresh();
    }, POLL_MS);
});

onUnmounted(() => {
    if (timer) clearInterval(timer);
});
</script>
