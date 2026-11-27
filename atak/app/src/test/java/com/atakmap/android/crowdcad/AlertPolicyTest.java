package com.atakmap.android.crowdcad;

import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.atakmap.android.crowdcad.model.AlertPolicy;

import org.junit.Test;

/** Tracker R35: only a debug build can mute the assignment alert; a release always alerts. */
public class AlertPolicyTest {

    @Test
    public void releaseBuildAlwaysAlertsEvenIfMuteWasSaved() {
        assertTrue(AlertPolicy.shouldAlert(false, true));
        assertTrue(AlertPolicy.shouldAlert(false, false));
    }

    @Test
    public void debugBuildAlertsUnlessTheTesterMutedIt() {
        assertTrue(AlertPolicy.shouldAlert(true, false));
        assertFalse(AlertPolicy.shouldAlert(true, true));
    }
}
