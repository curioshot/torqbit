/* ReelScroll host layer — replaces chrome.storage.* / chrome.runtime.*.
 *
 * Loaded FIRST by the bot (CDP or Marionette) or by an extension, before
 * reels.js and controller.js. It owns the single settings store and the
 * Python<->page bridge:
 *
 *   window.__RS.get()            -> current settings object
 *   window.__RS.set(patch, save) -> merge patch; save=true persists via host
 *   window.__RS.sub(fn)          -> called whenever settings change
 *
 *   window.__reelscroll.next(source) / .prev(source)
 *   window.__reelscroll.status()
 *   window.__reelscroll.setSettings(patch)
 *
 * Persistence target differs by transport:
 *   CDP        -> Runtime.addBinding('__reelscrollHost') pushes to the bot
 *   Marionette -> no binding; the bot polls state and re-pushes config
 * Both tolerate the other being absent.
 */
(() => {
  'use strict';

  if (window.__RS) return;

  const listeners = [];
  let current = {};

  function seed(cfg) {
    try {
      current = Object.assign({}, cfg && typeof cfg === 'object' ? cfg : {});
    } catch (err) {
      current = {};
    }
  }

  // Python seeds this before the payload scripts run.
  seed(window.__reelscrollConfig);

  // CDP installs a native function of this name. When it is absent (extension,
  // Marionette, or a page that sealed window) writes are still applied locally,
  // they just are not persisted by the bot.
  function persist(patch) {
    try {
      if (typeof window.__reelscrollHost === 'function') {
        window.__reelscrollHost(JSON.stringify(patch));
        return true;
      }
    } catch (err) {
      /* binding gone — fall through */
    }
    return false;
  }

  const api = {
    version: 2,
    get() {
      return Object.assign({}, current);
    },
    set(patch, save) {
      if (!patch || typeof patch !== 'object') return current;
      current = Object.assign({}, current, patch);
      for (const fn of listeners) {
        try {
          fn(current, patch);
        } catch (err) {
          /* one bad subscriber must not break the rest */
        }
      }
      if (save) persist(patch);
      return current;
    },
    sub(fn) {
      if (typeof fn === 'function') listeners.push(fn);
      return fn;
    },
    persist
  };

  window.__RS = api;

  // host.js may load before Python seeds the config (extension-style load);
  // if so, pick it up on the next frame.
  if (!window.__reelscrollConfig) {
    requestAnimationFrame(() => seed(window.__reelscrollConfig));
  }
})();
