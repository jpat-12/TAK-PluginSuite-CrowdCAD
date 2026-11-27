package com.atakmap.android.crowdcad;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.Base64;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * The unit icons: the EMS ALS / BLS / SUP icon in its status colour, from the CrowdCAD iconset
 * (iconset/build_iconset.py, bundled at {@link IconsetInstaller#ASSET}). The iconset path goes on
 * the phone's own position report, so CloudTAK and every client with the iconset draw it; the
 * PNG itself is used to restyle other units' markers on plugin devices ({@link UnitStyler}).
 */
final class UnitIcons {

    static final String[] DESIGNATIONS = {"ALS", "BLS", "SUP"};
    /** Same uid as the bridge's cot.ICONSET_UID and build_iconset.py: sha256("crowdcad-tak/iconset"). */
    static final String ICONSET_UID = sha256("crowdcad-tak/iconset");

    private static final Map<String, byte[]> PNGS = new HashMap<>();

    private UnitIcons() {
    }

    static boolean valid(String designation) {
        for (String d : DESIGNATIONS)
            if (d.equals(designation))
                return true;
        return false;
    }

    static String file(String designation, String colour) {
        return "EMS " + designation + " " + colour + ".png";
    }

    /**
     * The same PNGs by raw GitHub URL (the IU bridge's CAD_ICON_BASE approach). NOT used by
     * default: CloudTAK 13.102 resolves {@code <usericon iconsetpath>} only as an iconset id
     * ({@code <iconsetUid>:<path>} in its iconset store) and draws a URL as a plain white dot. Kept
     * for clients that fetch icons by URL.
     */
    static final String ICON_BASE = "https://raw.githubusercontent.com/jpat-12/TAK-PluginSuite-CrowdCAD/dev/iconset/png/";

    /** {@code <uid>/CrowdCAD/EMS ALS AVL.png}: the usericon iconsetpath (the CrowdCAD iconset). */
    static String path(String designation, String colour) {
        return ICONSET_UID + "/CrowdCAD/" + file(designation, colour);
    }

    /** base64:// PNG of one unit icon for an ATAK Icon, read once from the bundled iconset; null if missing. */
    static String uri(Context plugin, String designation, String colour) {
        byte[] png = png(plugin, file(designation, colour));
        return png == null ? null : "base64://" + Base64.encodeToString(png, Base64.NO_WRAP | Base64.URL_SAFE);
    }

    /** The icon as a Bitmap for the panel's banner; designation "" = the plain EMS icon. */
    static Bitmap bitmap(Context plugin, String designation, String colour) {
        byte[] png = png(plugin, designation.isEmpty() ? "EMS.png" : file(designation, colour));
        return png == null ? null : BitmapFactory.decodeByteArray(png, 0, png.length);
    }

    /** One PNG from the bundled iconset, read once; null if missing. */
    private static synchronized byte[] png(Context plugin, String file) {
        String name = "CrowdCAD/" + file;
        byte[] cached = PNGS.get(name);
        if (cached != null)
            return cached;
        try (InputStream in = plugin.getAssets().open(IconsetInstaller.ASSET);
                ZipInputStream zip = new ZipInputStream(in)) {
            for (ZipEntry e; (e = zip.getNextEntry()) != null;) {
                if (!name.equals(e.getName()))
                    continue;
                ByteArrayOutputStream png = new ByteArrayOutputStream();
                byte[] buf = new byte[8192];
                for (int n; (n = zip.read(buf)) > 0;)
                    png.write(buf, 0, n);
                PNGS.put(name, png.toByteArray());
                return PNGS.get(name);
            }
        } catch (Exception e) {
            Log.w(CrowdCadMapComponent.TAG, "unit icon " + name + " not readable", e);
        }
        return null;
    }

    static String sha256(String text) {
        try {
            byte[] h = MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder out = new StringBuilder();
            for (byte b : h)
                out.append(String.format("%02x", b));
            return out.toString();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }
}
