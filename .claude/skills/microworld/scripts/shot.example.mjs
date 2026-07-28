// Worked example: screenshot pass for docs/microworlds/automl-openevolve-seeding.html.
// Requires: npm install playwright-core; uses the pre-installed Chromium.
import { chromium } from "playwright-core";

const url = "file:///home/user/TRIDENT-Val/docs/microworlds/automl-openevolve-seeding.html";
const out = "/tmp/claude-0/-home-user-TRIDENT-Val/04f86a28-9f92-5f38-84a9-a17862a4649c/scratchpad";

const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium" });

async function shots(scheme, tag) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, colorScheme: scheme });
  const page = await ctx.newPage();
  page.on("console", m => { if (m.type() === "error") console.log("CONSOLE ERROR:", m.text()); });
  page.on("pageerror", e => console.log("PAGE ERROR:", e.message));
  await page.goto(url);
  await page.screenshot({ path: `${out}/1-briefing-${tag}.png` });
  await page.click("#brief-close");
  await page.screenshot({ path: `${out}/2-mission-${tag}.png` });
  await page.evaluate(() => go(8));   // mid-AutoML
  await page.screenshot({ path: `${out}/3-automl-${tag}.png` });
  await page.evaluate(() => go(15));  // seed decision
  await page.screenshot({ path: `${out}/4-seed-${tag}.png` });
  await page.evaluate(() => go(20));  // gen 5 (simple seed: KNN corrected)
  await page.screenshot({ path: `${out}/5-gen5-${tag}.png`, fullPage: true });
  await page.evaluate(() => go(19));  // gen 4 — the failure
  await page.screenshot({ path: `${out}/6-fail-${tag}.png`, fullPage: true });
  await page.evaluate(() => go(31));  // verdict
  await page.screenshot({ path: `${out}/7-final-${tag}.png`, fullPage: true });
  await page.evaluate(() => openCompare());
  await page.screenshot({ path: `${out}/8-compare-${tag}.png`, fullPage: true });
  await ctx.close();
}

await shots("light", "light");
await shots("dark", "dark");
await browser.close();
console.log("done");
