# Micro-worlds

Interactive, self-contained simulations that make a piece of this repo's machinery tangible —
in the spirit of Seymour Papert's "mathland": instead of reading about a system, you inhabit a
small world where its mechanics are visible and scrubbable.

Each file is a single static HTML page with no dependencies and no network access. Open it
directly in a browser (`open docs/microworlds/<name>.html` or via any static file server).
Nothing trains or executes for real — the runs are scripted traces, annotated step by step.

## automl-openevolve-seeding.html

A guided replay of how `evolved_v1` came to exist (ADR 0018), built around the ADR's central
question: **what should an evolutionary code search be seeded with?**

- **Act 1 — AutoML sweep.** Twelve simulated tuning trials converge on a boosted-tree config,
  illustrating both what AutoML is good at (efficient hyperparameter search) and its
  architectural anchoring (it reliably lands on the same families).
- **The seed decision.** Two "cartridges": the AutoML winner (accuracy goal) vs. the simple
  bagged-ExtraTrees seed the real run used (diversity goal). Both are playable.
- **Act 2 — OpenEvolve.** Fifteen generations per seed: LLM diffs against the `EVOLVE-BLOCK`,
  the frozen evaluator (same holdout split and MAPE/R² as the champion), failure artifacts
  feeding back into prompts, a MAP-Elites archive, two islands with a gen-10 migration.
- **Compare view.** Both seeds under the same budget, side by side — the experiment ADR 0018
  proposes, acted out.

Grounding: registry metrics come from the real `model/*/manifest.json` files, the search shape
from `scripts/evolve/config.yaml`, and the simple-seed trace ends, line for line, on the actual
`model/evolved_v1/evolved_program.py` (holdout MAPE 7.82%, R² 0.9415). The AutoML-seeded trace
is a plausible hypothetical dramatizing the ADR's reasoning, and is labeled as such in the page.

## disagreement-queue.html

Five assets walked through the champion/challenger machinery of ADR 0008 — how a model
disagreement becomes a logged human decision.

- **Shadow scoring.** The champion books every value; two challengers score the same
  portfolio in shadow. Each sample asset shows *why* a challenger dissents (linear
  blindness to interactions, the evolved model's comparables voice, correlated dissent).
- **The sensitivity dial** — the playable decision: divergence threshold 5% / 10% / 20%
  (the real ModelCompare options; 10% is `reports.py`'s `DISAGREEMENT_THRESHOLD`). Depth
  changes; ranking never does.
- **Triage.** Real request/response shapes for `POST /properties/{pid}/triage-decision`:
  accept champion, adopt a challenger, manual override — plus the 422 an empty rationale
  earns, and the audit-status cascade through ADR 0004's variance bands.
- **The payoff.** Layered nets, the adverse-selection anti-pattern, and a clone-fleet
  counterfactual showing why disagreement is only a signal when models fail differently.

Grounding: mechanism, endpoints, thresholds, bands, role gates, and log formats are real;
the five sample assets, portfolio divergence distribution, and error-overlap figures are
illustrative and labeled as such in the page's briefing.
