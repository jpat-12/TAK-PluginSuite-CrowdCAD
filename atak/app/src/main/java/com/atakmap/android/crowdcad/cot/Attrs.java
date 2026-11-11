package com.atakmap.android.crowdcad.cot;

/**
 * Attribute lookup on a CoT detail element. ATAK's {@code CotDetail::getAttribute} in the
 * plugin, a DOM element in JVM tests — so parsing is testable without ATAK.
 */
public interface Attrs {
    /** null when absent. */
    String get(String name);
}
