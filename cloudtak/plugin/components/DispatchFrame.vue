<template>
    <div class='d-flex flex-column h-100 w-100'>
        <div class='d-flex align-items-center px-2 py-1 small text-secondary border-bottom'>
            <span class='text-truncate'>
                Signed in to CrowdCAD as yourself · changes are CrowdCAD's own
            </span>
            <a
                class='ms-auto text-nowrap'
                :href='url'
                target='_blank'
                rel='noopener'
            >Open in new window ↗</a>
        </div>
        <iframe
            class='flex-grow-1 w-100 border-0'
            :src='url'
            :title='"CrowdCAD dispatch — " + name'
            allow='clipboard-read; clipboard-write; fullscreen'
            referrerpolicy='strict-origin-when-cross-origin'
        />
    </div>
</template>

<script setup lang='ts'>
// CrowdCAD's own dispatch screen for one event, in a CloudTAK floating pane (CrowdCadPanel.vue
// opens it). Dispatching is CrowdCAD itself — same rules, same sign-in, attributed in its call
// log — so nothing here writes to CrowdCAD. Embeds because CloudTAK's CSP default-src allows
// *.<fqdn> and CrowdCAD sends no X-Frame-Options; "Open in new window" covers anything else.
defineProps<{
    url: string;
    name: string;
}>();
</script>
