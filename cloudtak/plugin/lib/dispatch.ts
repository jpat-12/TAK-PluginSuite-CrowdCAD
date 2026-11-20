// Opens CrowdCAD's own dispatch screen for an event in a CloudTAK floating pane (DispatchFrame.vue).
// CrowdCAD's dispatch screen is laid out for a desktop: open the pane as large as the map allows
// (it stays draggable and resizable). One pane at a time; another event replaces it.
import DispatchFrame from '../components/DispatchFrame.vue';
import { pluginApi } from './plugin-api.ts';

const DISPATCH_PANE = 'plugin-crowdcad-dispatch';

export function openDispatch(url: string, name: string): void {
    if (!/^https:\/\//.test(url)) return;
    const float = pluginApi().float;
    if (float.has(DISPATCH_PANE)) float.remove(DISPATCH_PANE);
    float.add({
        uid: DISPATCH_PANE,
        name: `CrowdCAD dispatch — ${name}`,
        component: DispatchFrame,
        props: { url, name },
        width: Math.max(400, Math.min(1280, window.innerWidth - 140)),
        height: Math.max(300, Math.min(860, window.innerHeight - 110)),
        x: 60,
        y: 70,
    });
}
