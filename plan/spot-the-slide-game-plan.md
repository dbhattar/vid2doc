# Add "Spot the Slide" game to the Framewrite landing page

## Context

The landing page (`index.html` + `styles.css`, static site, no build step, deployed via `netlify.toml`) currently has no interactive element. The goal is a small, purely vanilla-JS game that's genuinely engaging AND reinforces the product's core value prop rather than being generic filler.

Framewrite's "smart frame capture" feature pulls the visuals that matter (slides, diagrams, key moments) out of raw video automatically, so the user never has to scrub footage themselves. The chosen game, **"Spot the Slide,"** turns that exact pain point into a reflex game: a 3×3 grid of tiles appears, one styled like a real presentation slide and the rest styled like meaningless raw-footage noise, and the player races a shrinking timer to click the real one. The payoff line at game end — "Framewrite finds every slide automatically — zero clicks, zero guessing" — closes the loop between the fun and the pitch. No image assets exist for slides/noise, so everything is rendered with pure CSS (gradients, divs), keeping the feature dependency-free.

## Placement

**Update (post-implementation):** placed immediately after `.hero`, before `.whats-new`, per user request for maximum visibility/accessibility right below the fold — not after `.features` as originally scoped below. The original rationale (playing right after reading the "Smart frame capture" card) was outweighed by wanting the game to be one of the very first things a visitor sees. No `.site-nav` link is added for it.

Original plan (superseded): insert between the end of `.features` and the start of `.pricing`, on the theory that the `.features` grid already contains the "Smart frame capture" card the game dramatizes.

**Update (post-implementation):** the color scheme was also made more vibrant than originally spec'd — a stronger radial accent glow behind the section (mirroring `.hero-glow`), a solid-accent eyebrow badge (white text on `var(--accent)` instead of the muted `accent-soft`/navy pill), a 2px accent-colored border + accent-tinted glow shadow on `.game-card`, a gradient timer fill, and more saturated noise-tile patterns — so the game visually pops against the rest of the muted palette instead of blending in.

## HTML structure

All three game states (idle / playing / ended) are separate panels rendered once in the HTML and toggled via the `hidden` attribute — never rebuilt with `innerHTML` swaps at the panel level. This keeps state transitions simple and avoids re-wiring listeners.

```html
<section class="spot-slide" id="spot-the-slide">
  <div class="container">
    <p class="spot-slide-eyebrow">Try it yourself</p>
    <h2>Spot the Slide</h2>
    <p class="spot-slide-intro">
      Nine tiles. One real slide, the rest is raw-footage noise. Click it before time runs out —
      Framewrite does this automatically, every frame, every video.
    </p>
    <div class="game-card">
      <div class="game-idle" data-panel="idle">
        <p class="game-idle-copy">Nine tiles. One slide. Beat the clock.</p>
        <button type="button" class="btn-primary" id="game-start">Play</button>
      </div>
      <div class="game-play-area" data-panel="playing" hidden>
        <div class="game-hud">
          <span class="game-score">Score: <b id="game-score-val">0</b></span>
          <span class="game-best">Best: <b id="game-best-val">0</b></span>
        </div>
        <div class="game-timer-track"><div class="game-timer-fill" id="game-timer-fill"></div></div>
        <p class="game-status" id="game-status" aria-live="polite" aria-atomic="true"></p>
        <div class="game-grid" id="game-grid"></div> <!-- 9 <button class="game-tile"> generated once by game.js -->
      </div>
      <div class="game-end" data-panel="ended" hidden>
        <p class="game-end-score">Final score: <b id="game-end-score-val">0</b></p>
        <p class="game-end-payoff">Framewrite finds every slide automatically — zero clicks, zero guessing.</p>
        <div class="game-end-actions">
          <button type="button" class="btn-primary" id="game-again">Play again</button>
          <a href="https://app.framewrite.cc/login" class="btn-hero-secondary">Get started free &#8594;</a>
        </div>
      </div>
    </div>
  </div>
</section>
```

Reuses `.btn-primary` and `.btn-hero-secondary` (already defined in `styles.css`) for the CTA pair — no new button styles.

Add `<script src="game.js" defer></script>` right before `</body>` (after the `.page-shell` closing `</div>`). Plain classic script (not `type="module"`) so it still works when `index.html` is opened directly via `file://`, matching how this static site is currently tested.

## CSS additions (styles.css)

Append a new block reusing existing tokens exclusively (`var(--surface)`, `var(--border)`, `var(--radius)`, `var(--shadow)`, `var(--accent)`, `var(--navy-soft)`, `var(--text-muted)`, etc. — no new colors):

- **Section/eyebrow/heading/intro**: mirror the `.whats-new` pattern (padding `64px 0 96px`, centered eyebrow pill, centered `h2` ~1.8rem, centered intro `max-width: 520px`).
- **`.game-card`**: reuses the `.feature-card` card recipe (surface bg, border, radius, shadow), `max-width: 480px`, centered, `padding: 28px 24px` (shrinks to `20px 16px` under 640px).
- **HUD/timer**: `.game-hud` flex row for score/best; `.game-timer-track` an 8px rounded bar (`background: var(--border)`) containing `.game-timer-fill` (`background: var(--accent)`, animated via `transform: scaleX()`, switching to a red-ish `.is-urgent` class at 70% elapsed as a discrete, non-motion urgency cue).
- **`.game-grid`**: `display:grid; grid-template-columns: repeat(3,1fr); gap:10px` (gap `8px` under 640px). Stays 3×3 at all widths — tiles shrink via `aspect-ratio:1/1` inside `fr` columns rather than dropping columns, since reducing columns would break the "find 1 of 9" mechanic; tiles remain well above the 44px touch-target minimum even at 375px viewports.
- **`.game-tile-slide`**: pure-CSS "presentation" look — a top color bar (`.slide-bar`), a few gray lines (`.slide-lines i`), and a tiny bar-chart shape (`.slide-chart b`), all positioned with percentages so they scale with the tile.
- **Noise variants** (`.noise-variant-1/2/3`): pure CSS via `repeating-linear-gradient`/`radial-gradient` combos on a blurred `::before` layer (not the tile itself, to keep the tile's own border crisp).
- **Feedback animations**: `.is-correct` (green pulse) / `.is-wrong` (shake) keyframes wrapped in `@media (prefers-reduced-motion: no-preference)`; a `reduce` variant substitutes an instant `box-shadow` swap with `transition: none`.
- **End screen**: simple centered score/payoff/actions styling matching existing muted-text conventions.

## JS architecture (new `game.js`)

Vanilla JS, single file, no dependencies. Key design: the 9 tile `<button>` elements are created **once** at init and mutated in place every round (class/innerHTML/aria-label swapped, never removed/recreated). This guarantees exactly one delegated click listener ever exists on `#game-grid`, keyboard focus naturally survives across rounds, and "Play again" never risks leaking listeners or duplicate timers.

- **State**: `{ status: 'idle'|'playing'|'ended', score, best, slideIndex, timeoutId, feedbackTimeoutId }`.
- **Difficulty ramp**: `roundDuration(round) = max(MIN_MS=900, START_MS=2600 - round*STEP_MS=150)`, floors at score 12.
- **Round start**: randomize `slideIndex` among 9 tiles; assign the slide tile the slide markup/class, assign the other 8 a random noise variant (1-3); animate the timer bar; set an authoritative `setTimeout(onTimeout, duration)` — the CSS transition is purely cosmetic, the real win/lose decision is driven by this independent timeout so it can't be thrown off by tab-throttling or reduced-motion overrides.
- **Timer bar**: CSS `transform: scaleX()` transition (reset via `transition: none` + forced reflow before re-triggering), not `requestAnimationFrame` — appropriate for a decorative widget and avoids coupling gameplay correctness to rendering/rAF pausing in backgrounded tabs.
- **Click handling**: single delegated listener on `#game-grid`, ignored unless `state.status === 'playing'` (cheaply absorbs stray clicks during the brief flash window between rounds).
- **Win**: increment score, flash `.is-correct`, announce via the live region, start next round after a short delay.
- **Lose** (wrong click or timeout): flash `.is-wrong` on the clicked tile (if applicable) and reveal the real slide tile, announce final score, transition to the end panel, move focus to `#game-again`.
- **Best score**: `localStorage` key `framewrite:spotTheSlide:bestScore`, read/write wrapped in try/catch (private-browsing contexts can throw).
- **Reset**: `#game-start` and `#game-again` both call the same `resetGame()`, which clears any pending timers before starting fresh — rapid repeated clicks can't produce overlapping timer chains.

## Accessibility

- Tiles are real `<button>` elements — free keyboard focus/activation, reuses the existing global `button:focus-visible` outline in `styles.css`.
- `#game-status` is `aria-live="polite"`, updated only on discrete state changes (round start/correct/wrong/timeout), never per-frame.
- `prefers-reduced-motion: reduce` disables the pulse/shake keyframes in favor of an instant color swap; the timer bar keeps a non-motion `.is-urgent` color cue.
- Honest limitation (won't be papered over): this is a visual pattern-recognition game — tile `aria-label`s stay generic ("Tile 1"..."Tile 9") rather than describing "slide" vs "noise", since doing so would trivially solve the game for screen-reader users. What is accessible: full keyboard operability and correct live-region state announcements.

## Files touched

- `index.html` — new `<section id="spot-the-slide">` between `.features` and `.pricing`, plus one new `<script src="game.js" defer>` before `</body>`.
- `styles.css` — new rules appended, reusing existing custom properties and section/card conventions.
- `game.js` (new) — all game logic, no build step required; `netlify.toml`'s `publish = "."` already serves it as-is alongside `index.html`.

## Verification

1. Open `index.html` directly via `file://` (double-click) to confirm it works with zero build step; also check via a local static server since `localStorage` behaves differently under `file://` in some browsers.
2. Scroll to the new section, click "Play" — confirm exactly one slide-styled tile appears among 8 noise tiles, and the timer bar animates down.
3. Win several rounds in a row — confirm score increments, status text updates, and each round's timer duration visibly shrinks, flooring at 900ms.
4. Lose via clicking a wrong tile — confirm the wrong-tile flash, the real slide tile is revealed, and the end screen shows the correct final score, payoff copy, "Play again," and the "Get started free" link.
5. Lose via letting the timer run out — confirm the same end screen with the timeout-specific status message.
6. Click "Play again" repeatedly (including rapid double-clicks) — confirm score resets cleanly each time with no skipped/double-incrementing rounds.
7. Resize to a mobile width (~375px) in DevTools — confirm the grid stays 3×3, tiles stay comfortably tappable, and spacing matches the 640px breakpoint.
8. Keyboard-only pass — Tab into "Play", Tab across the 9 tiles, Enter the correct one, confirm focus behavior and that focus lands on "Play again" at game end.
9. Emulate `prefers-reduced-motion: reduce` in DevTools Rendering tab — confirm feedback becomes an instant color change with no shake/pulse.
10. Check the browser console for errors across all flows, and confirm the best-score `localStorage` value persists across a page reload.
11. Confirm existing nav anchors (`#whats-new`, `#features`, `#pricing`, `#signup`) still scroll correctly and the new section's spacing matches its siblings.
