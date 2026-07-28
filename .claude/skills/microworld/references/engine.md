# Micro-world engine pattern

The canonical, fully-worked example is `docs/microworlds/automl-openevolve-seeding.html`
(committed at repo root). Crib its structure; don't re-derive it. This file is the
map of that structure plus the verification harness pattern.

## Page anatomy

```
<title> + <style>            one style block; CSS custom properties for all color
header                       title, mode/branch switch, Briefing + Compare buttons
main (2-col grid)
  ├─ story column            narration card (serif teaching voice) + stage card
  └─ instruments column      chart card, state-grid card, population card, scoreboard
footer .tape (fixed bottom)  play/prev/next, step counter, one <button> per step,
                             phase-colored segments, phase labels underneath
modals                       briefing (cast + controls + honesty note), compare view
#tip                         one shared tooltip div, driven by [data-tip] delegation
```

Theme tokens: define light values on `:root`, dark under BOTH
`@media (prefers-color-scheme: dark)` with a `:root:where(:not([data-theme="light"]))`
guard AND `:root[data-theme="dark"]`, plus an explicit `:root[data-theme="light"]`
block — the host's theme toggle must beat the OS setting in both directions.
Charts: take palette hexes from the dataviz skill's reference palette and run its
validator for both surfaces before shipping.

## Data model (events, not state)

```js
const STEPS = buildSteps(branch);   // flat array; each step: {phase, kind, title,
                                    //  concept, narr, ...payload}
function snapshot(idx) {            // fold events 0..idx into derived state:
  // accumulate points, archives (Map keyed by cell), populations, best-so-far…
}
function render() {                 // pure function of (state.idx, state.branch):
  // narration card, stage by step.kind, each instrument, tape playhead
}
```

Rules that keep this robust:
- `Date.now()`/randomness have no place in the trace — determinism is what makes
  scrubbing coherent.
- Branch switching rebuilds `STEPS` and clamps `state.idx` back to the fork step.
- Autoplay is a `setTimeout` chain with per-phase dwell times; it stops at the
  fork step and the last step, and any manual navigation stops it.
- Code shown per step is *derived*: store full program text per candidate, compute
  a line diff (simple LCS) against its **parent's** text at render time. When
  deriving variant texts with `.replace()`, make each target string long enough
  to be unique — then assert it (see harness).
- Keyboard: ←/→ step, space play/pause, Escape closes modals; skip handling when
  a modal is open or focus is in an input.

## Verification harness (run before showing anyone)

Pattern (worked example: `scripts/check.example.mjs` in this skill directory):
extract the page's `<script>` body, run it in `node:vm` with a ~40-line DOM
stub, then run assertions *inside the same context* so they see the page's real
top-level bindings. The screenshot pass has a worked example too:
`scripts/shot.example.mjs`.

DOM stub essentials: `document.querySelector` returns memoized stub elements
(`classList`, `addEventListener`, `setAttribute/getAttribute`, `querySelectorAll → []`,
`style`, `hidden`); `document.querySelectorAll → []`; an `innerHTML` **setter that
validates** — throw on unbalanced `<div>/<span>/<table>/<tr>/<td>/<button>/<pre>`
counts and on `undefined`/`NaN` appearing in the string. That setter is the
workhorse: it turns every render into an assertion.

Assert at minimum:
1. Every derived text variant `!==` its base, and contains a distinguishing
   marker string (catches silently-missed replace targets).
2. Every step of **every branch** renders: `for each branch { setBranch(b);
   for (i of steps) go(i) }` without throwing; modal/compare renderers too.
3. Every event's parent/reference IDs resolve, cells/indices are in range,
   failure events carry their error payloads.
4. Endpoint invariants: best-so-far series ends on the stated final numbers; any
   trace claiming to mirror a real recorded outcome matches it exactly.

Known JS-in-HTML traps: no `*/` inside block comments (file globs!); write
sentinel characters as `\u0001`-style escapes, never as literal control bytes.

## Screenshot pass

`playwright-core` + the pre-installed Chromium
(`executablePath: '/opt/pw-browsers/chromium'`, don't `playwright install`).
Shoot both `colorScheme: 'light'` and `'dark'` at representative steps: briefing,
one mid-phase step, the fork, a failure step, the finale, the compare modal
(use `page.evaluate(() => go(n))` to jump). Look for: label/tick collisions,
overflow, unreadable contrast, fixed-footer overlap. The harness cannot see any
of these.

Standing chart rules (each earned by a screenshot catch in a real build):
- An end-anchored axis caption and the last tick label(s) will collide — leave
  the final tick(s) off any axis that also carries a caption.
- Columns ranked by magnitude (|divergence|, |error|) get unsigned formatting;
  a signed formatter there mislabels negative values as positive.

## Delivery shapes

- **Artifact**: the fragment file itself (starts at `<title>`; no doctype/html/
  head/body — the publisher wraps it).
- **Repo copy** (`docs/microworlds/<name>.html`): same content wrapped in
  `<!doctype html><html lang="en"><head><meta charset><meta viewport>…` so it
  opens standalone in standards mode. Generate it from the fragment; don't
  maintain two sources. Add a paragraph to `docs/microworlds/README.md`.
