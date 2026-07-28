// Worked example: verification harness for docs/microworlds/automl-openevolve-seeding.html.
// Adapt the DOM stub + assertion pattern for each new micro-world (see references/engine.md).
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(new URL("./automl-openevolve-microworld.html", import.meta.url), "utf8");
const m = html.match(/<script>([\s\S]*)<\/script>/);
if (!m) { console.error("no <script> block found"); process.exit(1); }
const src = m[1];

// ---- minimal DOM stub ----
const makeEl = () => {
  const el = {
    _html: "", _attrs: new Map(), hidden: false, textContent: "",
    style: {}, dataset: {},
    classList: { add(){}, remove(){}, toggle(){} },
    addEventListener(){}, setAttribute(k, v){ this._attrs.set(k, String(v)); },
    getAttribute(k){ return this._attrs.get(k) ?? null; },
    querySelectorAll(){ return []; },
    appendChild(){}, closest(){ return null; },
  };
  Object.defineProperty(el, "innerHTML", {
    get(){ return this._html; },
    set(v){
      this._html = v;
      // crude sanity: flag unbalanced span/div/table tags
      for (const tag of ["div", "span", "table", "tr", "td", "th", "button", "pre", "details"]) {
        const open = (v.match(new RegExp(`<${tag}[\\s>]`, "g")) || []).length;
        const close = (v.match(new RegExp(`</${tag}>`, "g")) || []).length;
        if (open !== close) throw new Error(`unbalanced <${tag}> (${open} open / ${close} close) in innerHTML: ${v.slice(0, 120)}...`);
      }
      if (v.includes("undefined") || v.includes("NaN")) {
        throw new Error(`suspicious 'undefined'/'NaN' in innerHTML: ...${v.slice(Math.max(0, v.search(/undefined|NaN/) - 80), v.search(/undefined|NaN/) + 40)}...`);
      }
    },
  });
  return el;
};
const els = new Map();
const doc = {
  querySelector(sel){ if (!els.has(sel)) els.set(sel, makeEl()); return els.get(sel); },
  querySelectorAll(){ return []; },
  addEventListener(){}, createElement(){ return makeEl(); }, createTextNode(t){ return { t }; },
};
const sandbox = { document: doc, window: { innerWidth: 1280, innerHeight: 800 }, console, clearTimeout, setTimeout: () => 0 };
vm.createContext(sandbox);
vm.runInContext(src, sandbox, { filename: "artifact.js" });

const tests = `
(() => {
  const fails = [];
  const ok = (cond, msg) => { if (!cond) fails.push(msg); };

  // 1. derived code variants must differ from their bases (replace targets matched)
  const derived = [
    ["a1","seedA"],["a3","seedA"],["a5","a2"],["a6","a4"],["a7","a5"],["a8","a7"],["a9","a7"],
    ["a10","a7"],["a11","a8"],["a12","a11"],["a13","a11"],["a14","a13"],["a15","a10"],
    ["b1","seedB"],["b2","seedB"],["b4","b3"],["b5","b4"],["b6","b2"],["b7","b5"],["b8","b7"],
    ["b9","b7"],["b10","b9"],["b11","b9"],["b12","b11"],["b14","b13"],["b15","b13"],
  ];
  for (const [d, b] of derived) ok(C[d] && C[b] && C[d] !== C[b], "variant " + d + " identical to base " + b + " (replace target missed)");

  // 2. content markers per variant
  const marks = {
    a1:"learning_rate=0.04", a3:"TargetEncoder", a4:"OrdinalEncoder", a5:"VotingRegressor",
    a6:"KNeighborsRegressor", a7:"weights=[0.6, 0.4]", a8:'("et"', a9:"StackingRegressor",
    a10:"learning_rate=0.06", a11:"weights=[0.5, 0.35, 0.15]", a12:"weights=[0.4, 0.25, 0.35]",
    a13:"early_stopping=True", a14:"min_samples_leaf=12", a15:'weights=[0.55, 0.35, 0.1]',
    b1:"n_estimators=350", b2:"RandomForestRegressor", b3:"VotingRegressor",
    b4:'weights="dist"', b5:'weights="distance"', b6:"n_neighbors=15", b7:"weights=[0.45, 0.35, 0.2]",
    b8:"sf_per_room", b9:"max_depth=4", b10:"RobustScaler", b11:"weights=[0.42, 0.38, 0.2]",
    b12:"n_neighbors=11", b13:"l2_regularization=0.1", b14:"SVR", b15:"min_samples_leaf=3",
  };
  for (const [k, needle] of Object.entries(marks)) ok(C[k] && C[k].includes(needle), "C." + k + " missing marker: " + needle);
  ok(C.a8.includes("weights=[0.6, 0.4]") && (C.a8.match(/\\("(sq|ab|et)"/g) || []).length === 3, "a8 must have 3 estimators + stale 2 weights");

  // 3. every gen resolves a parent program and produces a non-empty diff
  for (const trace of [TRACE_A, TRACE_B]) {
    const ids = new Set(["seed"]);
    for (const g of trace.gens) {
      const pid = g.parent.replace(" (migrant)", "");
      ok(ids.has(pid), trace.key + " gen " + g.g + ": parent '" + pid + "' not defined before it");
      ids.add(g.id);
      const parentCode = pid === "seed" ? trace.seed.code : trace.gens.find(x => x.id === pid).code;
      const d = lineDiff(parentCode, g.code);
      ok(d.some(r => r.t !== "same"), trace.key + " gen " + g.g + ": empty diff vs parent " + pid);
      if (g.ok) {
        ok(g.cell && g.cell[0] >= 0 && g.cell[0] < 5 && g.cell[1] >= 0 && g.cell[1] < 4, trace.key + " gen " + g.g + ": cell out of range");
        ok(typeof g.mape === "number" && typeof g.r2 === "number", trace.key + " gen " + g.g + ": missing metrics");
      } else {
        ok(g.err && g.err.type && g.err.msg && g.err.sugg, trace.key + " gen " + g.g + ": failed gen missing err payload");
      }
    }
    ok(trace.gens.length === 15, trace.key + ": expected 15 gens, got " + trace.gens.length);
  }

  // 4. best-so-far endpoints match the stated finals
  const endA = bestSeries(TRACE_A).at(-1).v, endB = bestSeries(TRACE_B).at(-1).v;
  ok(Math.abs(endA - TRACE_A.final.best.mape) < 1e-9, "trace A best series end " + endA + " != final " + TRACE_A.final.best.mape);
  ok(Math.abs(endB - TRACE_B.final.best.mape) < 1e-9, "trace B best series end " + endB + " != final " + TRACE_B.final.best.mape);
  ok(Math.abs(endB - 7.82) < 1e-9, "trace B must land on the real evolved_v1 MAPE 7.82");

  // 5. b13 code must equal the real evolved_program EVOLVE-BLOCK signature bits
  for (const frag of ["n_estimators=350", "max_depth=4, learning_rate=0.08", "l2_regularization=0.1", 'n_neighbors=9, weights="distance", p=1', "weights=[0.42, 0.38, 0.2]"])
    ok(C.b13.includes(frag), "b13 missing real-program fragment: " + frag);

  // 6. walk every step of both seeds through the full render pipeline
  for (const seed of ["automl", "simple"]) {
    setSeed(seed);
    for (let i = 0; i < STEPS.length; i++) {
      try { go(i); } catch (e) { fails.push(seed + " step " + i + " render threw: " + e.message); break; }
    }
  }
  try { openCompare(); } catch (e) { fails.push("openCompare threw: " + e.message); }

  // 7. snapshot invariants at the final step
  setSeed("simple"); go(STEPS.length - 1);
  const snap = snapshot(STEPS.length - 1);
  ok(snap.done && snap.best && Math.abs(snap.best.mape - 7.82) < 1e-9, "simple-seed final snapshot best != 7.82 (got " + (snap.best && snap.best.mape) + ")");
  ok(snap.archive.size >= 6, "simple-seed archive too sparse: " + snap.archive.size);
  setSeed("automl"); go(STEPS.length - 1);
  const snapA = snapshot(STEPS.length - 1);
  ok(Math.abs(snapA.best.mape - 7.77) < 1e-9, "automl-seed final best != 7.77 (got " + snapA.best.mape + ")");

  if (fails.length) { console.error("FAIL\\n" + fails.map(f => " - " + f).join("\\n")); throw new Error(fails.length + " check(s) failed"); }
  console.log("ALL CHECKS PASS — " + derived.length + " variant chains, 2 traces x " + STEPS.length + " steps rendered, compare view OK");
})();
`;
vm.runInContext(tests, sandbox, { filename: "tests.js" });
