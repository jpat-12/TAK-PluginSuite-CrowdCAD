<template>
    <span
        class='crowdcad-badge'
        :class='{ stale }'
        :style='`background:${def.color}`'
        :title='def.label'
    >{{ def.letter }}</span>
</template>

<script setup lang='ts'>
// A unit's status as a coloured letter (A / E / S / T / B), the same colours the ATAK plugin
// uses. A device not heard from for 3 minutes fades.
import type { StatusDef } from '../lib/core.ts';

defineProps<{ def: StatusDef; stale?: boolean }>();
</script>

<style scoped>
.crowdcad-badge {
    display:inline-flex; width:26px; height:26px; border-radius:50%; flex:none;
    align-items:center; justify-content:center; color:#000; font-weight:800; font-size:13px;
}
.stale { opacity:.4; }
</style>
