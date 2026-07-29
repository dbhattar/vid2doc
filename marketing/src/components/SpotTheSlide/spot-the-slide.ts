declare global {
  interface Window {
    gtag?: (...args: unknown[]) => void;
  }
}

const CONFIG = { TILE_COUNT: 9, START_MS: 2600, MIN_MS: 900, STEP_MS: 150, NOISE_VARIANTS: 3 };
const BEST_KEY = 'framewrite:spotTheSlide:bestScore';

const SLIDE_MARKUP =
  '<span class="slide-bar"></span>' +
  '<span class="slide-lines"><i></i><i></i><i></i></span>' +
  '<span class="slide-chart"><b></b><b></b><b></b></span>';

type Status = 'idle' | 'playing' | 'ended';

const state: {
  status: Status;
  score: number;
  best: number;
  slideIndex: number;
  timeoutId: ReturnType<typeof setTimeout> | undefined;
  feedbackTimeoutId: ReturnType<typeof setTimeout> | undefined;
} = {
  status: 'idle',
  score: 0,
  best: 0,
  slideIndex: -1,
  timeoutId: undefined,
  feedbackTimeoutId: undefined,
};

const grid = document.getElementById('game-grid');

if (grid) {
  const startBtn = document.getElementById('game-start');
  const againBtn = document.getElementById('game-again');
  const ctaLink = document.getElementById('game-cta');
  const timerFill = document.getElementById('game-timer-fill') as HTMLElement;
  const statusEl = document.getElementById('game-status') as HTMLElement;
  const scoreVal = document.getElementById('game-score-val') as HTMLElement;
  const bestVal = document.getElementById('game-best-val') as HTMLElement;
  const endScoreVal = document.getElementById('game-end-score-val') as HTMLElement;

  const trackEvent = (name: string, params?: Record<string, unknown>) => {
    if (typeof window.gtag === 'function') {
      window.gtag('event', name, params || {});
    }
  };

  const tileEls: HTMLButtonElement[] = [];
  for (let i = 0; i < CONFIG.TILE_COUNT; i++) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'game-tile';
    btn.setAttribute('aria-label', `Tile ${i + 1}`);
    grid.appendChild(btn);
    tileEls.push(btn);
  }

  const prefersReducedMotion = () =>
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const loadBest = (): number => {
    try {
      return parseInt(localStorage.getItem(BEST_KEY) || '', 10) || 0;
    } catch {
      return 0;
    }
  };

  const saveBestIfNeeded = () => {
    if (state.score > state.best) {
      state.best = state.score;
      try {
        localStorage.setItem(BEST_KEY, String(state.best));
      } catch {
        /* ignore, e.g. private browsing */
      }
    }
  };

  const announce = (message: string) => {
    statusEl.textContent = message;
  };

  const updateHud = () => {
    scoreVal.textContent = String(state.score);
    bestVal.textContent = String(state.best);
  };

  const showPanel = (name: string) => {
    document.querySelectorAll<HTMLElement>('[data-panel]').forEach((panel) => {
      panel.hidden = panel.getAttribute('data-panel') !== name;
    });
  };

  const roundDuration = (round: number) => Math.max(CONFIG.MIN_MS, CONFIG.START_MS - round * CONFIG.STEP_MS);

  const animateTimerBar = (duration: number) => {
    timerFill.classList.remove('is-urgent');
    timerFill.style.transition = 'none';
    timerFill.style.transform = 'scaleX(1)';
    // eslint-disable-next-line no-unused-expressions
    timerFill.offsetWidth; // force reflow so the next transition isn't collapsed
    timerFill.style.transition = `transform ${duration}ms linear`;
    timerFill.style.transform = 'scaleX(0)';
    setTimeout(() => {
      if (state.status === 'playing') timerFill.classList.add('is-urgent');
    }, duration * 0.7);
  };

  const startRound = () => {
    clearTimeout(state.timeoutId);
    clearTimeout(state.feedbackTimeoutId);

    state.slideIndex = Math.floor(Math.random() * CONFIG.TILE_COUNT);

    tileEls.forEach((tile, i) => {
      tile.classList.remove('is-correct', 'is-wrong', 'game-tile-reveal');
      if (i === state.slideIndex) {
        tile.className = 'game-tile game-tile-slide';
        tile.innerHTML = SLIDE_MARKUP;
      } else {
        const variant = 1 + Math.floor(Math.random() * CONFIG.NOISE_VARIANTS);
        tile.className = `game-tile game-tile-noise noise-variant-${variant}`;
        tile.innerHTML = '';
      }
      tile.setAttribute('aria-label', `Tile ${i + 1}`);
    });

    const duration = roundDuration(state.score);
    animateTimerBar(duration);
    state.timeoutId = setTimeout(onTimeout, duration);
    announce(`Round ${state.score + 1}. Find the slide!`);
  };

  function onCorrect(tile: HTMLButtonElement) {
    clearTimeout(state.timeoutId);
    tile.classList.add('is-correct');
    state.score++;
    updateHud();
    announce(`Correct! Score: ${state.score}`);
    state.feedbackTimeoutId = setTimeout(startRound, prefersReducedMotion() ? 120 : 350);
  }

  function onWrong(tile: HTMLButtonElement) {
    clearTimeout(state.timeoutId);
    tile.classList.add('is-wrong');
    tileEls[state.slideIndex].classList.add('game-tile-reveal');
    endGame('Wrong tile — game over.', 'wrong_tile');
  }

  function onTimeout() {
    tileEls[state.slideIndex].classList.add('game-tile-reveal');
    endGame("Time's up — game over.", 'timeout');
  }

  function endGame(message: string, reason: string) {
    state.status = 'ended';
    saveBestIfNeeded();
    updateHud();
    announce(`${message} Final score: ${state.score}.`);
    trackEvent('spot_the_slide_end', { score: state.score, reason });
    state.feedbackTimeoutId = setTimeout(showEndPanel, prefersReducedMotion() ? 150 : 500);
  }

  function showEndPanel() {
    endScoreVal.textContent = String(state.score);
    showPanel('ended');
    if (againBtn) (againBtn as HTMLElement).focus();
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

  grid.addEventListener('click', (e) => {
    if (state.status !== 'playing') return;
    const tile = (e.target as HTMLElement).closest('.game-tile') as HTMLButtonElement | null;
    if (!tile) return;
    const index = tileEls.indexOf(tile);
    if (index === state.slideIndex) {
      onCorrect(tile);
    } else {
      onWrong(tile);
    }
  });

  if (startBtn) startBtn.addEventListener('click', resetGame);
  if (againBtn) againBtn.addEventListener('click', resetGame);
  if (ctaLink) {
    ctaLink.addEventListener('click', () => {
      trackEvent('spot_the_slide_cta_click', { score: state.score });
    });
  }

  state.best = loadBest();
  updateHud();
}

export {};
