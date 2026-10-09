/* ReelScroll — in-reel video controller (isolated world, Shadow DOM so IG styles can't touch it) */
(() => {
  'use strict';

  const HOST_ID = 'reelscroll-controller-host';
  const SPEEDS = [0.5, 1, 1.5, 2, 3];
  const DEFAULTS = {
    enabled: true,
    controllerEnabled: true,
    autoAdvance: true,
    playbackRate: 1,
    controllerMini: false,
    controllerPos: null
  };

  let settings = { ...DEFAULTS };
  let host = null;
  let shadow = null;
  let els = {};
  let video = null;
  let reverseRate = 0; // 0 = off, else 1 or 2 (simulated backward play)
  let reverseTimer = 0;
  let reverseLast = 0;
  let seeking = false;
  let lastDetectAt = 0;
  let frame = 0;
  let pendingAdvance = null; // {src, fireAt, retried}: polled, so rebinds can't cancel it
  let advancedFor = null; // src+duration key the watchdog already queued, fires once per reel
  let endedStamp = null; // {src, at}: `ended` fired recently, survives IG's instant replay
  let lastTime = 0; // last seen currentTime, for loop-wrap detection
  let lastSrc = ''; // bound video src, for same-element reuse detection
  let lastSeekAt = 0; // our own seeks never count as loop wraps
  let origLoop = false;
  let wantPip = false; // user wants the float open; follows reels while it can
  let pipFollow = false; // transitional: ignore the leave event of a migration
  let pipGen = 0; // generation counter: overlapping followPip() calls don't clear each other

  const SVG = {
    back: '<svg viewBox="0 0 16 16" width="14" height="14"><rect x="2" y="3" width="2" height="10" fill="currentColor"/><path d="M13 3v10L5.5 8 13 3z" fill="currentColor"/></svg>',
    fwd: '<svg viewBox="0 0 16 16" width="14" height="14"><rect x="12" y="3" width="2" height="10" fill="currentColor"/><path d="M3 3v10l7.5-5L3 3z" fill="currentColor"/></svg>',
    play: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M4 2.5v11l8.5-5.5L4 2.5z" fill="currentColor"/></svg>',
    pause: '<svg viewBox="0 0 16 16" width="14" height="14"><rect x="3.5" y="2.5" width="3.4" height="11" fill="currentColor"/><rect x="9.1" y="2.5" width="3.4" height="11" fill="currentColor"/></svg>',
    rev: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M12 3v10L4.5 8 12 3z" fill="currentColor"/></svg>',
    pip: '<svg viewBox="0 0 16 16" width="14" height="14"><rect x="1.5" y="3" width="13" height="10" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.6"/><rect x="8" y="7.5" width="4.5" height="3.4" rx="0.8" fill="currentColor"/></svg>'
  };

  const CSS = `
    :host { position: fixed; left: 0; top: 0; width: 0; height: 0; z-index: 2147483647; }
    .pill, .chip { position: fixed; font: 500 12px/1 system-ui, sans-serif; color: #fff;
      background: rgba(10,10,12,.82); border: 1px solid rgba(255,255,255,.14);
      border-radius: 999px; backdrop-filter: blur(6px); user-select: none; }
    .pill { left: 50%; bottom: 92px; transform: translateX(-50%);
      display: flex; align-items: center; gap: 4px; padding: 6px 10px; cursor: grab; }
    .pill.dragging { cursor: grabbing; }
    .chip { left: 50%; bottom: 92px; transform: translateX(-50%);
      display: flex; align-items: center; gap: 6px; padding: 7px 12px; cursor: pointer; }
    .hidden { display: none !important; }
    button { all: unset; display: flex; align-items: center; justify-content: center;
      min-width: 26px; height: 26px; border-radius: 999px; cursor: pointer; color: #fff;
      padding: 0 5px; box-sizing: border-box; }
    button:hover { background: rgba(255,255,255,.16); }
    button:focus-visible { outline: 2px solid #fff; outline-offset: 1px; }
    button.on { background: #bc2a8d; }
    .speed { font-variant-numeric: tabular-nums; min-width: 38px; }
    .time { font-variant-numeric: tabular-nums; color: rgba(255,255,255,.85);
      white-space: nowrap; padding: 0 2px; }
    .track { position: relative; width: 130px; height: 16px; display: flex;
      align-items: center; cursor: pointer; }
    .rail { position: relative; width: 100%; height: 4px; border-radius: 999px;
      background: rgba(255,255,255,.28); overflow: hidden; }
    .fill { position: absolute; left: 0; top: 0; bottom: 0; width: 0%;
      background: #fff; border-radius: 999px; }
    .track.disabled { opacity: .35; pointer-events: none; }
  `;

  function loadSettings() {
    // Host (bot-island) owns persistence; the extension used chrome.storage.sync.
    try {
      settings = { ...DEFAULTS, ...(window.__RS ? window.__RS.get() : {}) };
    } catch (err) {
      // Host unavailable: stick with defaults.
    }
  }

  function applySettings(next, changes) {
    settings = next;
    applyVisibility();
    if (video && changes.playbackRate) applyRate(video);
    // Toggling auto-advance at runtime takes effect on the live reel:
    // on restores the loop-off behavior, off gives the loop back.
    if (video && changes.autoAdvance) {
      if (changes.autoAdvance) {
        stripLocks(video);
      } else if (video.loop !== origLoop) {
        try {
          video.loop = origLoop;
        } catch (err) {
          // Read-only loop flag: leave it.
        }
      }
    }
  }

  if (window.__RS) {
    window.__RS.sub((next, changes) => applySettings(next, changes));
  }

  /** Persist a settings patch back to the host (bot-island writes config.json). */
  function saveSettings(patch) {
    settings = Object.assign({}, settings, patch);
    if (window.__RS) {
      window.__RS.set(patch, true);
    }
  }

  function isReelsPage() {
    const p = location.pathname || '';
    return p === '/reels' || p === '/reels/' || p.startsWith('/reels/') || p.startsWith('/reel/');
  }

  function isActive() {
    return settings.enabled && settings.controllerEnabled && isReelsPage();
  }

  function fmt(t) {
    if (!isFinite(t) || t < 0) return '--:--';
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return m + ':' + String(s).padStart(2, '0');
  }

  // The centered, viewport-sized video is the one the user is watching.
  // Feed preloads neighbors, so never just grab the first <video>.
  // Prefer the one actually playing: a paused preload can sit dead-center.
  // Ended videos keep only a small penalty — the just-finished centered reel
  // is exactly what the advance path needs to stay bound to.
  function detectVideo() {
    const midY = window.innerHeight / 2;
    let best = null;
    let bestScore = Infinity;
    document.querySelectorAll('video').forEach((v) => {
      const r = v.getBoundingClientRect();
      if (r.height < 200 || r.width < 150) return;
      let score = Math.abs(r.top + r.height / 2 - midY);
      if (v.paused) score += window.innerHeight * 0.6;
      if (score < bestScore) {
        bestScore = score;
        best = v;
      }
    });
    return best;
  }

  function setMediaHandlers(on) {
    // Puts working prev/next buttons INTO the PiP window and OS media OSD,
    // and keeps hardware keys alive when the PiP window (not the tab) is focused.
    try {
      if (!('mediaSession' in navigator)) return;
      if (on) {
        navigator.mediaSession.setActionHandler('previoustrack', () => {
          window.dispatchEvent(new CustomEvent('reelscroll:prev', { detail: { source: 'media-session' } }));
        });
        navigator.mediaSession.setActionHandler('nexttrack', () => {
          window.dispatchEvent(new CustomEvent('reelscroll:next', { detail: { source: 'media-session' } }));
        });
        navigator.mediaSession.metadata = new MediaMetadata({ title: 'Instagram Reel', artist: 'ReelScroll' });
      } else {
        navigator.mediaSession.setActionHandler('previoustrack', null);
        navigator.mediaSession.setActionHandler('nexttrack', null);
      }
    } catch (err) {
      // Media Session unsupported here: PiP buttons just won't appear.
    }
  }

  function bindVideo(v) {
    if (v === video) return;
    const keepFloating = wantPip;
    unbindVideo();
    video = v;
    stopReverse();
    // A pending advance survives rebinds; pumpAdvance drops it once the
    // centered video is a different reel. Only a truly empty feed cancels.
    if (!v) pendingAdvance = null;
    advancedFor = null;
    lastTime = v ? v.currentTime || 0 : 0;
    lastSrc = v ? v.currentSrc : '';
    setMediaHandlers(!!v);
    if (!video) return;
    origLoop = video.loop;
    stripLocks(video);
    video.addEventListener('loadedmetadata', onMeta);
    video.addEventListener('play', onPlay);
    video.addEventListener('ended', onEnded);
    video.addEventListener('timeupdate', onTime);
    video.addEventListener('enterpictureinpicture', onPipEnter);
    video.addEventListener('leavepictureinpicture', onPipLeave);
    applyRate(video);
    if (keepFloating) followPip();
    paint();
  }

  function unbindVideo() {
    if (!video) return;
    if (video.loop !== origLoop) {
      try {
        video.loop = origLoop;
      } catch (err) {
        // Read-only loop flag on this player: leave it.
      }
    }
    video.removeEventListener('loadedmetadata', onMeta);
    video.removeEventListener('play', onPlay);
    video.removeEventListener('ended', onEnded);
    video.removeEventListener('timeupdate', onTime);
    video.removeEventListener('enterpictureinpicture', onPipEnter);
    video.removeEventListener('leavepictureinpicture', onPipLeave);
    setMediaHandlers(false);
    video = null;
  }

  // Instagram ships reels with loop + disablepictureinpicture (+ controlslist).
  // A looping video never fires `ended`, and a PiP-blocked one refuses the float.
  // With auto-advance on we take the loop off so the reel can actually finish;
  // the PiP locks come off whenever we're bound (React re-adds attrs, tick re-strips).
  function stripLocks(v) {
    try {
      v.removeAttribute('disablepictureinpicture');
      v.removeAttribute('controlslist');
      if (settings.autoAdvance && v.loop) v.loop = false;
    } catch (err) {
      // Player ignores it: the watchdog still catches the wrap.
    }
  }

  // Usable length: finite duration normally; seekable end if IG ever serves
  // a stream with Infinity duration; NaN when nothing is known yet.
  function effectiveDuration(v) {
    if (isFinite(v.duration) && v.duration > 0) return v.duration;
    try {
      if (v.seekable && v.seekable.length > 0) {
        const end = v.seekable.end(v.seekable.length - 1);
        if (isFinite(end) && end > 0) return end;
      }
    } catch (err) {
      // Seekable unreadable on this player.
    }
    return NaN;
  }

  function onMeta() {
    if (video) applyRate(video);
    paint();
  }

  function onPlay() {
    // Real forward play cancels simulated reverse.
    stopReverse();
    if (video) applyRate(video);
    paint();
  }

  function nearEnd(v) {
    if (!v) return false;
    if (v.ended) return true;
    // A fresh `ended` counts even if IG already replayed the reel underneath us.
    if (endedStamp && endedStamp.src === v.currentSrc && Date.now() - endedStamp.at < 3000) return true;
    const dur = effectiveDuration(v);
    return isFinite(dur) && dur - v.currentTime <= 0.5;
  }

  function scheduleAdvance() {
    // Queue only: pumpAdvance (called from rAF AND timeupdate) does the timed
    // dispatch. Polled state survives video-element swaps that would kill a timer.
    if (!settings.autoAdvance || !video) return;
    if (pendingAdvance && pendingAdvance.el === video) return;
    pendingAdvance = { el: video, src: video.currentSrc, fireAt: Date.now() + 800, retried: false };
  }

  function clearEndedStampFor(src) {
    if (endedStamp && (!src || endedStamp.src === src)) endedStamp = null;
  }

  function pumpAdvance() {
    if (!pendingAdvance || !settings.autoAdvance || !video) return;
    // Element identity first (same-element src swaps keep it), src second
    // (a reused element showing a new reel cancels it). Empty src never mismatches.
    if (video !== pendingAdvance.el ||
        (video.currentSrc && pendingAdvance.src && video.currentSrc !== pendingAdvance.src)) {
      pendingAdvance = null; // centered reel is a different video: previous turn is moot
      return;
    }
    if (Date.now() < pendingAdvance.fireAt || !nearEnd(video)) return;
    window.dispatchEvent(new CustomEvent('reelscroll:next', {
      detail: { source: pendingAdvance.retried ? 'auto-advance-retry' : 'auto-advance' }
    }));
    clearEndedStampFor(video.currentSrc); // a later back-nav to this reel must not re-fire
    if (!pendingAdvance.retried) {
      // Cooldown may have eaten that turn: one retry after it expires.
      // After a real nav the centered element differs, so this can't double-fire.
      pendingAdvance.retried = true;
      pendingAdvance.fireAt = Date.now() + 2000;
    } else {
      pendingAdvance = null;
      advancedFor = null; // both turns eaten (e.g. maxed-out cooldown): let the watchdog re-queue
    }
  }

  // End watchdog: catches reels whose `ended` never fires (loop, MSE, races).
  // Runs from rAF while the tab is visible AND from `timeupdate` while it isn't
  // (background tab + PiP: rAF stops, media events keep flowing).
  // Fires once per reel; re-arms when the user scrubs back away from the end.
  function checkNearEnd() {
    if (!video || !settings.autoAdvance) return;
    pumpAdvance(); // first: an `ended`-queued turn must fire even with unknown duration
    const dur = effectiveDuration(video);
    if (!isFinite(dur)) return;
    const key = video.currentSrc + '#' + dur;
    const remaining = dur - video.currentTime;
    if (remaining > 0.5) {
      advancedFor = null;
      pendingAdvance = null;
      clearEndedStampFor(video.currentSrc);
    } else if (remaining <= 0.4 && reverseRate === 0 && advancedFor !== key) {
      advancedFor = key;
      scheduleAdvance();
    }
    pumpAdvance();
  }

  function onTime() {
    if (!video) return;
    // Same element showing a new reel (IG reuse): reset end-tracking first,
    // or the old reel's tail instantly advances the new one.
    if (video.currentSrc !== lastSrc) {
      lastSrc = video.currentSrc;
      lastTime = video.currentTime || 0;
      return;
    }
    const dur = effectiveDuration(video);
    if (!isFinite(dur)) {
      // Unknown length (unreadable stream): a playing video wrapping from well
      // into playback back to ~0 is a loop end. Normal progress re-arms.
      if (video.currentTime > 1) advancedFor = null;
      if (settings.autoAdvance && reverseRate === 0 && !video.paused &&
          Date.now() - lastSeekAt > 1000 &&
          lastTime > 2 && video.currentTime < 1) {
        const key = video.currentSrc + '#stream';
        if (advancedFor !== key) {
          advancedFor = key;
          scheduleAdvance();
        }
      }
      lastTime = video.currentTime;
      pumpAdvance();
      return;
    }
    // Loop-wrap catch: time jumped backwards from the very end, so the reel
    // restarted instead of ending — advance instead of replaying.
    // (Our own seeks are excluded: they set lastSeekAt.)
    if (settings.autoAdvance && reverseRate === 0 && Date.now() - lastSeekAt > 1000 &&
        lastTime - video.currentTime > 1) {
      if (isFinite(dur) && lastTime >= dur - 1.5) {
        const key = video.currentSrc + '#' + dur;
        if (advancedFor !== key) {
          advancedFor = key;
          scheduleAdvance();
        }
      } else {
        advancedFor = null; // manual seek backwards: re-arm
        pendingAdvance = null;
        clearEndedStampFor(video.currentSrc);
      }
    }
    lastTime = video.currentTime;
    checkNearEnd();
  }

  function onEnded() {
    // Stamp it: IG replays fast, and by the time our delay fires the reel may
    // already show currentTime ~0 again. The stamp keeps the advance valid.
    if (video) endedStamp = { src: video.currentSrc, at: Date.now() };
    scheduleAdvance();
    paint();
  }

  function onPipEnter() {
    wantPip = true;
    paint();
  }

  function onPipLeave() {
    // A migration closes the old float on purpose, and a replaced float already
    // has a successor: only a real close with nothing floating drops the wish.
    if (!pipFollow && !document.pictureInPictureElement) wantPip = false;
    paint();
  }

  // Move the floating window onto the newly centered reel.
  // Request FIRST without closing: when Chrome allows it (key/wheel/PiP-button
  // navs carry a gesture) the old float is replaced seamlessly. Timer-driven
  // auto-advance has no gesture to spend, so that path closes the float instead.
  async function followPip() {
    if (!video || !wantPip || typeof video.requestPictureInPicture !== 'function') return;
    const my = ++pipGen;
    pipFollow = true;
    try {
      await video.requestPictureInPicture();
      if (my === pipGen) wantPip = true;
    } catch (err) {
      if (my !== pipGen) return; // superseded by a newer migration
      try {
        await document.exitPictureInPicture().catch(() => {});
      } catch (err2) {
        // Nothing floating: nothing to close.
      }
      wantPip = false;
    } finally {
      if (my === pipGen) pipFollow = false;
    }
    paint();
  }

  async function togglePip() {
    pipGen++; // invalidate any in-flight followPip: the user's click wins
    if (video) stripLocks(video); // React may have re-added the PiP block since the tick
    try {
      if (document.pictureInPictureElement) {
        await document.exitPictureInPicture();
        wantPip = false;
      } else if (video && typeof video.requestPictureInPicture === 'function' && !video.disablePictureInPicture) {
        await video.requestPictureInPicture();
        wantPip = true;
      }
    } catch (err) {
      // PiP refused (not allowed on this video, no gesture): stay inline.
      wantPip = !!document.pictureInPictureElement;
    }
    paint();
  }

  function applyRate(v) {
    try {
      v.playbackRate = settings.playbackRate;
      v.preservesPitch = true;
    } catch (err) {
      // Some embedded players reject rate changes; leave them alone.
    }
  }

  function stopReverse() {
    reverseRate = 0;
    clearInterval(reverseTimer);
    reverseTimer = 0;
  }

  function startReverse(rate) {
    if (!video) return;
    stopReverse();
    try {
      video.pause();
    } catch (err) {
      return; // unable to take over playback: leave reverse off
    }
    reverseRate = rate;
    reverseLast = performance.now();
    clearInterval(reverseTimer);
    reverseTimer = setInterval(() => {
      if (!video || reverseRate === 0) {
        stopReverse();
        paint();
        return;
      }
      const now = performance.now();
      const dt = (now - reverseLast) / 1000;
      reverseLast = now;
      const next = video.currentTime - reverseRate * dt;
      if (next <= 0) {
        video.currentTime = 0;
        stopReverse();
      } else {
        try {
          video.currentTime = next;
        } catch (err) {
          stopReverse();
        }
      }
      paint();
    }, 50);
    paint();
  }

  function seekTo(frac) {
    if (!video || !isFinite(video.duration)) return;
    stopReverse();
    lastSeekAt = Date.now();
    pendingAdvance = null; // manual seek cancels a queued advance; watchdog re-queues at a fresh end
    advancedFor = null;
    clearEndedStampFor(video.currentSrc);
    const clamped = Math.max(0, Math.min(0.9999, frac));
    try {
      video.currentTime = clamped * video.duration;
    } catch (err) {
      // Seeking past buffered range throws on some reels; ignore.
    }
    paint();
  }

  function nudgeSecs(d) {
    if (!video || !isFinite(video.duration)) return;
    stopReverse();
    lastSeekAt = Date.now();
    pendingAdvance = null;
    advancedFor = null;
    clearEndedStampFor(video.currentSrc);
    const next = Math.max(0, Math.min(video.duration - 0.05, video.currentTime + d));
    try {
      video.currentTime = next;
    } catch (err) {
      // Ignore out-of-range seeks.
    }
    paint();
  }

  function cycleSpeed() {
    const i = SPEEDS.indexOf(settings.playbackRate);
    const next = SPEEDS[(i + 1 + SPEEDS.length) % SPEEDS.length];
    saveSettings({ playbackRate: next });
    stopReverse();
    if (video && !video.paused) applyRate(video);
    paint();
  }

  function cycleReverse() {
    // off -> -1x -> -2x -> off
    if (reverseRate === 0) startReverse(1);
    else if (reverseRate === 1) startReverse(2);
    else stopReverse();
    paint();
  }

  function togglePlay() {
    if (!video) return;
    if (reverseRate !== 0) {
      stopReverse();
      video.play().catch(() => {});
    } else if (video.paused) {
      video.play().catch(() => {});
    } else {
      video.pause();
    }
    paint();
  }

  function paint() {
    if (!els.pill) return;
    const dur = video ? effectiveDuration(video) : NaN;
    const hasMeta = isFinite(dur);
    els.play.innerHTML = video && !video.paused && reverseRate === 0 ? SVG.pause : SVG.play;
    els.play.title = video && !video.paused && reverseRate === 0 ? 'Pause' : 'Play';
    els.time.textContent = video
      ? fmt(video.currentTime) + ' / ' + fmt(dur)
      : '--:-- / --:--';
    els.fill.style.width = hasMeta ? (video.currentTime / dur * 100) + '%' : '0%';
    els.track.classList.toggle('disabled', !hasMeta);
    els.speed.textContent = settings.playbackRate + 'x';
    els.rev.classList.toggle('on', reverseRate !== 0);
    els.rev.innerHTML = SVG.rev + '<span>' + (reverseRate !== 0 ? '-' + reverseRate + 'x' : 'rev') + '</span>';
    els.pip.classList.toggle('on', !!document.pictureInPictureElement);
    els.chipText.textContent = (reverseRate !== 0 ? '-' + reverseRate + 'x' : settings.playbackRate + 'x');
  }

  function applyVisibility() {
    if (!els.pill) return;
    const show = isActive() && !!video;
    els.pill.classList.toggle('hidden', !show || settings.controllerMini);
    els.chip.classList.toggle('hidden', !show || !settings.controllerMini);
  }

  function build() {
    if (host) return;
    host = document.createElement('div');
    host.id = HOST_ID;
    shadow = host.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = CSS;
    const pill = document.createElement('div');
    pill.className = 'pill hidden';
    pill.innerHTML =
      '<button data-act="back" title="Back 5s">' + SVG.back + '</button>' +
      '<button data-act="play" title="Play/Pause">' + SVG.play + '</button>' +
      '<span class="time">--:-- / --:--</span>' +
      '<div class="track"><div class="rail"><div class="fill"></div></div></div>' +
      '<button data-act="fwd" title="Forward 5s">' + SVG.fwd + '</button>' +
      '<button data-act="speed" class="speed" title="Playback speed">1x</button>' +
      '<button data-act="rev" title="Reverse play">rev</button>' +
      '<button data-act="pip" title="Picture-in-picture">' + SVG.pip + '</button>' +
      '<button data-act="mini" title="Minimize">–</button>';
    const chip = document.createElement('div');
    chip.className = 'chip hidden';
    chip.innerHTML = SVG.play + '<span></span>';
    shadow.appendChild(style);
    shadow.appendChild(pill);
    shadow.appendChild(chip);
    document.documentElement.appendChild(host);

    els = {
      pill,
      chip,
      chipText: chip.querySelector('span'),
      play: pill.querySelector('[data-act="play"]'),
      time: pill.querySelector('.time'),
      track: pill.querySelector('.track'),
      fill: pill.querySelector('.fill'),
      speed: pill.querySelector('[data-act="speed"]'),
      rev: pill.querySelector('[data-act="rev"]'),
      pip: pill.querySelector('[data-act="pip"]')
    };

    pill.querySelector('[data-act="back"]').addEventListener('click', () => nudgeSecs(-5));
    pill.querySelector('[data-act="fwd"]').addEventListener('click', () => nudgeSecs(5));
    els.play.addEventListener('click', togglePlay);
    els.speed.addEventListener('click', cycleSpeed);
    els.rev.addEventListener('click', cycleReverse);
    els.pip.addEventListener('click', togglePip);
    pill.querySelector('[data-act="mini"]').addEventListener('click', () => {
      saveSettings({ controllerMini: true });
      applyVisibility();
    });
    chip.addEventListener('click', () => {
      saveSettings({ controllerMini: false });
      applyVisibility();
    });

    // Scrub: click or drag along the rail.
    const fracFromEvent = (e) => {
      const r = els.track.getBoundingClientRect();
      return (e.clientX - r.left) / Math.max(1, r.width);
    };
    els.track.addEventListener('pointerdown', (e) => {
      seeking = true;
      els.track.setPointerCapture(e.pointerId);
      seekTo(fracFromEvent(e));
    });
    els.track.addEventListener('pointermove', (e) => {
      if (seeking) seekTo(fracFromEvent(e));
    });
    els.track.addEventListener('pointerup', () => { seeking = false; });
    els.track.addEventListener('pointercancel', () => { seeking = false; });

    // Drag the pill by its background (never by buttons or the rail).
    let drag = null;
    pill.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button') || e.target.closest('.track')) return;
      const r = pill.getBoundingClientRect();
      drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
      pill.classList.add('dragging');
      pill.setPointerCapture(e.pointerId);
    });
    pill.addEventListener('pointermove', (e) => {
      if (!drag) return;
      pill.style.left = (e.clientX - drag.dx) + 'px';
      pill.style.top = (e.clientY - drag.dy) + 'px';
      pill.style.bottom = 'auto';
      pill.style.transform = 'none';
    });
    pill.addEventListener('pointerup', (e) => {
      if (!drag) return;
      drag = null;
      pill.classList.remove('dragging');
      const pos = { left: pill.style.left, top: pill.style.top };
      saveSettings({ controllerPos: pos });
    });

    if (settings.controllerPos) {
      pill.style.left = settings.controllerPos.left;
      pill.style.top = settings.controllerPos.top;
      pill.style.bottom = 'auto';
      pill.style.transform = 'none';
    }
  }

  function tick() {
    frame++;
    const now = performance.now();
    // Re-detect twice a second: cheap, catches reel switches the observer misses.
    if (now - lastDetectAt > 500) {
      lastDetectAt = now;
      if (isActive()) {
        bindVideo(detectVideo());
        if (video) {
          // Same element, new reel (IG reuses <video>): reset end-tracking so the
          // old reel's tail doesn't instantly advance the new one.
          if (video.currentSrc !== lastSrc) {
            lastSrc = video.currentSrc;
            lastTime = video.currentTime || 0;
            advancedFor = null;
            pendingAdvance = null;
            clearEndedStampFor(video.currentSrc);
          }
          // React re-adds attrs and resets rate on source swaps; heal both.
          stripLocks(video);
          if (reverseRate === 0 && video.playbackRate !== settings.playbackRate) applyRate(video);
        }
      } else {
        bindVideo(null);
        stopReverse();
      }
      applyVisibility();
    }
    // End watchdog: catches reels whose `ended` never fires (loop, MSE, races).
    // Fires once per reel; re-arms when the user scrubs back away from the end.
    checkNearEnd();
    if (video && !seeking && (frame % 6 === 0)) paint();
    requestAnimationFrame(tick);
  }

  // Read-only snapshot for the console: run `__reelscrollDebug()` on a Reels
  // page and paste the result when reporting that advance/nav misbehaves.
  function debugSnapshot() {
    const dur = video ? effectiveDuration(video) : NaN;
    let seekEnd = null;
    try {
      if (video && video.seekable && video.seekable.length > 0) {
        seekEnd = +video.seekable.end(video.seekable.length - 1).toFixed(2);
      }
    } catch (err) {
      // Seekable unreadable.
    }
    return {
      reelsPage: isReelsPage(),
      enabled: settings.enabled,
      controllerEnabled: settings.controllerEnabled,
      autoAdvance: settings.autoAdvance,
      hasVideo: !!video,
      videosOnPage: document.querySelectorAll('video').length,
      paused: video ? video.paused : null,
      ended: video ? video.ended : null,
      loop: video ? video.loop : null,
      pipBlocked: video ? !!video.disablePictureInPicture : null,
      currentTime: video ? +video.currentTime.toFixed(2) : null,
      duration: video ? (isFinite(video.duration) ? +video.duration.toFixed(2) : String(video.duration)) : null,
      effectiveDuration: isFinite(dur) ? +dur.toFixed(2) : null,
      seekableEnd: seekEnd,
      playbackRate: video ? video.playbackRate : null,
      pipOpen: !!document.pictureInPictureElement,
      advancedFor: advancedFor,
      pendingAdvance: pendingAdvance
    };
  }

  function initObservers() {
    // URL watcher for SPA navigation; detection itself runs in tick().
    let lastUrl = location.href;
    setInterval(() => {
      if (location.href !== lastUrl) {
        lastUrl = location.href;
        bindVideo(null);
        stopReverse();
        applyVisibility();
      }
    }, 1000);
  }

  async function init() {
    await loadSettings();
    build();
    initObservers();
    applyVisibility();
    paint();
    try {
      window.__reelscrollDebug = debugSnapshot;
    } catch (err) {
      // Sealed window object on this page: snapshot stays unavailable.
    }
    requestAnimationFrame(tick);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
