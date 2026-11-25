/* eslint-disable */
// CrowdCAD for TAK — CloudTAK server half (copied to <CloudTAK>/api/routes/plugin-crowdcad.ts,
// or api/stateless/routes/ on 13.1xx+; cloudtak/install.sh rewrites the imports for that layout).
//
// Relays the panel's requests to the CrowdCAD bridge with tokens that never reach the browser:
//   board token  → /info, /board                  (read-only board, docs/API.md)
//   manage token → /venues, /events, /events/:id/end   (New event form: create an event from TAK
//                  contacts, end one created that way; the bridge's manage.py), and
//                  /events/:id/dispatch, /calls, /calls/:cid/{assign,status}, /units/{status,post}
//                  (native dispatch: CrowdCAD's own dispatch actions, ported in the bridge's
//                  dispatch.py and written compare-and-swap). The CloudTAK username goes along as
//                  X-TAK-User and lands in CrowdCAD's call/team logs ("via CloudTAK: <user>").
//
// Configuration comes from CROWDCAD_TAK_URL / CROWDCAD_TAK_TOKEN / CROWDCAD_TAK_MANAGE_TOKEN,
// which cloudtak/install.sh merges into <CloudTAK>/api/.env (JSON, loaded at startup,
// git-ignored), so no core CloudTAK file is edited and infra-TAK's CloudTAK updates leave it.

import { Type } from '@sinclair/typebox';
import Schema from '@openaddresses/batch-schema';
import Err from '@openaddresses/batch-error';
import Auth from '../lib/auth.js';
import Config from '../lib/config.js';

const TIMEOUT_MS = 15_000;
const EventParams = Type.Object({ eventid: Type.String({ pattern: '^[a-z0-9]{15}$' }) });
const CallParams = Type.Object({
    eventid: Type.String({ pattern: '^[a-z0-9]{15}$' }),
    callid: Type.String({ pattern: '^[A-Za-z0-9_-]{1,40}$' }),
});

type TokenKind = 'none' | 'board' | 'manage';

async function relay(path: string, kind: TokenKind, opts: { method?: string; body?: unknown; user?: string } = {}): Promise<unknown> {
    const url = String(process.env.CROWDCAD_TAK_URL || '').replace(/\/+$/, '');
    const board = String(process.env.CROWDCAD_TAK_TOKEN || '');
    const manage = String(process.env.CROWDCAD_TAK_MANAGE_TOKEN || '');
    if (!url || !board) {
        throw new Err(503, null, 'CrowdCAD is not configured on this CloudTAK server — run the CrowdCAD installer with --cloudtak.');
    }
    if (kind === 'manage' && !manage) {
        throw new Err(503, null, 'Creating events from CloudTAK is not set up — re-run the CrowdCAD installer with --cloudtak.');
    }
    const headers: Record<string, string> = {};
    if (kind === 'board') headers.Authorization = `Bearer ${board}`;
    if (kind === 'manage') headers.Authorization = `Bearer ${manage}`;
    if (opts.user) headers['X-TAK-User'] = opts.user;
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    let response: Response;
    try {
        response = await fetch(`${url}/api/v1${path}`, {
            method: opts.method || 'GET',
            headers,
            body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
            signal: AbortSignal.timeout(TIMEOUT_MS),
        });
    } catch (err) {
        throw new Err(502, err instanceof Error ? err : null, `CrowdCAD bridge unreachable at ${url}`);
    }
    const text = await response.text();
    let data: any = {};
    try {
        data = text ? JSON.parse(text) : {};
    } catch {
        data = { error: text.slice(0, 200) };
    }
    if (!response.ok) {
        throw new Err(response.status, null, data && data.error ? String(data.error) : `CrowdCAD bridge returned HTTP ${response.status}`);
    }
    return data;
}

export default async function router(schema: Schema, config: Config) {
    await schema.get('/plugin-crowdcad/info', {
        name: 'CrowdCAD Info',
        group: 'PluginCrowdCAD',
        description: 'API version of the connected CrowdCAD bridge, and whether events can be created from CloudTAK',
        res: Type.Any(),
    }, async (req, res) => {
        try {
            await Auth.as_user(config, req);
            const info = await relay('/info', 'none') as Record<string, unknown>;
            res.json({ ...info, manage: Boolean(process.env.CROWDCAD_TAK_MANAGE_TOKEN) });
        } catch (err) {
            Err.respond(err, res);
        }
    });

    await schema.get('/plugin-crowdcad/board', {
        name: 'CrowdCAD Board',
        group: 'PluginCrowdCAD',
        description: 'Open calls and teams of every live CrowdCAD event (no patient data)',
        res: Type.Any(),
    }, async (req, res) => {
        try {
            await Auth.as_user(config, req);
            res.json(await relay('/board', 'board'));
        } catch (err) {
            Err.respond(err, res);
        }
    });

    await schema.get('/plugin-crowdcad/venues', {
        name: 'CrowdCAD Venues',
        group: 'PluginCrowdCAD',
        description: 'Venues built in CrowdCAD, for the New event form',
        res: Type.Any(),
    }, async (req, res) => {
        try {
            const user = await Auth.as_user(config, req);
            res.json(await relay('/manage/venues', 'manage', { user: user.email }));
        } catch (err) {
            Err.respond(err, res);
        }
    });

    await schema.post('/plugin-crowdcad/events', {
        name: 'CrowdCAD Create Event',
        group: 'PluginCrowdCAD',
        description: 'Create a CrowdCAD event whose teams and supervisors are TAK contacts',
        body: Type.Any(),
        res: Type.Any(),
    }, async (req, res) => {
        try {
            const user = await Auth.as_user(config, req);
            res.json(await relay('/manage/events', 'manage', { method: 'POST', body: req.body, user: user.email }));
        } catch (err) {
            Err.respond(err, res);
        }
    });

    await schema.get('/plugin-crowdcad/events/:eventid/dispatch', {
        name: 'CrowdCAD Dispatch View',
        group: 'PluginCrowdCAD',
        description: 'Units, open calls, posts and clinics of one event, for native dispatch (no patient data)',
        params: EventParams,
        res: Type.Any(),
    }, async (req, res) => {
        try {
            const user = await Auth.as_user(config, req);
            res.json(await relay(`/manage/events/${req.params.eventid}/dispatch`, 'manage', { user: user.email }));
        } catch (err) {
            Err.respond(err, res);
        }
    });

    await schema.post('/plugin-crowdcad/events/:eventid/calls', {
        name: 'CrowdCAD New Call',
        group: 'PluginCrowdCAD',
        description: 'Create a call (location, chief complaint, priority, optional unit)',
        params: EventParams,
        body: Type.Any(),
        res: Type.Any(),
    }, async (req, res) => {
        try {
            const user = await Auth.as_user(config, req);
            res.json(await relay(`/manage/events/${req.params.eventid}/calls`, 'manage', { method: 'POST', body: req.body, user: user.email }));
        } catch (err) {
            Err.respond(err, res);
        }
    });

    for (const action of ['assign', 'status'] as const) {
        await schema.post(`/plugin-crowdcad/events/:eventid/calls/:callid/${action}`, {
            name: action === 'assign' ? 'CrowdCAD Assign Unit' : 'CrowdCAD Unit Status On Call',
            group: 'PluginCrowdCAD',
            description: action === 'assign' ? 'Assign a team or supervisor to a call' : 'Set a unit’s status on its call (incl. closing it)',
            params: CallParams,
            body: Type.Any(),
            res: Type.Any(),
        }, async (req, res) => {
            try {
                const user = await Auth.as_user(config, req);
                res.json(await relay(`/manage/events/${req.params.eventid}/calls/${req.params.callid}/${action}`, 'manage', { method: 'POST', body: req.body, user: user.email }));
            } catch (err) {
                Err.respond(err, res);
            }
        });
    }

    for (const action of ['status', 'post'] as const) {
        await schema.post(`/plugin-crowdcad/events/:eventid/units/${action}`, {
            name: action === 'status' ? 'CrowdCAD Unit Availability' : 'CrowdCAD Unit Post',
            group: 'PluginCrowdCAD',
            description: action === 'status' ? 'Available / On Break / In Clinic for a unit not on a call' : 'Move a unit to a post',
            params: EventParams,
            body: Type.Any(),
            res: Type.Any(),
        }, async (req, res) => {
            try {
                const user = await Auth.as_user(config, req);
                res.json(await relay(`/manage/events/${req.params.eventid}/units/${action}`, 'manage', { method: 'POST', body: req.body, user: user.email }));
            } catch (err) {
                Err.respond(err, res);
            }
        });
    }

    await schema.post('/plugin-crowdcad/events/:eventid/end', {
        name: 'CrowdCAD End Event',
        group: 'PluginCrowdCAD',
        description: 'End a CrowdCAD event that was created from TAK',
        params: EventParams,
        res: Type.Any(),
    }, async (req, res) => {
        try {
            const user = await Auth.as_user(config, req);
            res.json(await relay(`/manage/events/${req.params.eventid}/end`, 'manage', { method: 'POST', body: {}, user: user.email }));
        } catch (err) {
            Err.respond(err, res);
        }
    });
}
