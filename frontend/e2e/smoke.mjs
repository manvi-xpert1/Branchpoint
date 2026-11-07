/**
 * End-to-end smoke test: drives the real app in Chromium through the MVP
 * acceptance workflow and saves screenshots.
 *
 *   # with the backend running (serving the built frontend) on :8000
 *   npm i -D playwright && npx playwright install chromium
 *   node e2e/smoke.mjs [baseUrl] [screenshotDir]
 *   (optional) set CHROME_PATH to use an existing Chrome instead of the download
 */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";

const BASE = process.argv[2] ?? "http://localhost:8000";
const SHOTS = process.argv[3] ?? "e2e/screenshots";
mkdirSync(SHOTS, { recursive: true });

// CHROME_PATH lets you use an existing Chrome/Chromium instead of the Playwright download.
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleErrors = [];
page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
page.on("pageerror", (e) => consoleErrors.push(String(e)));
page.on("dialog", (d) => d.accept());
// The web font comes from Google Fonts. Answer those requests locally so the
// test works offline; the app falls back to system fonts.
await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.fulfill({ status: 200, contentType: "text/css", body: "" }));

const step = (name) => console.log(`- ${name}`);
const shot = (name) => page.screenshot({ path: `${SHOTS}/${name}.png` });

try {
  step("landing: open the software example on its futures dashboard");
  await page.goto(BASE);
  await page.getByRole("heading", { name: /Explore alternative futures/ }).waitFor();
  await shot("0-landing");
  await page.getByTestId("example-software_infrastructure").click();
  await page.waitForURL(/\/futures/);
  await page.getByTestId("future-1").waitFor();
  // The DB-failure decisions are ranked with the default objectives (downtime x3, degraded x1, cost x1).
  assert.equal(await page.locator(".future").count(), 4);
  await page.locator(".card.recommendation", { hasText: "fast restore" }).waitFor();
  await shot("0b-futures");

  step("futures: weighting downtime more makes the replica the best future");
  await page.getByLabel("Weight of Downtime").fill("5");
  await page.locator(".card.recommendation", { hasText: "read replica" }).waitFor();
  await page.getByText(/is dominated by|are dominated by/).first().waitFor();
  // Sensitivity of the plain DB failure: Postgres's recovery time decides the downtime.
  await page.getByLabel("Future to analyse").selectOption({ label: "#4 DB fails, no intervention" });
  await page.getByRole("button", { name: "Analyse" }).click();
  await page.getByLabel("Sensitivity chart").waitFor();
  await page.locator("#sensitivity").getByText(/Baseline downtime/).waitFor();

  step("designer: open the e-commerce system");
  await page.getByRole("link", { name: "Design" }).click();
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
  await page.getByText("API Gateway depends on Order Queue").waitFor(); // dependency inspector opened
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

  step("monte carlo: run the flaky scenario 1000 times");
  await page.getByRole("link", { name: "Scenarios" }).click();
  await page.getByRole("link", { name: "Flaky week (probabilistic)" }).click();
  await page.getByRole("heading", { name: "Flaky week (probabilistic)" }).waitFor();
  await page.getByLabel("Number of runs").fill("1000");
  await page.getByRole("button", { name: "Run 1000 times" }).click();
  await page.getByText(/model estimates/).waitFor();
  await page.locator('[aria-label="Risk histogram"] .recharts-bar-rectangle').first().waitFor();
  // db_outage (p=0.3) -> 10, users_crash (p=0.2) -> 4: four possible outcomes.
  assert.equal(await page.locator('[aria-label="Risk histogram"] .recharts-bar-rectangle').count(), 4);
  const p95 = page.locator(".metric", { hasText: "Bad case (p95)" }).locator(".value");
  assert.match(await p95.innerText(), /^(10|14)$/);
  await page.getByRole("table", { name: "Risk drivers" }).getByText(/db_outage/).waitFor();
  await page.getByLabel("Risk histogram").scrollIntoViewIfNeeded();
  await shot("3c-monte-carlo");

  step("compare: run every scenario");
  await page.getByRole("link", { name: "Compare" }).first().click();
  await page.getByText("also run each").click();
  await page.getByRole("button", { name: /Run & compare/ }).click();
  await page.getByRole("table", { name: "Comparison" }).waitFor();
  const rows = page.getByRole("table", { name: "Comparison" }).locator("tbody tr");
  assert.equal(await rows.count(), 8);
  await page.getByRole("columnheader", { name: "Bad case" }).waitFor();
  await page.getByRole("button", { name: /Run & compare/ }).and(page.locator(":enabled")).waitFor({ timeout: 30000 });
  const noIntervention = rows.filter({ hasText: "DB fails, no intervention" });
  assert.match(await noIntervention.locator("td").nth(2).innerText(), /^10$/);
  await page.locator(".recharts-bar-rectangle path").first().waitFor();
  await page.waitForTimeout(1500); // let the chart animation finish
  await page.getByRole("heading", { name: "Downtime by scenario" }).scrollIntoViewIfNeeded();
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

  step("systems: list shows the system");
  await page.getByRole("link", { name: "All systems" }).click();
  await page.getByRole("heading", { name: "Your systems" }).waitFor();
  await page.getByText("5 parts").waitFor();
  await shot("6-projects");

  step("hospital: the surge decisions are simulated and ranked");
  await page.getByTestId("load-hospital").click();
  await page.waitForURL(/\/futures/);
  await page.getByTestId("future-1").waitFor();
  assert.equal(await page.locator(".future").count(), 6); // the surge and its 5 branches
  await page.locator(".card.recommendation", { hasText: "extra ED bays" }).waitFor();
  await page.getByLabel("Runs per future").selectOption("50");
  await page.getByRole("button", { name: /Simulate 300 runs/ }).click();
  await page.getByRole("table", { name: "Risk of every future" }).waitFor({ timeout: 60000 });
  await shot("7-hospital-futures");

  step("hospital: playback shows queues over time");
  await page.locator(".future").first().getByRole("button", { name: /Playback/ }).click();
  await page.waitForURL(/\/runs\//);
  await page.getByTestId("node-ed").waitFor();
  await page.getByRole("button", { name: "Charts over time" }).click();
  await page.getByLabel("Time series").selectOption("queue");
  await page.locator(".recharts-line").first().waitFor();
  await shot("8-hospital-charts");

  step("cold chain: a road closure reroutes stock and is explained");
  await page.getByRole("link", { name: "All systems" }).click();
  await page.getByTestId("load-cold_chain").click();
  await page.waitForURL(/\/futures/);
  await page.getByTestId("future-1").waitFor();
  await page.getByRole("link", { name: "Scenarios" }).click();
  await page.getByRole("link", { name: "Highway closed: warehouse to DC North (36 h)" }).click();
  await page.getByRole("button", { name: /Run simulation/ }).click();
  await page.waitForURL(/\/runs\//);
  await page.locator(".log-item", { hasText: "instead of" }).first().click();
  await page.getByText("Why did this happen?").waitFor();
  await page.locator(".chain-step", { hasText: "route closure begins" }).waitFor();
  await shot("9-coldchain-explain");

  assert.deepEqual(consoleErrors, [], "no browser console errors");
  console.log("\nE2E smoke test passed.");
} catch (e) {
  await shot("failure");
  console.error("\nE2E FAILED:", e.message, consoleErrors.length ? `\nConsole errors:\n${consoleErrors.join("\n")}` : "");
  process.exitCode = 1;
} finally {
  await browser.close();
}
