(function () {
  var CONFIG = { TILE_COUNT: 9, START_MS: 2600, MIN_MS: 900, STEP_MS: 150, NOISE_VARIANTS: 3 };
  var BEST_KEY = 'framewrite:spotTheSlide:bestScore';

  var SLIDE_MARKUP =
    '<span class="slide-bar"></span>' +
    '<span class="slide-lines"><i></i><i></i><i></i></span>' +
    '<span class="slide-chart"><b></b><b></b><b></b></span>';

  var state = {
    status: 'idle',
    score: 0,
    best: 0,
    slideIndex: -1,
    timeoutId: null,
    feedbackTimeoutId: null
  };

  var grid = document.getElementById('game-grid');
  if (!grid) return;

  var startBtn = document.getElementById('game-start');
  var againBtn = document.getElementById('game-again');
  var ctaLink = document.getElementById('game-cta');
  var timerFill = document.getElementById('game-timer-fill');
  var statusEl = document.getElementById('game-status');
  var scoreVal = document.getElementById('game-score-val');
  var bestVal = document.getElementById('game-best-val');
  var endScoreVal = document.getElementById('game-end-score-val');

  function trackEvent(name, params) {
    if (typeof window.gtag === 'function') {
      window.gtag('event', name, params || {});
    }
  }

  var tileEls = [];
  for (var i = 0; i < CONFIG.TILE_COUNT; i++) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'game-tile';
    btn.setAttribute('aria-label', 'Tile ' + (i + 1));
    grid.appendChild(btn);
    tileEls.push(btn);
  }

  function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function loadBest() {
    try {
      return parseInt(localStorage.getItem(BEST_KEY), 10) || 0;
    } catch (e) {
      return 0;
    }
  }

  function saveBestIfNeeded() {
    if (state.score > state.best) {
      state.best = state.score;
      try {
        localStorage.setItem(BEST_KEY, String(state.best));
      } catch (e) {
        /* ignore, e.g. private browsing */
      }
    }
  }

  function announce(message) {
    statusEl.textContent = message;
  }

  function updateHud() {
    scoreVal.textContent = String(state.score);
    bestVal.textContent = String(state.best);
  }

  function showPanel(name) {
    var panels = document.querySelectorAll('[data-panel]');
    for (var i = 0; i < panels.length; i++) {
      panels[i].hidden = panels[i].getAttribute('data-panel') !== name;
    }
  }

  function roundDuration(round) {
    return Math.max(CONFIG.MIN_MS, CONFIG.START_MS - round * CONFIG.STEP_MS);
  }

  function animateTimerBar(duration) {
    timerFill.classList.remove('is-urgent');
    timerFill.style.transition = 'none';
    timerFill.style.transform = 'scaleX(1)';
    // eslint-disable-next-line no-unused-expressions
    timerFill.offsetWidth; // force reflow so the next transition isn't collapsed
    timerFill.style.transition = 'transform ' + duration + 'ms linear';
    timerFill.style.transform = 'scaleX(0)';
    setTimeout(function () {
      if (state.status === 'playing') timerFill.classList.add('is-urgent');
    }, duration * 0.7);
  }

  function startRound() {
    clearTimeout(state.timeoutId);
    clearTimeout(state.feedbackTimeoutId);

    state.slideIndex = Math.floor(Math.random() * CONFIG.TILE_COUNT);

    tileEls.forEach(function (tile, i) {
      tile.classList.remove('is-correct', 'is-wrong', 'game-tile-reveal');
      if (i === state.slideIndex) {
        tile.className = 'game-tile game-tile-slide';
        tile.innerHTML = SLIDE_MARKUP;
      } else {
        var variant = 1 + Math.floor(Math.random() * CONFIG.NOISE_VARIANTS);
        tile.className = 'game-tile game-tile-noise noise-variant-' + variant;
        tile.innerHTML = '';
      }
      tile.setAttribute('aria-label', 'Tile ' + (i + 1));
    });

    var duration = roundDuration(state.score);
    animateTimerBar(duration);
    state.timeoutId = setTimeout(onTimeout, duration);
    announce('Round ' + (state.score + 1) + '. Find the slide!');
  }

  function onCorrect(tile) {
    clearTimeout(state.timeoutId);
    tile.classList.add('is-correct');
    state.score++;
    updateHud();
    announce('Correct! Score: ' + state.score);
    state.feedbackTimeoutId = setTimeout(startRound, prefersReducedMotion() ? 120 : 350);
  }

  function onWrong(tile) {
    clearTimeout(state.timeoutId);
    tile.classList.add('is-wrong');
    tileEls[state.slideIndex].classList.add('game-tile-reveal');
    endGame('Wrong tile — game over.', 'wrong_tile');
  }

  function onTimeout() {
    tileEls[state.slideIndex].classList.add('game-tile-reveal');
    endGame("Time's up — game over.", 'timeout');
  }

  function endGame(message, reason) {
    state.status = 'ended';
    saveBestIfNeeded();
    updateHud();
    announce(message + ' Final score: ' + state.score + '.');
    trackEvent('spot_the_slide_end', { score: state.score, reason: reason });
    state.feedbackTimeoutId = setTimeout(showEndPanel, prefersReducedMotion() ? 150 : 500);
  }

  function showEndPanel() {
    endScoreVal.textContent = String(state.score);
    showPanel('ended');
    if (againBtn) againBtn.focus();
  }

  function resetGame() {
    clearTimeout(state.timeoutId);
    clearTimeout(state.feedbackTimeoutId);
    state.score = 0;
    state.status = 'playing';
    updateHud();
    showPanel('playing');
    startRound();
    trackEvent('spot_the_slide_start');
  }

  grid.addEventListener('click', function (e) {
    if (state.status !== 'playing') return;
    var tile = e.target.closest('.game-tile');
    if (!tile) return;
    var index = tileEls.indexOf(tile);
    if (index === state.slideIndex) {
      onCorrect(tile);
    } else {
      onWrong(tile);
    }
  });

  if (startBtn) startBtn.addEventListener('click', resetGame);
  if (againBtn) againBtn.addEventListener('click', resetGame);
  if (ctaLink) {
    ctaLink.addEventListener('click', function () {
      trackEvent('spot_the_slide_cta_click', { score: state.score });
    });
  }

  state.best = loadBest();
  updateHud();
})();
