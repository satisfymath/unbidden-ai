// A screenshot of the dashboard for the walk's evidence: node demo/screenshot.mjs <url-with-token> <out.png>
// Uses the Playwright that the frontend's dev dependencies install (cd frontend && npm ci).
import { chromium } from "@playwright/test";
const [url, out] = process.argv.slice(2);
if (!url || !out) { console.error("usage: node demo/screenshot.mjs <url> <out.png>"); process.exit(2); }
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1500, height: 950 } });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(2500);
await page.screenshot({ path: out, fullPage: false });
await browser.close();
console.log(`screenshot ${out}`);
