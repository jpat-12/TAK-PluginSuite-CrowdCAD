package com.atakmap.android.crowdcad;

import android.content.Context;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.Log;

/**
 * The assignment alarm: an alarm tone at full alarm volume and hard vibration, for five seconds.
 * An assignment a medic doesn't notice is a patient waiting, so it plays on the ALARM stream,
 * which the ringer's silent / vibrate mode doesn't mute; the alarm volume is raised to max for
 * the five seconds and put back after. (Do Not Disturb set to block alarms still wins: that's the
 * user's explicit choice and Android gives a plugin no way past it.) No new permission: VIBRATE
 * is already declared; alarm volume and playback need none.
 */
final class AssignmentAlarm {

    static final long DURATION_MS = 5_000;
    // Hard, near-continuous buzzing: 900 ms on / 100 ms off, five times (5 s).
    private static final long[] TIMINGS = {0, 900, 100, 900, 100, 900, 100, 900, 100, 900};
    private static final int[] AMPLITUDES = {0, 255, 0, 255, 0, 255, 0, 255, 0, 255};

    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static MediaPlayer playing;    // UI thread only
    private static int restoreVolume = -1;

    private AssignmentAlarm() {
    }

    /** UI thread. A second assignment during the alarm restarts it. */
    static void fire(Context ctx) {
        stop(ctx);
        AudioAttributes alarm = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
        AudioManager audio = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
        if (audio != null) {
            try {
                restoreVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM);
                audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
            } catch (SecurityException e) {     // DND policy: play at the user's alarm volume
                restoreVolume = -1;
                Log.w(CrowdCadMapComponent.TAG, "alarm volume not raised", e);
            }
        }
        try {
            MediaPlayer mp = new MediaPlayer();
            mp.setAudioAttributes(alarm);
            mp.setDataSource(ctx, tone());
            mp.setLooping(true);
            mp.prepare();
            mp.start();
            playing = mp;
        } catch (Exception e) {
            Log.w(CrowdCadMapComponent.TAG, "alarm tone failed; vibration only", e);
        }
        Vibrator vibrator = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
        if (vibrator != null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
                vibrator.vibrate(VibrationEffect.createWaveform(TIMINGS, AMPLITUDES, -1), alarm);
            else
                vibrator.vibrate(TIMINGS, -1);
        }
        UI.postDelayed(() -> stop(ctx), DURATION_MS);
    }

    /** UI thread: silence it and put the alarm volume back. */
    static void stop(Context ctx) {
        UI.removeCallbacksAndMessages(null);
        if (playing != null) {
            try {
                playing.stop();
            } catch (IllegalStateException e) {
                // already stopped
            }
            playing.release();
            playing = null;
        }
        if (restoreVolume >= 0) {
            AudioManager audio = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
            try {
                if (audio != null)
                    audio.setStreamVolume(AudioManager.STREAM_ALARM, restoreVolume, 0);
            } catch (SecurityException e) {
                // DND policy changed meanwhile: leave it
            }
            restoreVolume = -1;
        }
    }

    private static Uri tone() {
        Uri uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM);
        if (uri == null)
            uri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
        return uri != null ? uri : RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
    }
}
