// CrowdCAD for TAK — CloudTAK plugin entry. Lands at <CloudTAK>/api/web/plugins/crowdcad/index.ts
// (or app/plugins/crowdcad/ on 13.1xx+), found by CloudTAK's `plugins/*/index.ts` build glob.
//
// A board of the live CrowdCAD event: open calls (priority first), teams and their
// status, and anything CrowdCAD couldn't place on the map. Its Dispatch button opens CrowdCAD's own
// dispatch screen in a floating pane (DispatchFrame.vue), signed in as the dispatcher. The markers themselves arrive as
// ordinary CoT from TAK Server like every other track — this plugin doesn't draw any.
//
// Lifecycle (AGENTS.md §2): routes in install() only; enable()/disable() add/remove just the
// menu item — disable() runs before the first enable().
import type { App } from 'vue';
import { markRaw } from 'vue';
import type { MenuItemConfig, PluginAPI, PluginInstance } from '@tak-ps/cloudtak';
import { IconAmbulance } from '@tabler/icons-vue';
import CrowdCadPanel from './components/CrowdCadPanel.vue';
import NewEventPanel from './components/NewEventPanel.vue';
import DispatchPanel from './components/DispatchPanel.vue';
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
        api.routes.add({ path: 'plugin-crowdcad-dispatch', name: `${ROUTE_NAME}-dispatch`, component: markRaw(DispatchPanel) }, 'home-menu');
        return new CrowdCadPlugin(api);
    }

    async enable(): Promise<void> {
        this.api.menu.add({
            key: MENU_KEY,
            label: 'CrowdCAD',
            route: ROUTE_NAME,
            tooltip: 'Live medical calls and teams',
            description: 'CrowdCAD board (open calls, team status) and CrowdCAD dispatch',
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
