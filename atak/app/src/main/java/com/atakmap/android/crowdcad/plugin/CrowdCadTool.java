package com.atakmap.android.crowdcad.plugin;

import android.content.Context;

import com.atak.plugins.impl.AbstractPluginTool;
import com.atakmap.android.crowdcad.CrowdCadDropDown;

/** Toolbar button; fires SHOW_PLUGIN, which opens the board. */
public class CrowdCadTool extends AbstractPluginTool {

    public CrowdCadTool(Context context) {
        super(context,
                context.getString(R.string.app_name),
                context.getString(R.string.app_name),
                context.getResources().getDrawable(R.drawable.ic_launcher),
                CrowdCadDropDown.SHOW_PLUGIN);
    }
}
