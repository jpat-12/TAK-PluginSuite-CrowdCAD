<template>
    <form
        class='px-2 py-2'
        @submit.prevent='submit'
    >
        <div class='d-flex align-items-center mb-2'>
            <button
                type='button'
                class='btn btn-sm btn-outline-secondary me-2'
                @click='$emit("close")'
            >
                ◀ Board
            </button>
            <div class='fw-bold'>
                {{ kind === 'team' ? 'Add Team' : 'Add Supervisor' }}
            </div>
        </div>
        <div
            v-if='error'
            class='alert alert-danger py-2 mb-2 small'
        >
            {{ error }}
        </div>

        <template v-if='kind === "team"'>
            <label class='form-label mb-1 small'>Team Name</label>
            <input
                v-model='name'
                class='form-control form-control-sm mb-2'
                maxlength='80'
                required
            >
            <div class='subheader mb-1'>
                Members
            </div>
            <div
                v-for='(m, i) in members'
                :key='i'
                class='d-flex align-items-center gap-1 mb-1'
            >
                <input
                    v-model='m.name'
                    class='form-control form-control-sm'
                    maxlength='80'
                    placeholder='Member name'
                    aria-label='Member name'
                >
                <input
                    v-model='m.cert'
                    class='form-control form-control-sm'
                    style='width: 7em;'
                    maxlength='40'
                    list='crowdcad-certs'
                    placeholder='Certification'
                    aria-label='Certification'
                >
                <label
                    class='form-check mb-0 small text-nowrap'
                    title='Lead'
                >
                    <input
                        v-model='m.lead'
                        type='checkbox'
                        class='form-check-input'
                    > Lead
                </label>
                <button
                    type='button'
                    class='btn btn-sm btn-ghost-secondary px-1'
                    aria-label='Remove member'
                    @click='members.splice(i, 1)'
                >
                    ✕
                </button>
            </div>
            <datalist id='crowdcad-certs'>
                <option
                    v-for='c in CERTS'
                    :key='c'
                    :value='c'
                />
            </datalist>
            <button
                type='button'
                class='btn btn-sm btn-outline-secondary mb-2'
                @click='members.push({ name: "", cert: members.at(-1)?.cert || CERTS[0], lead: false })'
            >
                + Add member
            </button>
        </template>

        <template v-else>
            <label class='form-label mb-1 small'>Supervisor Call Sign</label>
            <input
                v-model='name'
                class='form-control form-control-sm mb-1'
                maxlength='80'
                placeholder='The radio call sign, not a person’s name'
                required
            >
            <label class='form-label mb-1 small'>Certification</label>
            <input
                v-model='cert'
                class='form-control form-control-sm mb-1'
                maxlength='40'
                list='crowdcad-certs'
                required
            >
            <datalist id='crowdcad-certs'>
                <option
                    v-for='c in CERTS'
                    :key='c'
                    :value='c'
                />
            </datalist>
            <label class='form-label mb-1 small'>Name <span class='text-secondary'>(optional)</span></label>
            <input
                v-model='person'
                class='form-control form-control-sm mb-2'
                maxlength='80'
            >
        </template>

        <label class='form-label mb-1 small'>Carried by TAK contact <span class='text-secondary'>(optional)</span></label>
        <select
            v-model='takUid'
            class='form-select form-select-sm mb-1'
        >
            <option value=''>
                No device (placed at its post)
            </option>
            <option
                v-for='c in contacts'
                :key='c.uid'
                :value='c.uid'
            >
                {{ c.callsign }}
            </option>
        </select>
        <div class='small text-secondary mb-2'>
            With a contact, that phone’s position is the {{ kind }}’s on every map, and an assignment alerts it
            (ATAK CrowdCAD plugin).
        </div>

        <div class='d-flex gap-1'>
            <button
                class='btn btn-primary btn-sm flex-grow-1'
                type='submit'
                :disabled='busy'
            >
                {{ kind === 'team' ? 'Add Team' : 'Create Supervisor' }}
            </button>
            <button
                class='btn btn-outline-secondary btn-sm'
                type='button'
                @click='$emit("close")'
            >
                Cancel
            </button>
        </div>
    </form>
</template>

<script setup lang='ts'>
// CrowdCAD's Add Team (addteammodal.tsx: Team Name, members "Name [Cert] (Lead)") and Add
// Supervisor (addsupervisormodal.tsx: Supervisor Call Sign, Certification, optional name), written
// by the bridge with CrowdCAD's own handlers. Optionally tied to a TAK contact's device.
import { onMounted, ref } from 'vue';
import * as crowdcad from '../lib/client.ts';
import { nextTeamName } from '../lib/core.ts';
import { act, store } from '../lib/store.ts';
import type { DispatchView, TakContact } from '../lib/types.ts';

const props = defineProps<{ eventId: string; view: DispatchView; kind: 'team' | 'supervisor' }>();
const emit = defineEmits<{ close: []; added: [] }>();

// Suggestions only (CrowdCAD's roles are per-organisation); any text is accepted.
const CERTS = ['EMT', 'Paramedic', 'EMR', 'RN', 'MD', 'First Aid'];

const name = ref(props.kind === 'team'
    ? nextTeamName(props.view.units.filter((u) => u.kind === 'team').map((u) => u.name)) : '');
const members = ref<{ name: string; cert: string; lead: boolean }[]>([{ name: '', cert: CERTS[0], lead: true }]);
const cert = ref('');
const person = ref('');
const takUid = ref('');
const contacts = ref<TakContact[]>([]);
const busy = ref(false);
const error = ref('');

onMounted(async () => {
    try {
        const taken = new Set(props.view.units.map((u) => u.device).filter(Boolean));
        contacts.value = (await crowdcad.contacts())
            .filter((c) => c.uid && !taken.has(c.uid))
            .sort((a, b) => a.callsign.localeCompare(b.callsign));
    } catch { /* contacts unavailable: a team without a device is still a team */ }
});

async function submit(): Promise<void> {
    error.value = '';
    busy.value = true;
    const device = takUid.value ? { takUid: takUid.value } : {};
    const ok = await act(() => props.kind === 'team'
        ? crowdcad.addTeam(props.eventId, {
            name: name.value.trim(),
            members: members.value.filter((m) => m.name.trim()).map((m) => ({ ...m, name: m.name.trim(), cert: m.cert.trim() })),
            ...device,
        })
        : crowdcad.addSupervisor(props.eventId, {
            callSign: name.value.trim(), cert: cert.value.trim(),
            ...(person.value.trim() ? { name: person.value.trim() } : {}), ...device,
        }));
    busy.value = false;
    if (ok) emit('added');
    else error.value = store.actionError ?? 'CrowdCAD refused it.';
}
</script>
