// WebTAK entry point. Registers a sidebar tool + docked side drawer through WebTAK 4.10's
// plugin API (window.WebTAK.plugin.registerPlugin with Tool and Drawer model instances) — the
// shape WebTAK-Plugin-Channels read out of WebTAK 4.10.2's shipped bundle and runs in
// production. A 1-argument Drawer mount(container) is WebTAK's plain-DOM mode.
//
// Registration is wrapped so a different WebTAK build can only fall back to a floating launch
// button, never blank WebTAK (the grey-screen incident the Video Viewer plugin hit).

import board from './src/core.js';
import { BoardPanel } from './src/ui.js';
import { injectStyles } from './src/styles.js';

const LOG = '[WebTAK CrowdCAD]';
const PLUGIN_ID = 'crowdcad-board';
const VERSION = '__CROWDCAD_TAK_VERSION__';

// 24x24 ambulance glyph, so we don't depend on WebTAK's icon font names.
const ICON_URL = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="#D5D5D5" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M5 17H3V6a1 1 0 0 1 1-1h9v12M9 17h6m4 0h2v-6h-8m0-5h5l3 5M6 10h4M8 8v4"/></svg>');

function buildDrawer(drawerApi) {
  if (!drawerApi || !drawerApi.models || !drawerApi.models.Drawer) return null;
  let content = null;
  return new drawerApi.models.Drawer({
    name: PLUGIN_ID,
    displayName: 'CrowdCAD',
    orientation: 'side',
    mount: (container) => {
      injectStyles();
      content = new BoardPanel(container);
    },
    unmount: () => {
      content?.destroy();
      content = null;
    },
  });
}

function registerWithWebTAK() {
  try {
    const toolApi = window.WebTAK && window.WebTAK.tool;
    const pluginApi = window.WebTAK && window.WebTAK.plugin;
    const drawerApi = window.WebTAK && window.WebTAK.drawer;
    if (!toolApi || !pluginApi) return false;
    if (pluginApi.hasPlugin(PLUGIN_ID)) return true;

    const drawer = buildDrawer(drawerApi);
    const tool = new toolApi.models.Tool({
      category: 'other',
      iconUrl: ICON_URL,
      name: PLUGIN_ID,
      title: 'CrowdCAD',
      deviceTypes: 'all',
      onClick: () => (drawer ? drawer.open() : board.open()),
    });
    pluginApi.registerPlugin(new pluginApi.models.Plugin({
      name: PLUGIN_ID,
      description: 'Live CrowdCAD medical calls and team status; Dispatch opens CrowdCAD.',
      version: VERSION.startsWith('__') ? '0.0.0' : VERSION,
      tools: [tool],
      drawers: drawer ? [drawer] : [],
    }));
    const ok = pluginApi.hasPlugin(PLUGIN_ID);
    if (ok && drawer) board.setDrawerOpener(() => drawer.open());
    return ok;
  } catch (e) {
    console.warn(LOG, 'sidebar/drawer registration failed, falling back to floating panel:', e);
    return false;
  }
}

function boot() {
  board.mount();
  if (registerWithWebTAK()) {
    console.info(LOG, 'Registered as a WebTAK sidebar tool + docked drawer.');
  } else {
    board.showLaunchButton();
    console.info(LOG, 'Using floating launch button (sidebar/drawer registration unavailable).');
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot);
} else {
  boot();
}

export default board;
