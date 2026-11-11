package com.atakmap.android.crowdcad.plugin;

import com.atak.plugins.impl.AbstractPlugin;
import com.atak.plugins.impl.PluginContextProvider;
import com.atakmap.android.crowdcad.CrowdCadMapComponent;

import gov.tak.api.plugin.IServiceController;

/** Plugin entry point (named in assets/plugin.xml). */
public class CrowdCadLifecycle extends AbstractPlugin {

    public CrowdCadLifecycle(IServiceController serviceController) {
        super(serviceController,
                new CrowdCadTool(serviceController.getService(PluginContextProvider.class).getPluginContext()),
                new CrowdCadMapComponent());
    }
}
