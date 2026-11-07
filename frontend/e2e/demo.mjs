/**
 * Records a silent walkthrough of Branchpoint (about 1.5 minutes) and saves
 * README screenshots. Run against a fresh backend serving the built frontend:
 *
 *     node e2e/demo.mjs http://localhost:8000 ../docs/demo ../docs/screenshots
 *
 * Writes <video dir>/*.webm (convert with ffmpeg) and the screenshots.
 */
import { chromium } from "playwright";

const [BASE = "http://localhost:8000", VIDEO = "../docs/demo", SHOTS = "../docs/screenshots"] = process.argv.slice(2);
const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || undefined });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: VIDEO, size: { width: 1440, height: 900 } } });
const page = await context.newPage();
await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.fulfill({ status: 200, contentType: "text/css", body: "" }));
const pause = (ms) => page.waitForTimeout(ms);
const glide = async (locator) => { await locator.scrollIntoViewIfNeeded(); await pause(1200); };

// 1. Landing page
await page.goto(BASE);
await pause(2500);
await page.screenshot({ path: `${SHOTS}/landing.png` });
await page.mouse.wheel(0, 700); await pause(1800);
await page.mouse.wheel(0, 700); await pause(1500);
await page.mouse.wheel(0, -1400); await pause(800);

// 2. Hospital example: futures dashboard
await page.getByTestId("example-hospital").click();
await page.getByTestId("future-1").waitFor({ timeout: 30000 });
await pause(3000);
await page.screenshot({ path: `${SHOTS}/futures.png` });
// care more about boarding: the ranking updates
await page.getByLabel("Weight of Boarding time").fill("4");
await pause(3000);
await page.getByLabel("Weight of Boarding time").fill("1");
await pause(2000);
await glide(page.getByRole("heading", { name: "Trade-offs" }));
await pause(2500);
await page.locator("#sensitivity").getByRole("button", { name: "Analyse" }).click();
await page.getByLabel("Sensitivity chart").waitFor({ timeout: 30000 });
await glide(page.locator("#sensitivity"));
await pause(3000);

// 3. Playback with queues over time
await page.locator(".future").first().getByRole("button", { name: /Playback/ }).click();
await page.waitForURL(/\/runs\//);
await pause(2000);
await page.getByRole("button", { name: /Play/ }).click();
await pause(4000);
await page.getByRole("button", { name: "Charts over time" }).click();
await page.getByLabel("Time series").selectOption("queue");
await pause(3000);

// 4. Design view of the hospital
await page.getByRole("link", { name: "Design" }).click();
await pause(2500);
await page.getByTestId("node-ed").click();
await pause(2500);
await page.screenshot({ path: `${SHOTS}/designer.png` });

// 5. Cold chain: a road closure explained back to its cause
await page.getByRole("link", { name: "All systems" }).click();
await page.getByTestId("load-cold_chain").click();
await page.getByTestId("future-1").waitFor({ timeout: 30000 });
await pause(2500);
await page.getByRole("link", { name: "Scenarios" }).click();
await page.getByRole("link", { name: "Highway closed: warehouse to DC North (36 h)" }).click();
await pause(1500);
await page.getByRole("button", { name: /Run simulation/ }).click();
await page.waitForURL(/\/runs\//);
await pause(1500);
await page.locator(".log-item", { hasText: "instead of" }).first().click();
await page.getByText("Why did this happen?").waitFor();
await pause(3000);
await page.screenshot({ path: `${SHOTS}/playback.png` });

// 6. Software infrastructure: Monte Carlo on the flaky week
await page.getByRole("link", { name: "All systems" }).click();
await page.getByTestId("load-software_infrastructure").click();
await page.getByTestId("future-1").waitFor({ timeout: 30000 });
await pause(2500);
await page.getByRole("link", { name: "Scenarios" }).click();
await page.getByRole("link", { name: "Flaky week (probabilistic)" }).click();
await page.getByRole("button", { name: /Run 1000 times/ }).click();
await page.getByText(/model estimates/).waitFor({ timeout: 30000 });
await glide(page.getByLabel("Risk histogram"));
await pause(3500);
await page.screenshot({ path: `${SHOTS}/monte-carlo.png` });

await context.close();
await browser.close();
console.log("demo recorded");
