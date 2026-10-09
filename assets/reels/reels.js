/* ReelScroll — reel navigation engine.
 *
 * Originally an extension content script (isolated world). Now injected
 * directly into the page by bot-island over CDP/Marionette, so it runs in
 * the MAIN world: the history.pushState patch below genuinely works now,
 * and the host layer (host.js) replaces chrome.storage / chrome.runtime.
 */
(() => {
  'use strict';

  if (window.__reelscrollNav) return; // already injected for this document

  const DEFAULTS = {
    enabled: true,
    wheelEnabled: true,
    invertWheel: false,
    smooth: true,
    cooldownMs: 800,
    wheelThreshold: 30,
    nextKey: 'KeyS',
    prevKey: 'KeyW',
    nextLabel: 'S',
    prevLabel: 'W',
    allowArrows: false
  };

  let settings = { ...DEFAULTS, ...(window.__RS ? window.__RS.get() : {}) };
  let lastNavAt = 0;
  let currentIndex = 0;
  let candidates = [];
  let observer = null;
  let rescanTimer = 0;
  let toastEl = null;
  let toastTimer = 0;

  // The host (bot-island) pushes live setting changes; the extension path
  // used to deliver these via chrome.storage.onChanged.
  if (window.__RS) {
    window.__RS.sub((next) => {
      settings = next;
    });
  }

  function isReelsPage() {
    const p = location.pathname || '';
    return p === '/reels' || p === '/reels/' || p.startsWith('/reels/') || p.startsWith('/reel/');
  }

  function isActive() {
    return settings.enabled && isReelsPage();
  }

  function fromController(el) {
    return el instanceof HTMLElement && !!el.closest('#reelscroll-controller-host');
  }

  function isEditable(el) {
    if (!el) return false;
    if (el.isContentEditable) return true;
    const tag = (el.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'textarea' || tag === 'select';
  }

  function isNestedScrollable(el) {
    // Only let SMALL scrollable panes (comments sheet, dialogs) scroll natively.
    // The main Reels feed scroller is ~viewport height — that one we WANT to hijack.
    let node = el instanceof HTMLElement ? el : el?.parentElement;
    while (node && node !== document.body && node !== document.documentElement) {
      if (node instanceof HTMLElement) {
        const style = getComputedStyle(node);
        const overflowY = style.overflowY;
        if ((overflowY === 'auto' || overflowY === 'scroll') && node.scrollHeight > node.clientHeight + 8) {
          // Small pane => nested (don't hijack). Full-height => main feed (hijack).
          if (node.clientHeight < window.innerHeight * 0.7) return true;
          // Large container => keep walking: it may contain a small pane deeper down,
          // but we already checked from the inside out, so this IS the feed scroller.
          return false;
        }
      }
      node = node.parentElement;
    }
    return false;
  }

  function collectCandidates() {
    const found = [];
    const seen = new Set();

    const push = (el) => {
      if (!el || seen.has(el)) return;
      seen.add(el);
      if (!el.isConnected) return; // virtualized away: scrolling it would no-op
      const r = el.getBoundingClientRect();
      // Must be roughly viewport-sized vertically to be a reel.
      if (r.height > window.innerHeight * 0.4) found.push(el);
    };

    // Strategy 1: articles containing a video (most stable across IG redesigns).
    document.querySelectorAll('main article').forEach((a) => {
      if (a.querySelector('video')) push(a);
    });

    // Strategy 2: any video -> closest large container.
    document.querySelectorAll('video').forEach((v) => {
      const r = v.getBoundingClientRect();
      if (r.height < 200 || r.width < 150) return; // story thumbnails, previews
      const article = v.closest('article');
      if (article) {
        push(article);
        return;
      }
      // Walk up to a container roughly viewport height.
      let node = v.parentElement;
      for (let i = 0; i < 6 && node; i++) {
        const nr = node.getBoundingClientRect();
        if (nr.height > window.innerHeight * 0.5) {
          push(node);
          break;
        }
        node = node.parentElement;
      }
    });

    found.sort((a, b) => {
      const ra = a.getBoundingClientRect();
      const rb = b.getBoundingClientRect();
      return ra.top - rb.top;
    });

    return found;
  }

  function refreshCandidates() {
    candidates = collectCandidates();
    observeCandidates();
    updateCurrentIndex();
  }

  function scheduleRescan() {
    clearTimeout(rescanTimer);
    rescanTimer = setTimeout(() => {
      requestAnimationFrame(refreshCandidates);
    }, 300);
  }

  function observeCandidates() {
    if (observer) observer.disconnect();
    if (!('IntersectionObserver' in window)) return;
    observer = new IntersectionObserver(
      (entries) => {
        let best = -1;
        let bestRatio = 0;
        entries.forEach((e) => {
          const idx = candidates.indexOf(e.target);
          if (idx === -1) return;
          if (e.isIntersecting && e.intersectionRatio > bestRatio) {
            bestRatio = e.intersectionRatio;
            best = idx;
          }
        });
        if (best >= 0) currentIndex = best;
      },
      { threshold: [0.3, 0.5, 0.6, 0.8] }
    );
    // Batch observation to avoid layout thrash on large feeds.
    const batch = candidates.slice(0, 60);
    requestAnimationFrame(() => batch.forEach((el) => observer.observe(el)));
  }

  function updateCurrentIndex() {
    candidates = candidates.filter((el) => el.isConnected);
    if (candidates.length === 0) return;
    const midY = window.innerHeight / 2;
    let best = 0;
    let bestDist = Infinity;
    candidates.forEach((el, i) => {
      const r = el.getBoundingClientRect();
      const center = r.top + r.height / 2;
      const d = Math.abs(center - midY);
      if (d < bestDist) {
        bestDist = d;
        best = i;
      }
    });
    currentIndex = best;
  }

  function canNavigate() {
    return Date.now() - lastNavAt >= settings.cooldownMs;
  }

  // The snap feed usually scrolls an inner div, not the window.
  // Scroll that container; fall back to the viewport.
  function feedScroller() {
    const anchor = candidates[currentIndex] || document.querySelector('main');
    let node = anchor instanceof HTMLElement ? anchor.parentElement : null;
    while (node && node !== document.body && node !== document.documentElement) {
      const oy = getComputedStyle(node).overflowY;
      if ((oy === 'auto' || oy === 'scroll') && node.scrollHeight > node.clientHeight + 8) {
        return node;
      }
      node = node.parentElement;
    }
    return null;
  }

  function viewportNudge(down, source) {
    // IG virtualizes the feed, so often only one reel is detectable.
    // A viewport scroll still moves the snap feed; the rescan picks up the new reel.
    lastNavAt = Date.now();
    const top = (down ? 1 : -1) * window.innerHeight * 0.9;
    const behavior = settings.smooth ? 'smooth' : 'auto';
    const scroller = feedScroller();
    if (scroller) {
      scroller.scrollBy({ top, behavior });
    } else {
      window.scrollBy({ top, behavior });
    }
    showToast(down ? '▼' : '▲', source);
    scheduleRescan();
    return true;
  }

  function scrollToIndex(idx, source) {
    if (!isActive()) return false;
    if (!canNavigate()) return false;
    updateCurrentIndexIfStale();

    if (candidates.length <= 1) {
      // Single-reel page (/reel/<id>/), DOM not ready, or virtualized feed:
      // fall back to a viewport scroll in the requested direction.
      return viewportNudge(idx >= currentIndex, source);
    }

    const clamped = Math.max(0, Math.min(candidates.length - 1, idx));

    if (clamped === currentIndex) {
      // Already at edge — feedback only, and don't burn the cooldown.
      showToast(clamped === 0 ? '▲ top' : '▼ end');
      return true;
    }

    lastNavAt = Date.now();
    const dirDown = clamped >= currentIndex;
    currentIndex = clamped;
    const el = candidates[clamped];
    try {
      el.scrollIntoView({ behavior: settings.smooth ? 'smooth' : 'auto', block: 'center' });
    } catch (err) {
      const behavior = settings.smooth ? 'smooth' : 'auto';
      window.scrollBy({ top: (dirDown ? 1 : -1) * window.innerHeight * 0.9, behavior });
    }
    showToast(source === 'prev' ? '▲' : '▼', source);
    return true;
  }

  function updateCurrentIndexIfStale() {
    if (candidates.length === 0) refreshCandidates();
  }

  function goNext(source = 'api') {
    updateCurrentIndex();
    return scrollToIndex(currentIndex + 1, source === 'api' ? 'next' : source);
  }

  function goPrev(source = 'api') {
    updateCurrentIndex();
    return scrollToIndex(currentIndex - 1, source === 'api' ? 'prev' : source);
  }

  function showToast(text, source) {
    const label = text || (source === 'next' ? '▼' : source === 'prev' ? '▲' : '');
    if (!label) return;
    if (!toastEl) {
      toastEl = document.createElement('div');
      toastEl.className = 'irs-toast';
      toastEl.setAttribute('aria-hidden', 'true');
      document.documentElement.appendChild(toastEl);
    }
    toastEl.textContent = label;
    toastEl.classList.add('irs-show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toastEl.classList.remove('irs-show'), 450);
  }

  function onWheel(e) {
    if (!isActive() || !settings.wheelEnabled) return;
    if (fromController(e.target)) return;
    if (isEditable(e.target)) return;
    // Ignore horizontal/trackpad-horizontal gestures.
    if (Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
    if (Math.abs(e.deltaY) < settings.wheelThreshold) return;
    if (!canNavigate()) {
      e.preventDefault();
      return;
    }
    if (isNestedScrollable(e.target)) return; // let comment sheets scroll

    let down = e.deltaY > 0;
    if (settings.invertWheel) down = !down;
    e.preventDefault();
    e.stopPropagation();
    if (down) goNext('wheel');
    else goPrev('wheel');
  }

  function onKeyDown(e) {
    if (!isActive()) return;
    if (fromController(e.target)) return;
    if (e.repeat && !canNavigate()) return;
    if (isEditable(e.target)) return;
    // Don't fight modifier combos (Ctrl+F etc.).
    if (e.ctrlKey || e.metaKey || e.altKey) return;

    const code = e.code;
    if (code === settings.nextKey) {
      e.preventDefault();
      goNext('key');
    } else if (code === settings.prevKey) {
      e.preventDefault();
      goPrev('key');
    } else if (settings.allowArrows && code === 'ArrowDown') {
      e.preventDefault();
      goNext('key');
    } else if (settings.allowArrows && code === 'ArrowUp') {
      e.preventDefault();
      goPrev('key');
    }
  }

  function snapshot() {
    return {
      ok: true,
      active: isActive(),
      reelsPage: isReelsPage(),
      count: candidates.length,
      index: currentIndex,
      url: location.href,
      settings
    };
  }

  // Bridge used by bot-island (Runtime.evaluate over CDP/Marionette).
  // The extension's chrome.runtime.onMessage path is gone with the extension;
  // these three functions replace REELS_NEXT / REELS_PREV / REELS_PING.
  const prevApi = window.__reelscroll || {};
  window.__reelscroll = Object.assign(prevApi, {
    version: 2,
    next(source) {
      const ok = isActive() ? goNext(source || 'bot') : false;
      return { ok, active: isActive(), count: candidates.length };
    },
    prev(source) {
      const ok = isActive() ? goPrev(source || 'bot') : false;
      return { ok, active: isActive(), count: candidates.length };
    },
    status: snapshot,
    setSettings(patch) {
      return window.__RS ? window.__RS.set(patch, false) : settings;
    },
    refresh: refreshCandidates
  });

  function initObservers() {
    const mo = new MutationObserver(scheduleRescan);
    mo.observe(document.documentElement, { childList: true, subtree: true });

    // Instagram is an SPA — URL changes without reload (pushState/replaceState/popstate).
    const origPush = history.pushState;
    history.pushState = function (...args) {
      const ret = origPush.apply(this, args);
      scheduleRescan();
      return ret;
    };
    const origReplace = history.replaceState;
    history.replaceState = function (...args) {
      const ret = origReplace.apply(this, args);
      scheduleRescan();
      return ret;
    };
    window.addEventListener('popstate', scheduleRescan);
    // Fallback poll: catches SPA navs that bypass the patches.
    let lastUrl = location.href;
    setInterval(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        scheduleRescan();
      }
    }, 1000);
  }

  function init() {
    refreshCandidates();
    initObservers();
    window.addEventListener('wheel', onWheel, { passive: false, capture: true });
    window.addEventListener('keydown', onKeyDown, { capture: true });
    window.addEventListener('resize', scheduleRescan);
    // Local bridge: the video controller pill asks for turns the same way keys do.
    window.addEventListener('reelscroll:next', (e) => goNext(e.detail?.source || 'controller'));
    window.addEventListener('reelscroll:prev', (e) => goPrev(e.detail?.source || 'controller'));
    try {
      window.__reelscrollNav = () => ({
        reelsPage: isReelsPage(),
        candidates: candidates.length,
        currentIndex,
        videos: document.querySelectorAll('video').length
      });
    } catch (err) {
      // Sealed window object on this page: snapshot stays unavailable.
    }
    // Late IG hydration: rescan a few times after load.
    setTimeout(refreshCandidates, 1500);
    setTimeout(refreshCandidates, 3500);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
