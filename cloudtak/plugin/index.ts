// CrowdCAD Dispatch — CloudTAK dispatcher plugin entry point. Built from IU EMS Dispatch
// (TAK-PluginSuite-IndianaUniversity/CloudTAK-Eventcad) as the template; backend: the CrowdCAD bridge.
//
// lifecycle:
//   install()  — register route (once).
//   enable()   — add menu item + start polling the bridge (every map-ready).
//   disable()  — remove menu item + stop polling.
//
// See CloudTAK-Plugin_Development/AGENTS.md §2 for the lifecycle rules. Public API only: the
// board and actions go through the bridge (lib/bridge.ts), not CloudTAK's feature DB.

import type { App } from 'vue';
import { markRaw } from 'vue';
import type { PluginAPI, PluginInstance, MenuItemConfig } from '@tak-ps/cloudtak';
import { IconAmbulance } from '@tabler/icons-vue';
import CadApp from './components/App.vue';
import { initPluginApi } from './lib/plugin-api.ts';
import { startPolling, stopPolling } from './lib/bridge.ts';

const MENU_KEY   = 'plugin-crowdcad';
const ROUTE_NAME = 'home-menu-plugin-crowdcad';

export default class CrowdCadDispatchPlugin implements PluginInstance {
    api: PluginAPI;

    constructor(api: PluginAPI) {
        this.api = api;
    }

    static async install(app: App, api: PluginAPI): Promise<CrowdCadDispatchPlugin> {
        void app;
        initPluginApi(api);
        // Route registered once and kept — disable() removes only the menu item (not the route),
        // because CloudTAK fires disable() before the first enable() with the map not yet loaded.
        api.routes.add(
            { path: 'plugin-crowdcad', name: ROUTE_NAME, component: markRaw(CadApp) },
            'home-menu',
        );
        return new CrowdCadDispatchPlugin(api);
    }

    async enable(): Promise<void> {
        startPolling();
        this.api.menu.add({
            key:         MENU_KEY,
            label:       'CrowdCAD Dispatch',
            route:       ROUTE_NAME,
            tooltip:     'CrowdCAD Event Dispatcher',
            description: 'Assign medics to CrowdCAD calls, track responses',
            icon:        markRaw(IconAmbulance),
        } as MenuItemConfig);
    }

    async disable(): Promise<void> {
        stopPolling();
        try { this.api.menu.remove(MENU_KEY); } catch { /* map not loaded yet */ }
    }
}
