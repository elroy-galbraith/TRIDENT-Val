# Micro-world learnings log

Read this before building; append after the user has used the result. Dated,
newest first. Keep entries actionable without the original session's context.
When a learning becomes general method, promote it into SKILL.md or
references/engine.md and mark it `[promoted]` here.

---

## 2026-07-28 — disagreement-queue (second build; first via the skill)

**Build-time notes (user signal to be appended after use):**
- The seeded pitfalls worked: no comment-glob bug, no replace-chain corruption, and the
  harness passed on the first run. The verification cost dropped from three debug cycles
  (build 1) to zero.
- The axis-caption/end-tick collision recurred in a *new* chart form (histogram caption vs
  right-edge tick labels) — it is evidently a class of bug, not an incident. `[promoted]`
  into references/engine.md as a standing rule: leave the last tick(s) off any axis that
  also carries an end-anchored caption.
- New pitfall: a signed-percent formatter applied to a *magnitude* column (queue ranked by
  |divergence| displayed "+25.0%" for what was a −25% dissent). Rule: ranking/magnitude
  columns get unsigned formatting; signed formatting only where direction is the point.
- Design move that worked again: the previous build's central lesson (selection pressure,
  error independence) became this build's *payoff act* — the clone-fleet counterfactual
  directly dramatizes "agreement ≠ accuracy". Sequencing micro-worlds so each one's verdict
  seeds the next one's tension makes the set teach more than the sum of pages.
- Mechanism detail worth reusing: when two subsystems compose (triage decision re-deriving
  audit status through the variance bands), stage the composition as a single visible state
  cascade in one API response — it landed harder than explaining either net alone.

---

## 2026-07-28 — automl-openevolve-seeding (first build)

**User-question signal (the best kind):** after using the world, the user asked
*"why does the LLM only tweak the AutoML seed instead of deeply altering it, while
the naive seed gets restructured?"* The world showed the divergence but
under-taught its cause — that **selection pressure, not the LLM's disposition,
drives conservatism** (a strong parent makes bold mutations score worse, so only
timid lineages survive; exploitation_ratio then compounds it). Next time a
simulation shows two branches diverging, narrate the *incentive* at the exact
step divergence first appears, and consider an instrument that shows the payoff
of bold vs. timid moves directly (e.g., a small "return on mutation size" readout
per generation). The answer that finally landed used: selection-not-creativity,
payoff landscape/headroom, prompt anchoring via inspiration programs,
valley-crossing, and the fine-tuning-stays-near-pretrained-weights analogy.

**Pitfalls hit (all caught by the verification gates, none by inspection):**
- A file glob inside a JS block comment (`model/*/manifest.json`) — the `*/`
  terminates the comment and breaks the whole script. Never put paths with `*/`
  in JS comments. `[promoted]` into the harness gate.
- Deriving code variants via `.replace()` chains: a too-generic target
  (`"    ])"`) matched an earlier bracket and silently corrupted a variant.
  Every derived variant must be asserted `!==` its base and spot-checked for a
  content marker. `[promoted]` into SKILL.md step 6.
- Chart axis caption ("generation →") collided with the final tick label at the
  right edge — render ticks short of the end or move the caption; caught only by
  screenshots, not the harness.
- Literal control characters used as tokenizer sentinels survived editing by
  luck; write them as explicit `\u0001` escapes.

**Design moves that landed (user said the world "really helped"):**
- Real recorded numbers as anchors (manifests' 7.88/8.02/7.82) plus one trace
  that ends line-for-line on the real winning program — and an explicit honesty
  note labeling the other trace as a scripted hypothetical. Trust survived
  scrutiny because the labeling came first.
- Autoplay hard-stopping at the seed decision forced engagement with the fork —
  the central tension became a choice the user made, not a paragraph they read.
- Failure generations as first-class steps (error → score 0 → evaluator artifact
  → visibly informed retry next generation) taught the feedback loop better than
  any success step.
- Fold-to-snapshot state (`snapshot(idx)` replays events) made scrubbing instant
  and kept the data model event-shaped and small.
- Concept tags as step eyebrows ("FEEDBACK LOOP", "MIGRATION", "DEAD END") gave
  the user vocabulary they reused in their follow-up questions.

**Context worth keeping:** OpenEvolve itself ships `scripts/visualizer.py`, a
real-data dashboard (evolution tree, diffs, MAP-Elites grid) over run
checkpoints. A micro-world is the *pedagogical* complement (why it happens), not
a substitute for it (what happened) — say so when relevant, and point at it when
the user wants to review an actual run.
