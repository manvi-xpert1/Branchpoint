/**
 * End-to-end smoke test: drives the real app in Chromium through the MVP
 * acceptance workflow and saves screenshots.
 *
 *   # with the backend running (serving the built frontend) on :8000
 *   npm i -D playwright && npx playwright install chromium
 *   node e2e/smoke.mjs [baseUrl] [screenshotDir]
 */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:8000";
const SHOTS = process.argv[3] ?? "e2e/screenshots";
mkdirSync(SHOTS, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
page.on("pageerror", (e) => consoleErrors.push(String(e)));
page.on("dialog", (d) => d.accept());

const step = (name) => console.log(`- ${name}`);
const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png` });

try {
  step("projects: load the example");
  await page.goto(BASE);
  await page.getByRole("button", { name: "Load example" }).first().click();
  await page.waitForURL(/\/design$/);
  await page.getByTestId("node-postgres").waitFor();
  assert.equal(await page.locator(".react-flow__node").count(), 4);
  assert.equal(await page.locator(".react-flow__edge").count(), 3);
  await page.getByText("No problems found.").waitFor();
  await shot("1-designer");

  step("designer: add a queue and connect the gateway to it");
  await page.getByTitle("Add Queue").click();
  await page.getByTestId("node-queue").waitFor();
  await page.getByLabel("Component name").fill("Order Queue");
  const handle = page.locator('.react-flow__node[data-id="api_gateway"] .react-flow__handle.source');
  await handle.dragTo(page.locator('.react-flow__node[data-id="queue"]'));
  await page.locator('.react-flow__edge[data-id="api_gateway->queue"]').waitFor();
  await page.getByText("depends on").waitFor(); // dependency inspector opened
  await page.getByLabel("Dependency type").selectOption("optional");

  step("designer: blast radius when selecting the database");
  await page.getByTestId("node-postgres").click();
  await page.getByText(/If this fails, up to 2 components/).waitFor();
  await shot("2-designer-edit");

  step("designer: save and reload persists the change");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.getByRole("button", { name: "Saved" }).waitFor();
  await page.reload();
  await page.getByTestId("node-queue").waitFor();
  assert.equal(await page.locator(".react-flow__edge").count(), 4);

  step("designer: JSON mode round trip");
  await page.getByRole("button", { name: "JSON", exact: true }).click();
  const json = JSON.parse(await page.getByLabel("System JSON").inputValue());
  assert.equal(json.components.length, 5);
  await page.getByRole("button", { name: "Cancel" }).click();

  step("scenarios: branch 'DB fails' and add a replica via preset");
  await page.getByRole("link", { name: "Scenarios" }).click();
  await page.getByRole("link", { name: "DB fails, no intervention" }).click();
  await page.getByRole("heading", { name: "DB fails, no intervention" }).waitFor();
  await page.getByRole("button", { name: "Branch", exact: true }).click();
  await page.getByRole("heading", { name: "DB fails, no intervention: alternative" }).waitFor();
  await page.getByText(/inherited/).first().waitFor();
  await page.getByLabel("Replica of").selectOption("postgres");
  await page.getByLabel("Replica of").locator("..").getByRole("button", { name: "Add" }).click();
  await page.getByTestId(/intervention-add_postgres_replica/).waitFor();
  await page.getByLabel("Scenario name").fill("DB fails + replica (built in UI)");
  await shot("3-scenario-builder");

  step("scenarios: save & run");
  await page.getByRole("button", { name: /Save & run/ }).click();
  await page.waitForURL(/\/runs\//);
  await page.getByTestId("node-postgres_replica").waitFor();
  assert.equal(await page.getByTestId("node-postgres").getAttribute("data-status"), "failed");
  assert.equal(await page.getByTestId("node-api_gateway").getAttribute("data-status"), "healthy");
  await page.waitForTimeout(500);
  await shot("3b-replica-run");

  step("compare: run every scenario");
  await page.getByRole("link", { name: "Compare" }).first().click();
  await page.getByRole("button", { name: /Run & compare/ }).click();
  await page.getByRole("table", { name: "Comparison" }).waitFor();
  const rows = page.getByRole("table", { name: "Comparison" }).locator("tbody tr");
  assert.equal(await rows.count(), 7);
  const noIntervention = rows.filter({ hasText: "DB fails, no intervention" });
  assert.match(await noIntervention.locator("td").nth(2).innerText(), /^10$/);
  await page.locator(".recharts-bar-rectangle path").first().waitFor();
  await page.waitForTimeout(1500); // let the chart animation finish
  await page.getByRole("heading", { name: "Time unavailable vs degraded" }).scrollIntoViewIfNeeded();
  await shot("4-compare");

  step("playback: gateway failure explained back to the root event");
  await noIntervention.getByRole("link", { name: "Playback" }).click();
  await page.waitForURL(/\/runs\//);
  await page.getByTestId("node-api_gateway").waitFor();
  assert.equal(await page.getByTestId("node-api_gateway").getAttribute("data-status"), "failed");
  await page.locator(".log-item", { hasText: "api_gateway" }).filter({ hasText: "failed" }).first().click();
  await page.getByText("Why did this happen?").waitFor();
  assert.equal(await page.locator(".chain-step").count(), 4);
  await shot("5-playback-explain");

  step("playback: scrub, step and play");
  await page.getByLabel("Simulation time").fill("2");
  assert.equal(await page.getByTestId("node-postgres").getAttribute("data-status"), "healthy");
  await page.getByTitle("Next event").click();
  assert.equal(await page.getByTestId("node-postgres").getAttribute("data-status"), "failed");
  await page.getByRole("button", { name: /Play/ }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: /Pause/ }).click();
  const t = await page.getByLabel("Simulation time").inputValue();
  assert.ok(Number(t) > 5, `time advanced while playing (t=${t})`);

  step("playback: verify replay");
  await page.getByRole("button", { name: "Verify replay" }).click();
  await page.getByText(/Replay identical/).waitFor();

  step("projects: list shows the system");
  await page.getByRole("link", { name: "Branchpoint" }).click();
  await page.getByText("5 components").waitFor();
  await shot("6-projects");

  assert.deepEqual(consoleErrors, [], "no browser console errors");
  console.log("\nE2E smoke test passed.");
} catch (e) {
  await shot("failure");
  console.error("\nE2E FAILED:", e.message, consoleErrors.length ? `\nConsole errors:\n${consoleErrors.join("\n")}` : "");
  process.exitCode = 1;
} finally {
  await browser.close();
}
