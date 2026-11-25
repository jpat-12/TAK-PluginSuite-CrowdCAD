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
                Add Call
            </div>
        </div>
        <div
            v-if='error'
            class='alert alert-danger py-2 mb-2 small'
        >
            {{ error }}
        </div>

        <div class='subheader mb-1'>
            Location
        </div>
        <LocationEditor
            v-model='draft'
            :posts='view.posts'
            :w3w='Boolean(view.w3w)'
        />

        <label class='form-label mb-1 mt-2 small'>Chief Complaint</label>
        <input
            v-model='chiefComplaint'
            class='form-control form-control-sm mb-1'
            maxlength='120'
            placeholder='e.g. Fall, chest pain (no names, age or sex)'
        >
        <label class='form-label mb-1 small'>Source</label>
        <input
            v-model='source'
            class='form-control form-control-sm mb-1'
            maxlength='60'
            placeholder='Who called it in (e.g. Event Services)'
        >
        <div class='d-flex align-items-center gap-2 mb-2'>
            <label class='form-check mb-0 small'>
                <input
                    v-model='priority'
                    type='checkbox'
                    class='form-check-input'
                > Mark as Priority
            </label>
            <select
                v-model='assign'
                class='form-select form-select-sm ms-auto'
                style='width: 12em;'
                aria-label='Assign Team'
            >
                <option value=''>
                    Assign Team (optional)
                </option>
                <option
                    v-for='u in freeUnits'
                    :key='u.name'
                    :value='u.name'
                >
                    {{ u.name }} ({{ u.status || '—' }})
                </option>
            </select>
        </div>
        <div class='d-flex gap-1'>
            <button
                class='btn btn-primary btn-sm flex-grow-1'
                type='submit'
                :disabled='busy'
            >
                Submit
            </button>
            <button
                class='btn btn-outline-secondary btn-sm'
                type='button'
                @click='$emit("close")'
            >
                Cancel
            </button>
        </div>
        <div class='small text-secondary mt-2'>
            A map point becomes the call’s CrowdCAD location (“lat, lon”); the description, floor and
            what3words go in its notes. Saved to CrowdCAD “via CloudTAK”.
        </div>
    </form>
</template>

<script setup lang='ts'>
// CrowdCAD's Add Call (quickcallmodal.tsx: Location, Source, Chief Complaint, Assign Team),
// written by the bridge with CrowdCAD's own handler, plus the TAK location details. Age/Sex is
// deliberately not offered: patient details are entered in CrowdCAD itself, never from TAK.
import { computed, ref } from 'vue';
import LocationEditor from './LocationEditor.vue';
import * as crowdcad from '../lib/client.ts';
import { emptyDraft, toPayload } from '../lib/location.ts';
import { mapCentre } from '../lib/map-pick.ts';
import { act, store } from '../lib/store.ts';
import type { DispatchView } from '../lib/types.ts';

const props = defineProps<{ eventId: string; view: DispatchView }>();
const emit = defineEmits<{ close: []; created: [callId: string | null] }>();

const draft = ref(emptyDraft('post'));
const chiefComplaint = ref('');
const source = ref('');
const priority = ref(false);
const assign = ref('');
const busy = ref(false);
const error = ref('');

// Units not on an open call (CrowdCAD's quick call lists available teams and supervisors).
const freeUnits = computed(() => props.view.units.filter((u) => !props.view.calls.some((c) => c.assigned.includes(u.name))));

async function submit(): Promise<void> {
    const where = toPayload(draft.value, mapCentre());
    if ('error' in where) {
        error.value = where.error;
        return;
    }
    error.value = '';
    busy.value = true;
    let callId: string | null = null;
    const ok = await act(async () => {
        callId = (await crowdcad.newCall(props.eventId, {
            location: where.location,
            chiefComplaint: chiefComplaint.value.trim(),
            priority: priority.value,
            ...(source.value.trim() ? { source: source.value.trim() } : {}),
            ...(assign.value ? { assign: assign.value } : {}),
            details: where.details,
        })).callId;
    });
    busy.value = false;
    if (ok) emit('created', callId);
    else error.value = store.actionError ?? 'CrowdCAD refused the call.';
}
</script>
