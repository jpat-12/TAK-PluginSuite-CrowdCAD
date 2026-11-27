package com.atakmap.android.crowdcad;

import android.content.Context;
import android.preference.PreferenceManager;

import com.atakmap.android.crowdcad.model.AlertPolicy;
import com.atakmap.android.crowdcad.plugin.BuildConfig;

/**
 * The tester's "mute assignment alert" switch (tracker R35). It exists only in debug builds: the
 * Settings button is shown only when BuildConfig.DEBUG, and {@link #muted} ignores the saved value
 * in a release build, so a TPC-signed release always beeps and buzzes even if the pref was set.
 */
final class AlertMute {

    private static final String PREF = "crowdcad.debugMuteAlert";

    private AlertMute() {
    }

    /** Whether this build offers the switch at all. */
    static boolean available() {
        return BuildConfig.DEBUG;
    }

    /** True only in a debug build whose tester turned the alert off. */
    static boolean muted(Context ctx) {
        return !AlertPolicy.shouldAlert(BuildConfig.DEBUG, saved(ctx));
    }

    static void set(Context ctx, boolean muted) {
        if (!available())
            return;
        PreferenceManager.getDefaultSharedPreferences(ctx).edit().putBoolean(PREF, muted).apply();
    }

    private static boolean saved(Context ctx) {
        try {
            return PreferenceManager.getDefaultSharedPreferences(ctx).getBoolean(PREF, false);
        } catch (Throwable t) {      // prefs unreadable: alert (never fail silent)
            return false;
        }
    }
}
