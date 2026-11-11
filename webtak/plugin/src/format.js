// Pure display helpers shared by the panel (and unit-tested in ../../test). Labels and colours
// mean the same on every client: red = a call with no unit.

export const INCIDENT = {
  NEW: { label: 'New', color: '#ff5c5c' },
  DISP: { label: 'Dispatched', color: '#ffa94d' },
  ONSC: { label: 'On scene', color: '#ffd43b' },
  TRAN: { label: 'Transporting', color: '#5c9dff' },
};

export const UNIT = {
  AVL: { label: 'Available', color: '#24c265' },
  RESP: { label: 'Responding', color: '#ffa94d' },
  ONSC: { label: 'On scene', color: '#ffd43b' },
  TRAN: { label: 'Transporting', color: '#5c9dff' },
  OOS: { label: 'Out of service', color: '#868e96' },
};

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

/** "7m", "1h05" — time since `ms`, never negative (clock skew). */
export function age(ms, now) {
  const minutes = Math.max(0, Math.floor((now - ms) / 60000));
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h${String(minutes % 60).padStart(2, '0')}`;
}

/** One-line warning about the bridge's own health, or null. */
export function bridgeWarning(bridge) {
  if (!bridge) return null;
  if (bridge.crowdcad === 'down') return 'The bridge can’t reach CrowdCAD — this board may be out of date.';
  if (bridge.crowdcad === 'polling') return 'CrowdCAD realtime unavailable — updates every ~30 s.';
  if (bridge.tak === false) return 'The bridge isn’t connected to TAK Server — map markers may be stale.';
  return null;
}

/** The event to show: the chosen one if still live, else the first. */
export function pickEvent(board, chosenId) {
  const events = (board && board.events) || [];
  return events.find((e) => e.id === chosenId) || events[0] || null;
}
