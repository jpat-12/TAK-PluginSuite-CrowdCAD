<template>
    <img
        :src='incidentIcon(priority)'
        :width='size'
        :height='size'
        :alt='"P" + priority'
        :title='"Priority " + priority'
        class='flex-none'
    >
</template>

<script setup lang='ts'>
// The EMS incident icon tinted by priority (P1 red, P2 orange, P3 yellow): the same picture
// ATAK plugin users see on their map.
import { incidentIcon } from '../lib/incident-icon.ts';

withDefaults(defineProps<{ priority: number; size?: number }>(), { size: 26 });
</script>
