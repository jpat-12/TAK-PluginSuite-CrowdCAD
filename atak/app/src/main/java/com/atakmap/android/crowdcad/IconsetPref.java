package com.atakmap.android.crowdcad;

import android.content.Context;
import android.preference.PreferenceManager;

/**
 * The opt-out for the plugin adding its bundled iconset to ATAK's icon library (tracker R42).
 *
 * On by default. On ATAK 5.8 the import never settled and Retry looped, so a failure now offers
 * "Stop loading it", which turns this off; the CrowdCAD panel's Settings turns it back on. The
 * plugin's own markers don't need the set (IncidentStyler and UnitIcons paint base64 PNGs read
 * straight from the APK's asset); it only lets ATAK resolve {@code <usericon iconsetpath>}.
 *
 * "Pending" marks an import that was requested but never confirmed. If ATAK hung or was killed
 * mid-import, the next load sees it and asks instead of importing again.
 */
final class IconsetPref {

    private static final String PREF = "crowdcad.installIconset";
    private static final String PENDING = "crowdcad.iconsetImportPending";

    private IconsetPref() {
    }

    static boolean enabled(Context ctx) {
        try {
            return PreferenceManager.getDefaultSharedPreferences(ctx).getBoolean(PREF, true);
        } catch (Throwable t) {      // prefs unreadable: behave as before R42 (try to import)
            return true;
        }
    }

    static void set(Context ctx, boolean enabled) {
        PreferenceManager.getDefaultSharedPreferences(ctx).edit().putBoolean(PREF, enabled).apply();
    }

    static boolean pending(Context ctx) {
        try {
            return PreferenceManager.getDefaultSharedPreferences(ctx).getBoolean(PENDING, false);
        } catch (Throwable t) {
            return false;
        }
    }

    /** commit(), not apply(): it must be on disk before the import that might hang ATAK starts. */
    static void setPending(Context ctx, boolean pending) {
        PreferenceManager.getDefaultSharedPreferences(ctx).edit().putBoolean(PENDING, pending).commit();
    }
}
