/* eslint-disable */
// CrowdCAD for TAK — CloudTAK server half (copied to <CloudTAK>/api/routes/plugin-crowdcad.ts,
// or api/stateless/routes/ on 13.1xx+; cloudtak/install.sh rewrites the imports for that layout).
//
// Relays the panel's board request to the CrowdCAD bridge with the board token, which never
// reaches the browser. Read-only: the bridge has no write API (docs/API.md).
//
// Configuration comes from CROWDCAD_TAK_URL / CROWDCAD_TAK_TOKEN, which cloudtak/install.sh
// merges into <CloudTAK>/api/.env (JSON, loaded at startup, git-ignored), so no core CloudTAK
// file is edited and infra-TAK's CloudTAK updates leave it in place.

import { Type } from '@sinclair/typebox';
import Schema from '@openaddresses/batch-schema';
import Err from '@openaddresses/batch-error';
import Auth from '../lib/auth.js';
import Config from '../lib/config.js';

const TIMEOUT_MS = 10_000;

async function relay(path: string, withToken: boolean): Promise<unknown> {
    const url = String(process.env.CROWDCAD_TAK_URL || '').replace(/\/+$/, '');
    const token = String(process.env.CROWDCAD_TAK_TOKEN || '');
    if (!url || !token) {
        throw new Err(503, null, 'CrowdCAD is not configured on this CloudTAK server — run the CrowdCAD installer with --cloudtak.');
    }
    let response: Response;
    try {
        response = await fetch(`${url}/api/v1${path}`, {
            headers: withToken ? { Authorization: `Bearer ${token}` } : {},
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
        description: 'API version of the connected CrowdCAD bridge',
        res: Type.Any(),
    }, async (req, res) => {
        try {
            await Auth.as_user(config, req);
            res.json(await relay('/info', false));
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
            res.json(await relay('/board', true));
        } catch (err) {
            Err.respond(err, res);
        }
    });
}
