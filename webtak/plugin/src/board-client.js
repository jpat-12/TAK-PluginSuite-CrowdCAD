// The bridge's board API (docs/API.md), called straight from the WebTAK page: the bridge's
// cors_origins must list this page's origin (crowdcad_caddy.py seeds the usual ones).

export const SUPPORTED_API = 1;

async function call(bridgeUrl, path, token) {
  const base = (bridgeUrl || '').replace(/\/+$/, '');
  if (!base) throw new Error('No CrowdCAD bridge URL set — open Settings.');
  let response;
  try {
    response = await fetch(`${base}/api/v1${path}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      cache: 'no-store',
    });
  } catch {
    // CORS refusals surface here too, indistinguishable from "host down" by design of fetch().
    throw new Error(`Can't reach the CrowdCAD bridge at ${base} (down, or this origin isn't in its cors_origins).`);
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    /* non-JSON error page */
  }
  if (response.status === 401) throw new Error('The CrowdCAD board token was refused — check Settings.');
  if (!response.ok) throw new Error((data && data.error) || `CrowdCAD bridge returned HTTP ${response.status}`);
  return data;
}

export async function fetchBoard({ bridgeUrl, token }) {
  const board = await call(bridgeUrl, '/board', token);
  if (!board || Math.floor(board.api) !== SUPPORTED_API) {
    throw new Error(`The CrowdCAD bridge speaks API v${board && board.api}; this plugin needs v${SUPPORTED_API}.`);
  }
  return board;
}
