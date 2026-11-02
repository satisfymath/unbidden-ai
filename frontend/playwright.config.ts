// Browser tests against the Python server serving the built assets, on its own port and state directory.
import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const state = mkdtempSync(join(tmpdir(), "unbidden-e2e-"));
export const TOKEN = "e2e-session-token";
const port = 8799;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: { baseURL: `http://127.0.0.1:${port}`, viewport: { width: 1500, height: 950 }, trace: "retain-on-failure" },
  webServer: {
    command: `npm run build && cd .. && UNBIDDEN_HOME=${state} UNBIDDEN_LANG=es uv run python -m unbidden.web --demo --record docs/bench/stage9-demo/DEMO-B-1 --port ${port} --no-tick --planner rule --state-dir ${state}/web --token ${TOKEN}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
    timeout: 180_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
