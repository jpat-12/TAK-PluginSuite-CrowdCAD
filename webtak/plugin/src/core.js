// Framework-free core: opens the board in a real WebTAK drawer when ../index.js registered
// one, else in a floating panel. No WebTAK internals here, so it runs the same in WebTAK and
// in the standalone demo.

import { injectStyles } from './styles.js';
import { mountFloatingPanel } from './floating-panel.js';
import { getConfig, setConfig } from './config.js';

class CrowdCadBoard {
  constructor() {
    this._floating = null;
    this._launchBtn = null;
    this._openDrawer = null;
  }

  mount() {
    injectStyles();
    return this;
  }

  setDrawerOpener(fn) {
    this._openDrawer = fn;
    return this;
  }

  open() {
    this.mount();
    if (this._openDrawer) {
      this._openDrawer();
      return this;
    }
    if (this._floating) this._floating.show();
    else this._floating = mountFloatingPanel();
    return this;
  }

  close() {
    this._floating?.destroy();
    this._floating = null;
    return this;
  }

  configure(patch) { return setConfig(patch); }
  getConfig() { return getConfig(); }

  showLaunchButton(label = '🚑 CrowdCAD') {
    this.mount();
    if (this._launchBtn) return this;
    const btn = document.createElement('button');
    btn.className = 'wcad-launch';
    btn.textContent = label;
    btn.addEventListener('click', () => this.open());
    document.body.appendChild(btn);
    this._launchBtn = btn;
    return this;
  }
}

const instance = new CrowdCadBoard();
if (typeof window !== 'undefined') window.CrowdCadBoard = instance;

export default instance;
