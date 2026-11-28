package com.atakmap.android.crowdcad;

import android.app.AlertDialog;
import android.content.Context;
import android.content.Intent;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import com.atakmap.android.icons.UserIconDatabase;
import com.atakmap.android.icons.UserIconSet;
import com.atakmap.android.ipc.AtakBroadcast;
import com.atakmap.android.maps.MapView;
import com.atakmap.coremap.filesystem.FileSystemUtils;
import com.atakmap.coremap.io.IOProviderFactory;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * Installs the bundled CrowdCAD iconset (assets/iconsets/CrowdCAD.zip, built by the suite's
 * iconset/build_iconset.py) into ATAK's icon library every time the plugin loads, so markers
 * whose CoT names {@code <usericon iconsetpath="<uid>/CrowdCAD/...">} resolve without anyone
 * importing a data package by hand.
 *
 * Flow (background thread):
 * 1. Read uid + version from the zip's own iconset.xml. They are not hard-coded here, so a
 *    rebuilt zip is picked up with no code change.
 * 2. If ATAK already has that uid at the same or a newer version, stop. This is the normal case
 *    after the first load.
 * 3. Otherwise copy the zip to atak/tools/crowdcad/ and broadcast ADD_ICONSET. That is ATAK's
 *    own import path (IconsMapAdapter); it also removes an older version of the same uid.
 * 4. ADD_ICONSET returns nothing, so poll UserIconDatabase until the set appears.
 *
 * Any failure (missing or bad asset, unwritable storage, import never landing) opens a dialog
 * with Retry or "Stop loading it".
 *
 * Tracker R42 ({@link IconsetPref}): on ATAK 5.8 the import never settled and Retry looped.
 * "Stop loading it" turns the import off (Settings turns it back on), and an import that was
 * started but never confirmed (ATAK hung or was killed) is not started again on the next load:
 * the dialog asks first. The plugin's own markers don't need the set.
 */
final class IconsetInstaller {

    static final String ASSET = "iconsets/CrowdCAD.zip";
    private static final String ADD_ICONSET = "com.atakmap.android.icons.ADD_ICONSET";
    // ATAK imports on its own thread. 20 s covers a slow device; past that, call it failed.
    private static final long CONFIRM_TIMEOUT_MS = 20_000;
    private static final long CONFIRM_POLL_MS = 500;

    private final Context plugin;
    private final MapView mapView;
    private final ExecutorService worker = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile boolean stopped;

    IconsetInstaller(Context plugin, MapView mapView) {
        this.plugin = plugin;
        this.mapView = mapView;
    }

    /** Runs only when the operator has the iconset turned on (tracker R42, {@link IconsetPref}). */
    void start() {
        if (stopped || !IconsetPref.enabled(mapView.getContext()))
            return;
        worker.execute(this::installOrReport);
    }

    void stop() {
        stopped = true;
        worker.shutdownNow();
    }

    /** Parsed {@code <iconset uid=".." version="..">} header. */
    static final class Header {
        final String uid;
        final int version;

        Header(String uid, int version) {
            this.uid = uid;
            this.version = version;
        }
    }

    private static final Pattern ICONSET_TAG = Pattern.compile("<iconset\\b[^>]*>", Pattern.DOTALL);

    /** Pure: the uid and version from an iconset.xml, or null if either is missing or invalid. */
    static Header parseHeader(String xml) {
        if (xml == null)
            return null;
        Matcher tag = ICONSET_TAG.matcher(xml);
        if (!tag.find())
            return null;
        String uid = attr(tag.group(), "uid");
        String version = attr(tag.group(), "version");
        if (uid == null || uid.trim().isEmpty() || version == null)
            return null;
        try {
            return new Header(uid.trim(), Integer.parseInt(version.trim()));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String attr(String tag, String name) {
        Matcher m = Pattern.compile("\\b" + name + "\\s*=\\s*\"([^\"]*)\"").matcher(tag);
        return m.find() ? m.group(1) : null;
    }

    private void installOrReport() {
        try {
            install();
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();   // plugin unloading: nothing to report
        } catch (Exception e) {
            Log.e(CrowdCadMapComponent.TAG, "iconset install failed", e);
            if (!stopped && IconsetPref.enabled(mapView.getContext()))
                ui.post(() -> showError(e.getMessage() != null ? e.getMessage() : e.toString()));
        }
    }

    private void install() throws Exception {
        byte[] zip = readAsset();
        Header header = parseHeader(iconsetXml(zip));
        if (header == null)
            throw new IOException("the bundled iconset has no valid iconset.xml (uid + version)");

        UserIconDatabase db = UserIconDatabase.instance(mapView.getContext());
        UserIconSet have = db.getIconSet(header.uid, false, false);
        if (have != null && have.getVersion() >= header.version) {
            Log.d(CrowdCadMapComponent.TAG, "iconset " + header.uid + " v" + have.getVersion() + " already installed");
            return;
        }

        // Tracker R42: an import requested last time never confirmed (ATAK hung or was killed in
        // it). Ask, via the error dialog, instead of starting the same import again.
        Context ctx = mapView.getContext();
        if (IconsetPref.pending(ctx)) {
            IconsetPref.setPending(ctx, false);
            throw new IOException("ATAK didn't finish importing the iconset last time it tried");
        }

        File dir = FileSystemUtils.getItem("tools/crowdcad");
        if (!IOProviderFactory.exists(dir) && !IOProviderFactory.mkdirs(dir))
            throw new IOException("can't create " + dir);
        File out = new File(dir, "CrowdCAD-iconset.zip");
        try (OutputStream os = IOProviderFactory.getOutputStream(out)) {
            os.write(zip);
        }

        IconsetPref.setPending(ctx, true);
        Intent add = new Intent(ADD_ICONSET);
        add.putExtra("filepath", out.getAbsolutePath());
        AtakBroadcast.getInstance().sendBroadcast(add);
        Log.d(CrowdCadMapComponent.TAG, "iconset import requested: " + out + " (v" + header.version + ")");

        long deadline = System.currentTimeMillis() + CONFIRM_TIMEOUT_MS;
        while (System.currentTimeMillis() < deadline && !stopped) {
            Thread.sleep(CONFIRM_POLL_MS);
            UserIconSet now = db.getIconSet(header.uid, false, false);
            if (now != null && now.getVersion() >= header.version) {
                IconsetPref.setPending(ctx, false);
                Log.d(CrowdCadMapComponent.TAG, "iconset " + header.uid + " v" + now.getVersion() + " installed");
                return;
            }
        }
        if (stopped)
            return;                  // plugin unloading mid-wait: leave "pending" for the next load
        IconsetPref.setPending(ctx, false);   // reported now, so the next load imports normally
        throw new IOException("ATAK did not finish importing the iconset within "
                + CONFIRM_TIMEOUT_MS / 1000 + " s");
    }

    private byte[] readAsset() throws IOException {
        try (InputStream in = plugin.getAssets().open(ASSET)) {
            ByteArrayOutputStream buf = new ByteArrayOutputStream();
            byte[] chunk = new byte[8192];
            for (int n; (n = in.read(chunk)) > 0; )
                buf.write(chunk, 0, n);
            return buf.toByteArray();
        } catch (IOException e) {
            throw new IOException("the plugin's bundled iconset (" + ASSET + ") is missing or unreadable", e);
        }
    }

    private static String iconsetXml(byte[] zip) throws IOException {
        try (ZipInputStream zin = new ZipInputStream(new java.io.ByteArrayInputStream(zip))) {
            for (ZipEntry e; (e = zin.getNextEntry()) != null; ) {
                if (e.getName().equals("iconset.xml")) {
                    ByteArrayOutputStream buf = new ByteArrayOutputStream();
                    byte[] chunk = new byte[4096];
                    for (int n; (n = zin.read(chunk)) > 0; )
                        buf.write(chunk, 0, n);
                    return new String(buf.toByteArray(), StandardCharsets.UTF_8);
                }
            }
        }
        return null;
    }

    /** UI thread. Uses ATAK's activity context: a plugin context can't host a dialog. */
    private void showError(String reason) {
        new AlertDialog.Builder(mapView.getContext())
                .setTitle("CrowdCAD icons not loaded")
                .setMessage("The CrowdCAD iconset could not be added to ATAK's icon library. The "
                        + "CrowdCAD panel and its markers still work.\n\nReason: " + reason)
                .setPositiveButton("Retry", (d, w) -> start())
                // Tracker R42: a way out when the import never settles, instead of Retry forever.
                .setNeutralButton("Stop loading it", (d, w) -> IconsetPref.set(mapView.getContext(), false))
                .setNegativeButton("Dismiss", null)
                .show();
    }
}
