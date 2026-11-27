package com.atakmap.android.crowdcad;

import android.content.Context;
import android.content.res.AssetFileDescriptor;
import android.media.AudioAttributes;
import android.media.AudioManager;
import android.media.MediaPlayer;
import android.media.ToneGenerator;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.util.Log;

import com.atakmap.android.crowdcad.model.Roster;

/**
 * The assignment alarm: the dispatcher's chosen sound (soft pulses by default, or hi-lo; set in
 * CloudTAK's Settings, sent in the bridge's roster CoT) looped on the ALARM stream, which the
 * ringer's silent / vibrate mode doesn't mute, plus hard vibration, for five seconds or until the
 * medic taps Acknowledge ({@link #stop}). The alarm volume is raised to max and put back after.
 * Do Not Disturb set to block alarms still wins: Android gives a plugin no way past it. No new
 * permission: VIBRATE is already declared; playback and alarm volume need none.
 *
 * Sounds are res/raw WAVs made by atak/tools/make_alert_sounds.py. If one can't be played, the old
 * ToneGenerator beeps stand in: a medic must never get a silent assignment.
 *
 * Every step is guarded: an alarm that fails must never take ATAK down with it.
 */
final class AssignmentAlarm {

    static final long DURATION_MS = 5_000;
    private static final long BEEP_EVERY_MS = 450;
    private static final int BEEP_MS = 250;
    // Hard, near-continuous buzzing: 900 ms on / 100 ms off, five times (5 s).
    private static final long[] TIMINGS = {0, 900, 100, 900, 100, 900, 100, 900, 100, 900};
    private static final int[] AMPLITUDES = {0, 255, 0, 255, 0, 255, 0, 255, 0, 255};

    private static final Handler UI = new Handler(Looper.getMainLooper());
    private static MediaPlayer player;     // UI thread only
    private static ToneGenerator tones;    // fallback, UI thread only
    private static Vibrator vibrating;
    private static int restoreVolume = -1;
    private static long until;

    private AssignmentAlarm() {
    }

    /** The res/raw sound for a roster alert value ("hilo", else soft pulses). */
    static int soundRes(String sound) {
        return Roster.ALERT_HILO.equals(sound)
                ? com.atakmap.android.crowdcad.plugin.R.raw.alert_hi_lo
                : com.atakmap.android.crowdcad.plugin.R.raw.alert_soft_pulses;
    }

    /**
     * UI thread. A second assignment during the alarm restarts it.
     *
     * @param ctx    ATAK's context (audio, vibrator)
     * @param plugin the plugin's context: the sounds are the plugin's resources, not ATAK's
     * @param sound  {@link Roster#ALERT_SOFT} or {@link Roster#ALERT_HILO}
     */
    static void fire(Context ctx, Context plugin, String sound) {
        try {
            stop(ctx);
            if (AlertMute.muted(ctx)) {      // tracker R35: debug builds only; release always alerts
                Log.i(CrowdCadMapComponent.TAG, "assignment alert muted (debug build, R35)");
                return;
            }
            AudioManager audio = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
            if (audio != null) {
                try {
                    restoreVolume = audio.getStreamVolume(AudioManager.STREAM_ALARM);
                    audio.setStreamVolume(AudioManager.STREAM_ALARM, audio.getStreamMaxVolume(AudioManager.STREAM_ALARM), 0);
                } catch (SecurityException e) {     // DND policy: play at the user's alarm volume
                    restoreVolume = -1;
                }
            }
            until = System.currentTimeMillis() + DURATION_MS;
            if (!playSound(plugin, sound)) {
                tones = new ToneGenerator(AudioManager.STREAM_ALARM, ToneGenerator.MAX_VOLUME);
                UI.post(BEEP);
            }
            Vibrator vibrator = (Vibrator) ctx.getSystemService(Context.VIBRATOR_SERVICE);
            if (vibrator != null) {
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    vibrator.vibrate(VibrationEffect.createWaveform(TIMINGS, AMPLITUDES, -1), alarmAttributes());
                } else {
                    vibrator.vibrate(TIMINGS, -1);
                }
                vibrating = vibrator;
            }
            UI.postDelayed(() -> stop(ctx), DURATION_MS);
        } catch (Throwable t) {
            Log.e(CrowdCadMapComponent.TAG, "assignment alarm failed", t);
        }
    }

    private static AudioAttributes alarmAttributes() {
        return new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build();
    }

    /** Loop the sound on the alarm stream. False (and nothing playing) if it couldn't start. */
    private static boolean playSound(Context plugin, String sound) {
        MediaPlayer mp = new MediaPlayer();
        try {
            mp.setAudioAttributes(alarmAttributes());
            try (AssetFileDescriptor afd = plugin.getResources().openRawResourceFd(soundRes(sound))) {
                mp.setDataSource(afd.getFileDescriptor(), afd.getStartOffset(), afd.getLength());
            }
            mp.setLooping(true);
            mp.prepare();
            mp.start();
            player = mp;
            return true;
        } catch (Throwable t) {
            Log.w(CrowdCadMapComponent.TAG, "alert sound " + sound + " failed; beeping instead", t);
            try {
                mp.release();
            } catch (Throwable ignored) {   // already broken: nothing left to free
            }
            return false;
        }
    }

    private static final Runnable BEEP = new Runnable() {
        @Override
        public void run() {
            if (tones == null || System.currentTimeMillis() >= until)
                return;
            try {
                tones.startTone(ToneGenerator.TONE_PROP_BEEP2, BEEP_MS);
            } catch (Throwable t) {
                Log.w(CrowdCadMapComponent.TAG, "beep failed", t);
                return;
            }
            UI.postDelayed(this, BEEP_EVERY_MS);
        }
    };

    /** UI thread: silence it (Acknowledge, the 5 s, or the plugin unloading); alarm volume back. */
    static void stop(Context ctx) {
        try {
            UI.removeCallbacksAndMessages(null);
            until = 0;
            if (player != null) {
                MediaPlayer mp = player;
                player = null;
                try {
                    mp.stop();
                } catch (Throwable ignored) {   // never started / already stopped: release anyway
                }
                mp.release();
            }
            if (tones != null) {
                tones.stopTone();
                tones.release();
                tones = null;
            }
            if (vibrating != null) {
                vibrating.cancel();
                vibrating = null;
            }
            if (restoreVolume >= 0) {
                AudioManager audio = (AudioManager) ctx.getSystemService(Context.AUDIO_SERVICE);
                if (audio != null)
                    audio.setStreamVolume(AudioManager.STREAM_ALARM, restoreVolume, 0);
                restoreVolume = -1;
            }
        } catch (Throwable t) {
            Log.w(CrowdCadMapComponent.TAG, "alarm stop", t);
        }
    }
}
