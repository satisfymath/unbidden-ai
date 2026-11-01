// Campaign 12: the dashboard checked with a browser (Playwright, Chromium from the frontend's dev dependencies).
//
//   cd frontend && HOME=/Users/<real> node scripts/c12_ui_check.mjs <url-with-token> <out-dir> [--reload]
//
// It opens the dashboard, waits for the first paint of data, records what the person would see (connection state,
// the workspace's name and mode, the counts the top bar shows, the chat panel), takes screenshots, reloads to check
// persistence, and writes ui.json with what was observed and any console error. It never types a secret; the session
// token travels only in the URL the harness passes (scrubbed from every record).
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, out] = process.argv.slice(2);
if (!url || !out) { console.error("usage: node ui_check.mjs <url> <out-dir>"); process.exit(2); }
mkdirSync(out, { recursive: true });
const result = { url: url.replace(/\?s=.*/, "?s=<token>"), console_errors: [], steps: [] };
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
page.on("console", (m) => { if (m.type() === "error") result.console_errors.push(m.text().slice(0, 300)); });
page.on("pageerror", (e) => result.console_errors.push(`pageerror: ${String(e).slice(0, 300)}`));
const step = (name, data) => { result.steps.push({ name, ...data }); };
try {
  await page.goto(url, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(6000);
  const text = await page.evaluate(() => document.body.innerText);
  step("loaded", {
    has_root: await page.locator("#root").count() > 0,
    topbar: text.split("\n").slice(0, 12),
    mentions_live: /Vivo|live/i.test(text),
    mentions_demo: /demo/i.test(text),
    widgets_line: (text.match(/\d+ widgets?[^\n]*/) || [""])[0],
  });
  await page.screenshot({ path: join(out, "01-space.png") });
  // the activity view
  const activity = page.getByText(/^(Actividad|Activity)$/).first();
  if (await activity.count()) {
    await activity.click();
    await page.waitForTimeout(2500);
    const t2 = await page.evaluate(() => document.body.innerText);
    step("activity", { lines: t2.split("\n").slice(0, 40) });
    await page.screenshot({ path: join(out, "02-activity.png") });
  }
  const experiments = page.getByText(/^(Experimentos|Experiments)$/).first();
  if (await experiments.count()) {
    await experiments.click();
    await page.waitForTimeout(2500);
    const t3 = await page.evaluate(() => document.body.innerText);
    step("experiments", { lines: t3.split("\n").slice(0, 30) });
    await page.screenshot({ path: join(out, "03-experiments.png") });
  }
  const space = page.getByText(/^(Espacio|Space)$/).first();
  if (await space.count()) { await space.click(); await page.waitForTimeout(1500); }
  // reload: the layout and the conversation must come back without a model call
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForTimeout(5000);
  const t4 = await page.evaluate(() => document.body.innerText);
  step("reloaded", { widgets_line: (t4.match(/\d+ widgets?[^\n]*/) || [""])[0], mentions_live: /Vivo|live/i.test(t4) });
  await page.screenshot({ path: join(out, "04-reloaded.png") });
  // no secret-looking string on the page
  step("secrets", { suspicious: (t4.match(/(sk-[A-Za-z0-9]{10,}|github_pat_[A-Za-z0-9_]{10,}|ghp_[A-Za-z0-9]{10,})/g) || []).length });
  result.ok = true;
} catch (e) {
  result.ok = false; result.error = String(e).slice(0, 500);
  try { await page.screenshot({ path: join(out, "99-error.png") }); } catch {}
} finally {
  await browser.close();
  writeFileSync(join(out, "ui.json"), JSON.stringify(result, null, 1));
  console.log(JSON.stringify({ ok: result.ok, steps: result.steps.length, console_errors: result.console_errors.length }));
}
