package com.atakmap.android.crowdcad;

import android.content.Context;
import android.preference.PreferenceManager;

/**
 * Whether the plugin adds its bundled iconset to ATAK's icon library at load (tracker R42).
 *
 * Off by default: on some devices ATAK's import of the set never settles and the plugin's
 * "Retry" kept it going in a loop. The plugin doesn't need the iconset to draw anything itself
 * (IncidentStyler and UnitIcons paint base64 PNGs read straight from the APK's asset); the set
 * only lets ATAK resolve {@code <usericon iconsetpath>} the way stock clients do. Turn it on in
 * the CrowdCAD panel's Settings when that's wanted.
 */
final class IconsetPref {

    private static final String PREF = "crowdcad.installIconset";

    private IconsetPref() {
    }

    static boolean enabled(Context ctx) {
        try {
            return PreferenceManager.getDefaultSharedPreferences(ctx).getBoolean(PREF, false);
        } catch (Throwable t) {      // prefs unreadable: don't import (the safe side, see above)
            return false;
        }
    }

    static void set(Context ctx, boolean enabled) {
        PreferenceManager.getDefaultSharedPreferences(ctx).edit().putBoolean(PREF, enabled).apply();
    }
}
