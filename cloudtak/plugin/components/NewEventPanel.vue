<template>
    <MenuTemplate
        name='New CrowdCAD event'
        :loading='loading'
    >
        <form
            class='px-2 py-2'
            @submit.prevent='submit'
        >
            <div
                v-if='error'
                class='alert alert-danger py-2 mb-2'
            >
                {{ error }}
            </div>

            <label class='form-label mb-1'>Event name</label>
            <input
                v-model='name'
                class='form-control form-control-sm mb-2'
                maxlength='120'
                placeholder='e.g. IU Football vs Purdue'
                required
            >

            <label class='form-label mb-1'>Date</label>
            <input
                v-model='date'
                type='date'
                class='form-control form-control-sm mb-2'
                required
            >

            <label class='form-label mb-1'>Venue</label>
            <select
                v-model='venueId'
                class='form-select form-select-sm mb-1'
                required
            >
                <option
                    disabled
                    value=''
                >
                    {{ venues.length ? 'Pick a venue built in CrowdCAD' : 'No venues in CrowdCAD yet' }}
                </option>
                <option
                    v-for='v in venues'
                    :key='v.id'
                    :value='v.id'
                >
                    {{ v.name }} · {{ v.posts }} posts{{ v.mapped ? '' : ' · not on the map' }}
                </option>
            </select>
            <div
                v-if='venue && !venue.mapped'
                class='small text-warning mb-2'
            >
                This venue has no GeoJSON-imported map, so its calls and teams won’t appear on the TAK map
                (only in “Not on the map”). Import a GIS map for it in CrowdCAD first.
            </div>
            <div
                v-else
                class='mb-2'
            />

            <div class='d-flex align-items-center mb-1'>
                <label class='form-label mb-0'>Units from your TAK contacts</label>
                <span class='ms-auto small text-secondary'>{{ picked.length }} picked</span>
            </div>
            <input
                v-model='filter'
                class='form-control form-control-sm mb-1'
                placeholder='Filter callsigns'
            >
            <div
                class='border rounded mb-2'
                style='max-height: 40vh; overflow-y: auto;'
            >
                <div
                    v-if='!contactRows.length'
                    class='small text-secondary p-2'
                >
                    {{ contacts.length ? 'No contact matches.' : 'No TAK contacts visible to you right now.' }}
                </div>
                <div
                    v-for='row in contactRows'
                    :key='row.uid'
                    class='d-flex align-items-center gap-1 px-2 py-1 border-bottom'
                >
                    <input
                        :id='"cc-pick-" + row.uid'
                        v-model='row.picked'
                        type='checkbox'
                        class='form-check-input mt-0'
                    >
                    <label
                        :for='"cc-pick-" + row.uid'
                        class='text-truncate small flex-grow-1'
                        :title='row.uid'
                    >
                        {{ row.callsign }}
                        <span
                            v-if='row.team'
                            class='text-secondary'
                        >· {{ row.team }}</span>
                    </label>
                    <template v-if='row.picked'>
                        <select
                            v-model='row.kind'
                            class='form-select form-select-sm'
                            style='width: 8.5em;'
                            title='CrowdCAD unit type'
                        >
                            <option value='team'>
                                Team
                            </option>
                            <option value='supervisor'>
                                Supervisor
                            </option>
                        </select>
                        <input
                            v-model='row.name'
                            class='form-control form-control-sm'
                            style='width: 9em;'
                            maxlength='80'
                            title='Unit name in CrowdCAD'
                        >
                    </template>
                </div>
            </div>
            <div class='small text-secondary mb-2'>
                Each contact becomes one CrowdCAD unit carried by that device: its position report is the unit on the
                map, and dispatch assignments alert that phone (ATAK CrowdCAD plugin). Every CrowdCAD user can dispatch
                the event.
            </div>

            <button
                class='btn btn-primary btn-sm w-100'
                type='submit'
                :disabled='saving || !canSubmit'
            >
                {{ saving ? 'Creating…' : `Create event with ${picked.length} unit${picked.length === 1 ? '' : 's'}` }}
            </button>
        </form>
    </MenuTemplate>
</template>

<script setup lang='ts'>
// CloudTAK's New event form: name, date, a venue built in CrowdCAD, and TAK contacts picked as
// teams or supervisors. The bridge's manage API writes the event in CrowdCAD's own shape
// (bridge/crowdcad_tak/manage.py); then the dispatcher opens on it.
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import MenuTemplate from '../../../src/components/CloudTAK/util/MenuTemplate.vue';
import * as crowdcad from '../lib/client.ts';
import { selectEvent } from '../lib/store.ts';
import type { TakContact, VenueSummary } from '../lib/types.ts';

interface Row extends TakContact {
    picked: boolean;
    kind: 'team' | 'supervisor';
    name: string;
}

const router = useRouter();
const loading = ref(true);
const saving = ref(false);
const error = ref<string | null>(null);

const name = ref('');
const date = ref(new Date().toLocaleDateString('en-CA'));   // YYYY-MM-DD, local day
const venueId = ref('');
const venues = ref<VenueSummary[]>([]);
const contacts = ref<Row[]>([]);
const filter = ref('');

const venue = computed(() => venues.value.find((v) => v.id === venueId.value) ?? null);
const picked = computed(() => contacts.value.filter((c) => c.picked));
const contactRows = computed(() => {
    const f = filter.value.trim().toLowerCase();
    // Picked contacts stay visible whatever the filter, so a choice can't silently hide.
    return contacts.value.filter((c) => c.picked || !f || c.callsign.toLowerCase().includes(f));
});
const canSubmit = computed(() => name.value.trim() && venueId.value && picked.value.length
    && picked.value.every((c) => c.name.trim()));

function errorText(err: unknown): string {
    return err instanceof Error ? err.message : String(err);
}

onMounted(async () => {
    try {
        const [v, c] = await Promise.all([crowdcad.venues(), crowdcad.contacts()]);
        venues.value = v;
        if (v.length === 1) venueId.value = v[0].id;
        contacts.value = c
            .filter((x) => x.uid && x.callsign)
            .sort((a, b) => a.callsign.localeCompare(b.callsign))
            .map((x) => ({ ...x, picked: false, kind: 'team', name: x.callsign }));
    } catch (err) {
        error.value = errorText(err);
    } finally {
        loading.value = false;
    }
});

async function submit(): Promise<void> {
    const names = new Set<string>();
    for (const unit of picked.value) {
        const key = unit.name.trim().toLowerCase();
        if (names.has(key)) {
            error.value = `Two units are named “${unit.name.trim()}” — CrowdCAD needs unique names.`;
            return;
        }
        names.add(key);
    }
    saving.value = true;
    error.value = null;
    try {
        const created = await crowdcad.createEvent({
            name: name.value.trim(),
            date: date.value,
            venueId: venueId.value,
            units: picked.value.map((c) => ({ name: c.name.trim(), kind: c.kind, uid: c.uid, callsign: c.callsign })),
        });
        // Straight back to the dispatcher, on the new event.
        selectEvent(created.id);
        await router.push({ name: 'home-menu-plugin-crowdcad' });
    } catch (err) {
        error.value = errorText(err);
    } finally {
        saving.value = false;
    }
}
</script>
