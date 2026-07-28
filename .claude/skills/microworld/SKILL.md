---
name: microworld
description: Build a "micro-world" — an interactive, scrubbable, self-contained HTML simulation that teaches how a system in this repo actually works, grounded in its real code and recorded numbers (in the spirit of Papert's mathland and Geoffrey Litt's ephemeral debugger UIs). Use this whenever the user is trying to *understand* a mechanism rather than change it — "help me understand X", "why does X do Y", "walk me through how the pipeline works", "visualize/simulate/demo how X behaves", "build me something like the ADR-0018 micro-world" — even if they never say "simulation" or "micro-world". Also use it when the user asks to extend or fix an existing page under docs/microworlds/. Do NOT use it for product dashboards over live data, ordinary charts, or one-off diagrams; those need dataviz alone.
---

# Micro-world builder

A micro-world lets someone learn a system the way children learn French in France:
by inhabiting it. The deliverable is a single self-contained HTML page with a
scrubbable timeline, a narrated stage, and live instruments — a *bespoke educational
simulation* of one mechanism in this repo, not a generic explainer.

**Before anything else, read `LEARNINGS.md` in this skill's directory.** It is the
accumulated experience of every previous build — pitfalls that cost real debugging
time and design moves that measurably helped understanding. It exists so each
micro-world starts where the last one left off. After delivering, you will append
to it (step 8); that loop is the whole point of this file's existence.

## The method

### 1. Ground the world in truth
Read the real artifacts first — source files, configs, ADRs, manifests, recorded
metrics — and build the world out of them: real file paths in panel headers, real
hyperparameters in the code views, real recorded numbers on the scoreboard. Where
the simulation must invent (a hypothetical branch, interpolated intermediate
values), label it explicitly in the page's briefing ("nothing runs for real; trace
X mirrors the recorded outcome, trace Y is a scripted hypothetical"). The value of
a micro-world over a textbook diagram is precisely that it maps onto *their*
system; one fabricated number presented as real destroys that trust.

### 2. Find the central tension
A micro-world teaches **one decision or mechanism**, not the whole system. Before
designing anything, answer: *what question does this world exist to answer?* (The
first one answered ADR-0018's: "what should the search be seeded with?") If the
question is a fork, make the fork playable — let the user choose a branch and
watch both under the same budget. If the user's request is broad ("how does the
backend work"), narrow it with them or pick the mechanism their recent questions
circle around.

### 3. Design as a scrubbable tape
This is Litt's debugger insight and the load-bearing architecture:

- Precompute the entire run as a **deterministic sequence of steps** (data, not
  behavior). Nothing executes for real at view time.
- Derive all UI state by **folding the event list up to the current index** — a
  `snapshot(idx)` function — so any step renders instantly, in any order, and
  scrubbing backwards is free.
- Give every step a **narration** in a teaching voice (2–4 sentences: what just
  happened, why, what to look at) plus a short concept tag ("FEEDBACK LOOP",
  "MIGRATION", "DEAD END"). The narration carries the pedagogy; the visuals carry
  the evidence.
- Autoplay must **stop at decision points** and at the end — a fork the tape
  rolls through is a fork the user never felt.

### 4. Stage + instruments
Two synchronized views, so cause and cumulative effect are visible at once:
- **Stage** (what is happening now): code shown as a *diff against its parent*,
  verdicts, error artifacts, the current actor.
- **Instruments** (what has happened so far): progression chart, state grids,
  populations, a scoreboard of real reference numbers.
Make invisible boundaries visible — if part of the system is mutable and part is
frozen (an EVOLVE-BLOCK vs. its evaluator), draw the wall and tag the panels.
Include failures as first-class steps: a candidate that errors, scores zero, and
feeds artifacts forward teaches more than five successes.

### 5. Build it
One self-contained HTML file, no external resources. Load the `artifact-design`
skill before writing the page and the `dataviz` skill before any chart (validate
the palette with its script — don't eyeball). Support light and dark themes,
keyboard scrubbing (←/→/space) plus click-to-jump, hover tooltips, a briefing
modal (cast of concepts + controls + the honesty note), and reduced-motion
guards. Structural details and reusable skeleton: read `references/engine.md`.

### 6. Verify mechanically before showing anyone
Hand-authored trace data has many derived strings; errors hide until someone
scrubs to them. Two gates, both required:
1. **Harness**: extract the page's script, run it in `node` `vm` with a minimal
   DOM stub, and walk *every step of every branch* through the real render
   pipeline; fail on thrown errors, unbalanced markup, or `undefined`/`NaN`
   appearing in rendered HTML. Assert that every derived artifact (e.g., code
   variants built by string replacement) actually differs from its base — a
   silently-missed replace target renders as an empty diff, which no one notices
   until it confuses the learner. Harness pattern: `references/engine.md`.
2. **Eyes**: screenshot light *and* dark with the pre-installed Chromium
   (`playwright-core`, `executablePath: '/opt/pw-browsers/chromium'`) at several
   representative steps, and actually look — the harness checks logic, not label
   collisions or overflow.

### 7. Deliver
Publish as an artifact (the fragment form the Artifact tool expects) **and**
commit a full-document copy under `docs/microworlds/` (wrap with
doctype/html/head/body so it opens standalone without quirks mode), adding an
entry to `docs/microworlds/README.md`. Follow the session's normal branch/PR
rules.

### 8. Close the loop — append to LEARNINGS.md
After the user has actually used the world, add a dated entry. The richest
signal is **the questions they ask afterwards**: a question means the world
showed the *what* but under-taught the *why* at that point — record it and what
would have taught it. Also record: pitfalls hit during the build (with the fix),
design moves that landed, verification gaps the harness or screenshots caught.
Keep entries specific enough that a future build can act on them without this
session's context. If a learning generalizes into method, promote it into this
file or `references/engine.md` and note the promotion in the log — the log is a
queue for improving the skill, not just a diary.
