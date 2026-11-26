package com.atakmap.android.crowdcad.cot;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The bridge's {@code <event type="t-x-crowdcad-roster">…<__crowdcad_roster v="1"><unit uid=".."
 * status=".."/>…} (bridge cot.render_roster): device uid → IU status code. Pure, tested.
 */
public final class RosterMessage {

    public static final String TYPE = "t-x-crowdcad-roster";
    public static final String ELEMENT = "__crowdcad_roster";

    private static final Pattern UNIT = Pattern.compile("<unit\\b([^>]*)/?>");
    private static final Pattern ATTR = Pattern.compile("\\b(uid|status|name)=\"([^\"]*)\"");
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
