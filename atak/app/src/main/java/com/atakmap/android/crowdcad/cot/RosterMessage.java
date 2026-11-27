package com.atakmap.android.crowdcad.cot;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The bridge's {@code <event type="t-x-crowdcad-roster">…<__crowdcad_roster v="1"><unit uid=".."
 * status=".." supreq=".."/>…} (bridge cot.render_roster): device uid → IU status code and open
 * supervisor request, and the dispatcher's
 * assignment alert sound ({@code alert="soft|hilo"} on the roster element). Pure, tested.
 */
public final class RosterMessage {

    public static final String TYPE = "t-x-crowdcad-roster";
    public static final String ELEMENT = "__crowdcad_roster";

    private static final Pattern UNIT = Pattern.compile("<unit\\b([^>]*)/?>");
    private static final Pattern ATTR = Pattern.compile("\\b(uid|status|name|supreq)=\"([^\"]*)\"");
    private static final Pattern ALERT = Pattern.compile("<" + ELEMENT + "\\b[^>]*\\balert=\"([^\"]*)\"");
    private static final Pattern VERSION = Pattern.compile("<" + ELEMENT + "\\b[^>]*\\bv=\"(\\d+)\"");

    private RosterMessage() {
    }

    /** @return uid → status, or null if this isn't a roster we understand (no detail, newer v). */
    public static Map<String, String> parse(String detailXml) {
        return attribute(detailXml, "status");
    }

    /** @return uid → CrowdCAD unit name ("Medic 1"), or null as {@link #parse}. */
    public static Map<String, String> names(String detailXml) {
        return attribute(detailXml, "name");
    }

    /**
     * @return uid → `at` (ms) of each unit's open supervisor request (the unit's {@code supreq}
     * attribute; units without one are left out), or null as {@link #parse}.
     */
    public static Map<String, Long> supervisorRequests(String detailXml) {
        Map<String, String> raw = attribute(detailXml, "supreq");
        if (raw == null)
            return null;
        Map<String, Long> out = new LinkedHashMap<>();
        for (Map.Entry<String, String> e : raw.entrySet()) {
            long at = toMs(e.getValue());
            if (at > 0)
                out.put(e.getKey(), at);
        }
        return out;
    }

    /** A {@code supreq} value as ms, or 0 if missing / not a number. */
    public static long toMs(String value) {
        if (value == null || value.isEmpty() || value.length() > 15)
            return 0;
        try {
            return Long.parseLong(value);
        } catch (NumberFormatException e) {
            return 0;
        }
    }

    /** @return "hilo" when the dispatcher chose hi-lo, else "soft" (missing, unknown, no roster). */
    public static String alert(String detailXml) {
        if (detailXml == null)
            return "soft";
        Matcher a = ALERT.matcher(detailXml);
        return a.find() && "hilo".equals(a.group(1)) ? "hilo" : "soft";
    }

    private static Map<String, String> attribute(String detailXml, String wanted) {
        if (detailXml == null)
            return null;
        Matcher v = VERSION.matcher(detailXml);
        if (!v.find() || Integer.parseInt(v.group(1)) > 1)
            return null;
        Map<String, String> out = new LinkedHashMap<>();
        Matcher u = UNIT.matcher(detailXml);
        while (u.find()) {
            String uid = null, value = "";
            Matcher a = ATTR.matcher(u.group(1));
            while (a.find()) {
                if ("uid".equals(a.group(1)))
                    uid = a.group(2);
                else if (wanted.equals(a.group(1)))
                    value = a.group(2);
            }
            if (uid != null && !uid.isEmpty())
                out.put(uid, value);
        }
        return out;
    }
}
