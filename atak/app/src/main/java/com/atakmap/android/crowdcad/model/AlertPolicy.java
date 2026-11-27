package com.atakmap.android.crowdcad.model;

/**
 * Whether an assignment sounds the alarm (tracker R35). Testers can mute the beeps and buzz in a
 * DEBUG build only; a release build (the one TPC signs for medics) ALWAYS alerts, whatever the
 * saved preference says: an assignment a medic doesn't notice is a patient waiting.
 */
public final class AlertPolicy {

    private AlertPolicy() {
    }

    /** @param debugBuild BuildConfig.DEBUG; @param muted the tester's debug-only mute preference */
    public static boolean shouldAlert(boolean debugBuild, boolean muted) {
        return !debugBuild || !muted;
    }
}
