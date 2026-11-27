// tracker R3: the ALS / BLS / SUP unit icon each phone sends (<usericon iconsetpath=
// "<CrowdCAD iconset>/CrowdCAD/EMS ALS BUSY.png"/>) actually drawn by CloudTAK, in the status
// colour from the board, instead of the team-colour dot.
//
// Why a rewrite is needed: CloudTAK 13.102 (app/src/base/cot.ts styleProperties/renderedIcon) gives
// every CoT with a <__group> (every ATAK PLI) group + marker-color, so the map's "-group" circle
// layer draws a team skittle and the icon layer asks for "<usericon path>-colored-<team colour>",
// which no iconset resolves: our icon never shows.
//
// Internal reach-in (CloudTAK plugin AGENTS.md §4), re-verify on every CloudTAK upgrade:
// CoT styling runs in the atlas web worker (out of a plugin's reach), but the main thread feeds the
// worker's rendered features to MapLibre's GeoJSON source '-1' (stores/map.ts updateCOT →
// source.updateData(diff); resyncCOT → source.setData). We wrap those two methods on that source
// instance and, only for phones the CrowdCAD board lists, drop group / marker-color /
// marker-stroke-color and set icon = '<iconset uid>:CrowdCAD/EMS <ALS|BLS|SUP> <AVL|OOS|BUSY>'.
// CloudTAK's own icon manager then loads that image from the imported CrowdCAD iconset (v3)
// (stores/modules/icons.ts loadIconsetImage). Rendered features carry the CoT uid in
// properties.id and a numeric id = COT.vectorId(uid) (mirrored below). Disable restores the
// original styling and unwraps the source.
import type { GeoJSONSource } from 'maplibre-gl';
import { getPluginApi } from './plugin-api.ts';
import type { Unit } from './core.ts';

const COT_SOURCE = '-1';
const ICONSET = 'abee9e5e3aec4b62a5bbb27c78fcb9b27e0140919c7ff132c8c6fa41ab2b0c78';   // iconset/build_iconset.py uid
const STALE_MS = 10 * 60_000;              // a phone not heard for 10 min: give the marker back to CloudTAK
// The rendered properties that make a contact a team skittle (base/cot.ts RENDERED_PROPERTIES).
const TEAM_PROPS = ['group', 'marker-color', 'marker-stroke-color', 'icon-opacity'];
const SAVED_PROPS = [...TEAM_PROPS, 'icon'];

type Props = Record<string, unknown>;
interface Feat { id?: number | string; type: string; properties?: Props | null; geometry?: unknown }
interface FeatDiff {
    id: number | string;
    newGeometry?: unknown;
    removeAllProperties?: boolean;
    removeProperties?: string[];
    addOrUpdateProperties?: { key: string; value: unknown }[];
}
interface SourceDiff { removeAll?: boolean; remove?: (number | string)[]; add?: Feat[]; update?: FeatDiff[] }
type SetData = GeoJSONSource['setData'];
type UpdateData = GeoJSONSource['updateData'];

const want = new Map<string, string>();       // CoT uid → icon id it should render with
const applied = new Map<string, string>();    // CoT uid → icon id last pushed into the source
const saved = new Map<string, Props>();       // CoT uid → CloudTAK's own styling props, for restore
const uidOf = new Map<number, string>();      // vector id → CoT uid
let hooked: { source: GeoJSONSource; setData: SetData; updateData: UpdateData } | null = null;

/** Same rule as the ATAK plugin (Roster.colourOf): AVL green, OOS grey, anything else light red. */
export function colourOf(status: string): 'AVL' | 'OOS' | 'BUSY' {
    if (!status || status === 'OOS') return 'OOS';
    return status === 'AVL' ? 'AVL' : 'BUSY';
}

/** CloudTAK's COT.vectorId (base/cot.ts): the numeric feature id of a CoT uid. */
export function vectorId(id: string): number {
    let h = 0;
    for (let i = 0; i < id.length; i++) {
        h = (h << 5) - h + id.charCodeAt(i);
        h |= 0;
    }
    return h >>> 0;
}

export function iconFor(u: Pick<Unit, 'designation' | 'status'>): string {
    return ICONSET + ':CrowdCAD/EMS ' + (u.designation || 'BLS') + ' ' + colourOf(u.status);
}

function remember(uid: string, props: Props): void {
    const keep: Props = saved.get(uid) ?? {};
    for (const k of SAVED_PROPS) if (k in props) keep[k] = props[k];
    saved.set(uid, keep);
}

function patchFeature(f: Feat): Feat {
    const uid = f.properties?.id;
    if (typeof uid !== 'string' || !want.has(uid) || !f.properties) return f;
    remember(uid, f.properties);
    const props: Props = { ...f.properties };
    for (const k of TEAM_PROPS) delete props[k];
    props.icon = want.get(uid);
    applied.set(uid, want.get(uid)!);
    return { ...f, properties: props };
}

function patchDiff(diff: SourceDiff): SourceDiff {
    if (!want.size) return diff;
    const out: SourceDiff = { ...diff };
    if (diff.add) out.add = diff.add.map(patchFeature);
    if (diff.update) {
        out.update = diff.update.map((u) => {
            const uid = uidOf.get(Number(u.id));
            if (!uid || !want.has(uid)) return u;
            const add: { key: string; value: unknown }[] = [];
            const seen: Props = {};
            for (const p of u.addOrUpdateProperties ?? []) {
                if (SAVED_PROPS.includes(p.key)) seen[p.key] = p.value;     // CloudTAK's value: keep for restore
                else add.push(p);
            }
            remember(uid, seen);
            add.push({ key: 'icon', value: want.get(uid) });
            applied.set(uid, want.get(uid)!);
            const remove = [...new Set([...(u.removeProperties ?? []).filter((k) => k !== 'icon'), ...TEAM_PROPS])];
            return { ...u, addOrUpdateProperties: add, removeProperties: remove };
        });
    }
    return out;
}

function patchData(data: unknown): unknown {
    const fc = data as { type?: string; features?: Feat[] };
    if (!want.size || !fc || typeof fc !== 'object' || fc.type !== 'FeatureCollection' || !fc.features) return data;
    return { ...fc, features: fc.features.map(patchFeature) };
}

function cotSource(): GeoJSONSource | null {
    try {
        return (getPluginApi()?.map?.getSource(COT_SOURCE) as GeoJSONSource | undefined) ?? null;
    } catch {
        return null;      // map not ready
    }
}

/** Wrap source '-1' (again, if CloudTAK re-created it on a style change). */
function hook(): boolean {
    const source = cotSource();
    if (!source) return false;
    if (hooked?.source === source) return true;
    const setData = source.setData.bind(source) as SetData;
    const updateData = source.updateData.bind(source) as UpdateData;
    hooked = { source, setData, updateData };
    applied.clear();      // a new source holds CloudTAK's own styling
    source.setData = ((data: unknown) => setData(patchData(data) as Parameters<SetData>[0])) as SetData;
    source.updateData = ((diff: unknown) => updateData(patchDiff(diff as SourceDiff) as Parameters<UpdateData>[0])) as UpdateData;
    // Features already in the source came in before the hook: note their styling for restore.
    void source.getData().then((data) => {
        for (const f of (data as { features?: Feat[] }).features ?? []) {
            const uid = f.properties?.id;
            if (typeof uid === 'string' && want.has(uid) && !applied.has(uid) && f.properties) remember(uid, f.properties);
        }
        sync();
    }).catch((e: unknown) => console.warn('[plugin-crowdcad] unit icons: getData failed', e));
    return true;
}

/** Push what changed: restyle units whose icon changed, give back the ones no longer listed. */
function sync(): void {
    if (!hooked) return;
    const update: FeatDiff[] = [];
    for (const [uid, icon] of want) {
        if (applied.get(uid) === icon) continue;
        if (!saved.has(uid)) continue;           // not in the map yet: patched when CloudTAK adds it
        update.push({ id: vectorId(uid), addOrUpdateProperties: [{ key: 'icon', value: icon }], removeProperties: TEAM_PROPS });
        applied.set(uid, icon);
    }
    for (const uid of [...applied.keys()]) {
        if (want.has(uid)) continue;
        const orig = saved.get(uid) ?? {};
        update.push({
            id: vectorId(uid),
            addOrUpdateProperties: Object.entries(orig).map(([key, value]) => ({ key, value })),
            removeProperties: 'icon' in orig ? [] : ['icon'],
        });
        applied.delete(uid);
    }
    if (!update.length) return;
    hooked.updateData({ update } as Parameters<UpdateData>[0])
        .catch((e: unknown) => console.warn('[plugin-crowdcad] unit icons not applied', e));
}

/** Every board refresh: which phones get which icon (a phone only while it's still reporting). */
export function drawUnitIcons(units: Unit[], now: number): void {
    want.clear();
    for (const u of units) {
        if (!u.device || !u.uid || !u.seen || now - u.seen > STALE_MS) continue;
        want.set(u.uid, iconFor(u));
        uidOf.set(vectorId(u.uid), u.uid);
    }
    try {
        if (hook()) sync();
    } catch (e) {
        console.warn('[plugin-crowdcad] unit icons not drawn', e);
    }
}

/** Plugin disable: CloudTAK's own markers back, source unwrapped. */
export function clearUnitIcons(): void {
    want.clear();
    try {
        sync();
        if (hooked && cotSource() === hooked.source) {
            const src = hooked.source as unknown as Record<string, unknown>;
            delete src.setData;          // own properties set by hook(): the prototype methods return
            delete src.updateData;
        }
    } catch (e) {
        console.warn('[plugin-crowdcad] unit icons not cleared', e);
    }
    hooked = null;
    applied.clear();
}
