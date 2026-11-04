// The whole story: open the project, understand what happens, select an experiment, ask for a chart by chat, see it
// on the canvas, open its evidence, reload and keep the space. Plus the canvas mechanics and the honest states.
import { expect, test, type Page } from "@playwright/test";
import { TOKEN } from "../../playwright.config";

async function open(page: Page, ws = "demo:storefront-web") {
  await page.goto(`/?s=${TOKEN}`);
  await page.evaluate((id) => localStorage.setItem("unbidden.ws", id), ws);
  await page.goto(`/?s=${TOKEN}`);
  await expect(page.locator(".widget").first()).toBeVisible({ timeout: 20_000 });
  await page.waitForTimeout(800);
  await page.locator('button[aria-label="encuadrar todo"]').click(); // cards outside the viewport are not rendered
  await page.waitForTimeout(700);
}

/** How many cards the canvas holds, rendered or not (only visible nodes are mounted). */
async function cardCount(page: Page): Promise<number> {
  const text = await page.locator(".saved-pill").textContent();
  return Number(/(\d+) widgets/.exec(text ?? "")?.[1] ?? "0");
}

test("the page refuses to work without the session token and says so", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Abre la URL que imprimió el servidor")).toBeVisible();
  await expect(page.locator(".widget")).toHaveCount(0);
});

test("open → understand → select → ask a chart → see it → evidence → reload keeps the space", async ({ page }) => {
  await open(page);
  await expect(page.locator(".topbar").getByText("UNBiDDEN")).toBeVisible();
  await expect(page.getByText("Demostración · datos ficticios")).toBeVisible();
  await expect(page.locator(".widget", { hasText: "Unbidden ahora" })).toBeVisible();
  const before = await cardCount(page);
  expect(before).toBeGreaterThan(6);

  await page.locator(".widget-head", { hasText: "Hallazgo validado" }).click();
  await page.keyboard.press("Meta+K");
  await expect(page.getByRole("dialog", { name: "conversación con Unbidden" })).toBeVisible();
  await expect(page.locator(".context-chips")).toContainText("Hallazgo validado");
  await page.locator(".dock input").fill("Muéstrame la latencia antes y después de este experimento");
  await page.keyboard.press("Enter");
  await expect(page.locator(".tool-line").first()).toContainText("create_widget", { timeout: 20_000 });
  await expect(page.locator(".msg.assistant").last()).toContainText("añadido");
  await page.keyboard.press("Escape");
  await expect(page.locator(".saved-pill")).toContainText(`${before + 1} widgets`);
  const chart = page.locator(".widget", { hasText: "Latencia antes y después" }).last();
  await expect(chart.locator(".recharts-bar")).toHaveCount(2, { timeout: 10_000 });
  await expect(chart.locator(".prov")).toContainText("demostración");

  await chart.locator('button[aria-label="menú de la tarjeta"]').click();
  await page.locator(".menu button", { hasText: "Inspeccionar" }).click();
  const inspector = page.locator("aside.inspector");
  await expect(inspector).toBeVisible();
  await expect(inspector).toContainText("experiment.samples");
  await expect(inspector).toContainText("opportunity: opp_demo000000000001");
  await expect(inspector).toContainText("Veredicto registrado");

  await page.reload();
  await expect(page.locator(".saved-pill")).toContainText(`${before + 1} widgets`, { timeout: 20_000 });
  await expect(page.locator(".widget", { hasText: "Latencia antes y después" }).last()).toBeVisible();
});

test("chat modifies, compares honestly and undoes; missing data is stated, not filled in", async ({ page }) => {
  await open(page);
  const count = await cardCount(page);
  await page.keyboard.press("Meta+K");
  await page.locator(".dock input").fill("Grafica el gasto por corrida");
  await page.keyboard.press("Enter");
  await expect(page.locator(".msg.assistant").last()).toContainText("Gasto por run", { timeout: 20_000 });
  await page.locator(".dock input").fill("Cambia ese gráfico a barras");
  await page.keyboard.press("Enter");
  await expect(page.locator(".msg.assistant").last()).toContainText("actualizado vista", { timeout: 20_000 });
  await page.locator(".dock input").fill("Compara estas dos ejecuciones");
  await page.keyboard.press("Enter");
  await expect(page.locator(".msg.assistant").last()).toContainText("dos ejecuciones", { timeout: 20_000 });
  await page.locator(".dock input").fill("Deshaz la última tarjeta");
  await page.keyboard.press("Enter");
  await expect(page.locator(".msg.assistant").last()).toContainText("deshecho", { timeout: 20_000 });
  await page.keyboard.press("Escape");
  await expect(page.locator(".saved-pill")).toContainText(`${count + 1} widgets`);
  await page.locator('button[aria-label="encuadrar todo"]').click();
  await expect(page.locator(".widget", { hasText: "Gasto por run" })).toHaveCount(1);
});

test("drag, resize, zoom, multi-select, remove with undo, and scroll inside a table", async ({ page }) => {
  await open(page);
  const card = page.locator(".react-flow__node", { hasText: "Checks del proyecto" });
  const box = (await card.boundingBox())!;
  const head = card.locator(".widget-head");
  const hb = (await head.boundingBox())!;
  await page.mouse.move(hb.x + 120, hb.y + hb.height / 2);
  await page.mouse.down();
  await page.mouse.move(hb.x + 220, hb.y + 160, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(900);
  const moved = (await card.boundingBox())!;
  expect(Math.abs(moved.x - box.x)).toBeGreaterThan(50);
  await expect(page.locator(".saved-pill")).toContainText("Guardado", { timeout: 5000 });

  await page.locator('button[aria-label="acercar"]').click();
  await expect(page.locator(".zoom-pill span")).not.toHaveText("100%");
  await page.locator('button[aria-label="encuadrar todo"]').click();

  await page.locator(".widget-head", { hasText: "Checks del proyecto" }).click();
  await page.keyboard.press("Delete");
  await expect(page.locator(".widget", { hasText: "Checks del proyecto" })).toHaveCount(0);
  await expect(page.locator(".toast")).toContainText("nada del motor cambió");
  await page.locator(".toast button", { hasText: "Deshacer" }).click();
  await expect(page.locator(".widget", { hasText: "Checks del proyecto" })).toHaveCount(1);

  // Scrolling inside a scrollable card must not pan the canvas.
  await page.locator('button[aria-label="añadir tarjeta"]').click();
  await page.locator(".add-item", { hasText: "Tabla" }).click();
  const table = page.locator(".table-wrap").last();
  await expect(table).toBeVisible();
  await page.waitForTimeout(1200); // the new card is focused with an animation; let the viewport settle first
  const vp = await page.evaluate(() => (document.querySelector(".react-flow__viewport") as HTMLElement).style.transform);
  const tb = (await table.boundingBox())!;
  await page.mouse.move(tb.x + 50, tb.y + 50);
  await page.mouse.wheel(0, 120);
  await page.waitForTimeout(300);
  expect(await page.evaluate(() => (document.querySelector(".react-flow__viewport") as HTMLElement).style.transform)).toBe(vp);
});

test("a widget specification the server rejects never reaches the canvas", async ({ page, request }) => {
  await open(page);
  const r = await request.put(`/api/ws/${encodeURIComponent("demo:storefront-web")}/presentation`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    data: { base_version: 0, widgets: [{ type: "iframe", title: "x" }] },
  });
  expect(r.status()).toBe(422);
  const cross = await request.get(`/api/ws/${encodeURIComponent("demo:storefront-web")}/summary`, { headers: { Authorization: `Bearer ${TOKEN}`, Origin: "http://evil.example" } });
  expect(cross.status()).toBe(403);
});

test("a historical record is shown as closed, with its cycles, and never as current", async ({ page }) => {
  await open(page, "record:DEMO-B-1");
  await expect(page.getByText("Histórico · corrida cerrada")).toBeVisible();
  await expect(page.locator(".widget", { hasText: "Unbidden ahora" })).toContainText("Corrida cerrada");
  await expect(page.locator(".widget", { hasText: "Ciclos de la corrida" })).toContainText("cycle 1");
  await expect(page.locator(".widget", { hasText: "Hallazgo validado" })).toContainText("commentaries.article_id");
  await expect(page.locator(".widget", { hasText: "Capturas" })).toHaveCount(0);
  await page.locator('button[role="tab"]', { hasText: "Actividad" }).click();
  await expect(page.locator(".pane").first()).toContainText("cerrado");
});

test("keyboard: tabs, chat, fit and the list view on a narrow screen", async ({ page }) => {
  await open(page);
  await page.keyboard.press("2");
  await expect(page.locator(".pane").first()).toContainText("Experimentos y hallazgos");
  await page.keyboard.press("1");
  await page.keyboard.press("f");
  await page.setViewportSize({ width: 420, height: 800 });
  await page.reload();
  await expect(page.locator(".mobile .card").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".react-flow")).toHaveCount(0);
});
