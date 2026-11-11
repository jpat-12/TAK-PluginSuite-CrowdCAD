// Where the board comes from. install.sh bakes the bridge URL and board token into the bundle
// (replacing the two placeholders below), so operators open WebTAK and it just works. The
// in-panel Settings can override them per browser (localStorage), e.g. for testing.
//
// The token is readable by anyone who can load WebTAK's plugin files — which TAK Server only
// serves to signed-in users. It unlocks a read-only, patient-data-free board, nothing else
// (docs/API.md); rotate it on the console page if a bundle leaks.

const STORAGE_KEY = 'wcad.config.v1';

export const DEFAULTS = {
  bridgeUrl: '__CROWDCAD_TAK_URL__',
  token: '__CROWDCAD_TAK_TOKEN__',
  pollMs: 5000,
};

function baked(value) {
  return value.startsWith('__CROWDCAD_TAK_') ? '' : value;   // placeholder never replaced = unset
}

let current = load();

function load() {
  const base = { ...DEFAULTS, bridgeUrl: baked(DEFAULTS.bridgeUrl), token: baked(DEFAULTS.token) };
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? { ...base, ...JSON.parse(raw) } : base;
  } catch {
    return base;   // private mode / blocked storage: baked values only
  }
}

export function getConfig() {
  return { ...current };
}

export function setConfig(patch) {
  current = { ...current, ...patch };
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ bridgeUrl: current.bridgeUrl, token: current.token }));
  } catch {
    /* private mode / quota — keep in-memory only */
  }
  return getConfig();
}
