// Calls to this plugin's server half (api/routes/plugin-crowdcad.ts), which relays them to the
// CrowdCAD bridge with the server-side board token.
//
// Internal reach-in (CloudTAK plugin AGENTS.md §4): `std` is CloudTAK's authenticated fetch;
// the public plugin API has no HTTP client. Same import Aleph's plugin uses — re-verify it on
// every CloudTAK upgrade.
import { std } from '../../../src/std.ts';
import type { Board, BridgeInfo } from './types.ts';

// The bridge API major this plugin speaks; refuse others instead of showing a wrong board.
export const SUPPORTED_API = 1;

export async function info(): Promise<BridgeInfo> {
    return await std('/api/plugin-crowdcad/info') as BridgeInfo;
}

export async function board(): Promise<Board> {
    return await std('/api/plugin-crowdcad/board') as Board;
}
