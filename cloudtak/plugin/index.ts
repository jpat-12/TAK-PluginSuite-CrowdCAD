// CrowdCAD for TAK — CloudTAK plugin entry. Lands at <CloudTAK>/api/web/plugins/crowdcad/index.ts
// (or app/plugins/crowdcad/ on 13.1xx+), found by CloudTAK's `plugins/*/index.ts` build glob.
//
// The CrowdCAD dispatcher (CrowdCadPanel.vue): the live event's Calls, Teams and Supervisors in
// CrowdCAD's own words, a call screen with the units around it and the closest teams to assign,
// and Add Call / Add Team / Add Supervisor — each written by the bridge with CrowdCAD's own
// handlers. "CrowdCAD ↗" still opens CrowdCAD's own dispatch screen in a floating pane
// (DispatchFrame.vue). Markers arrive as ordinary CoT from TAK Server; this plugin draws none.
//
// Lifecycle (AGENTS.md §2): routes in install() only; enable()/disable() add/remove just the
// menu item — disable() runs before the first enable().
import type { App } from 'vue';
import { markRaw } from 'vue';
import type { MenuItemConfig, PluginAPI, PluginInstance } from '@tak-ps/cloudtak';
import { IconAmbulance } from '@tabler/icons-vue';
import CrowdCadPanel from './components/CrowdCadPanel.vue';
import NewEventPanel from './components/NewEventPanel.vue';
import { setPluginApi } from './lib/plugin-api.ts';

const MENU_KEY = 'plugin-crowdcad';
const ROUTE_NAME = 'home-menu-plugin-crowdcad';

export default class CrowdCadPlugin implements PluginInstance {
    api: PluginAPI;

    constructor(api: PluginAPI) {
        this.api = api;
    }

    static async install(app: App, api: PluginAPI): Promise<CrowdCadPlugin> {
        void app;
        setPluginApi(api);
        api.routes.add({ path: 'plugin-crowdcad', name: ROUTE_NAME, component: markRaw(CrowdCadPanel) }, 'home-menu');
        api.routes.add({ path: 'plugin-crowdcad-new', name: `${ROUTE_NAME}-new`, component: markRaw(NewEventPanel) }, 'home-menu');
        return new CrowdCadPlugin(api);
    }

    async enable(): Promise<void> {
        this.api.menu.add({
            key: MENU_KEY,
            label: 'CrowdCAD',
            route: ROUTE_NAME,
            tooltip: 'CrowdCAD dispatch: calls and teams',
            description: 'CrowdCAD dispatch: Calls, Teams, Add Call, Add Team, units around a call',
            icon: markRaw(IconAmbulance) as unknown as MenuItemConfig['icon'],
        } as MenuItemConfig);
    }

    async disable(): Promise<void> {
        try {
            this.api.menu.remove(MENU_KEY);
        } catch {
            /* map not loaded yet — nothing to remove */
        }
    }
}
