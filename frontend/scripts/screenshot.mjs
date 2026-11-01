// A screenshot of the dashboard for the walk's evidence: cd frontend && node scripts/screenshot.mjs <url-with-token> <out.png>
// Uses the Playwright that the frontend's dev dependencies install (cd frontend && npm ci).
import { chromium } from "@playwright/test";
const [url, out] = process.argv.slice(2);
if (!url || !out) { console.error("usage: cd frontend && node scripts/screenshot.mjs <url> <out.png>"); process.exit(2); }
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
await page.goto(url, { waitUntil: "domcontentloaded" }); // not networkidle: a live dashboard keeps an event stream open
await page.waitForTimeout(5000);
await page.screenshot({ path: out, fullPage: false });
await browser.close();
console.log(`screenshot ${out}`);
