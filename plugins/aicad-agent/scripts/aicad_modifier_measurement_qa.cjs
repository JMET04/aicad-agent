#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { pathToFileURL } = require("url");

function loadPlaywright() {
  try { return require("playwright"); }
  catch (_) { return require(path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright")); }
}
function hash(file) { return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"); }

async function main() {
  const review = path.resolve(process.argv[2]);
  const reportPath = path.resolve(process.argv[3]);
  const screenshot = path.resolve(process.argv[4]);
  for (const file of [reportPath, screenshot]) fs.mkdirSync(path.dirname(file), { recursive: true });
  const { chromium } = loadPlaywright();
  const candidates = ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"];
  const executablePath = candidates.find(fs.existsSync);
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(pathToFileURL(review).href, { waitUntil: "load" });
  await page.waitForFunction(() => window.__aicadUi && window.__aicad3dSelector && window.__aicadSection);

  const clickEntity = async id => page.locator(`.view-hit[data-view-entity-id="${id}"]`).evaluate(element => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  const clearSelection = async () => page.evaluate(() => { for (const ref of [...window.__aicadUi.selectedRefs]) window.__aicadUi.toggleSelectionRef(ref); });
  const current = async () => page.evaluate(() => ({
    selected: window.__aicadUi.selectedRefs,
    kind: document.querySelector(".measurement-card")?.dataset.measurementKind || null,
    text: document.querySelector("#measurement")?.innerText || "",
    path: document.querySelector("#parameterPath")?.value || "",
    value: document.querySelector("#parameterValue")?.value || "",
  }));

  const initialCoordinates = await page.evaluate(() => ({
    toggle: document.querySelector("#coordinateToggle").checked,
    triads: document.querySelectorAll(".view-coordinate-triad").length,
    origins: document.querySelectorAll(".model-origin-marker").length,
    svgVisible: [...document.querySelectorAll(".view-coordinate-triad")].every(item => getComputedStyle(item).display !== "none"),
    canvasVisible: window.__aicad3dSelector.coordinateSystemVisible,
    system: pkg.coordinate_system,
  }));
  await page.locator(".coordinate-toggle").click();
  const coordinatesOff = await page.evaluate(() => ({
    checked: document.querySelector("#coordinateToggle").checked,
    bodyHidden: document.body.classList.contains("coordinates-hidden"),
    svgHidden: [...document.querySelectorAll(".view-coordinate-triad")].every(item => getComputedStyle(item).display === "none"),
    canvasHidden: !window.__aicad3dSelector.coordinateSystemVisible,
  }));
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => window.__aicadUi && window.__aicad3dSelector);
  const coordinatesOffPersisted = await page.evaluate(() => ({
    checked: document.querySelector("#coordinateToggle").checked,
    bodyHidden: document.body.classList.contains("coordinates-hidden"),
    svgHidden: [...document.querySelectorAll(".view-coordinate-triad")].every(item => getComputedStyle(item).display === "none"),
    canvasHidden: !window.__aicad3dSelector.coordinateSystemVisible,
  }));
  await page.locator(".coordinate-toggle").click();
  const coordinatesOn = await page.evaluate(() => ({
    checked: document.querySelector("#coordinateToggle").checked,
    bodyVisible: !document.body.classList.contains("coordinates-hidden"),
    svgVisible: [...document.querySelectorAll(".view-coordinate-triad")].every(item => getComputedStyle(item).display !== "none"),
    canvasVisible: window.__aicad3dSelector.coordinateSystemVisible,
  }));
  await page.reload({ waitUntil: "load" });
  await page.waitForFunction(() => window.__aicadUi && window.__aicad3dSelector);
  const coordinatesOnPersisted = await page.evaluate(() => ({
    checked: document.querySelector("#coordinateToggle").checked,
    bodyVisible: !document.body.classList.contains("coordinates-hidden"),
    svgVisible: [...document.querySelectorAll(".view-coordinate-triad")].every(item => getComputedStyle(item).display !== "none"),
    canvasVisible: window.__aicad3dSelector.coordinateSystemVisible,
  }));

  await clickEntity("TOP_F001_P_1");
  const line = await current();
  await page.locator(".measurement-card .metric-primary[data-editable]").click();
  const lineEdit = await current();
  await clearSelection();

  await clickEntity("TOP_F001_P_2");
  const secondLine = await current();
  await clearSelection();

  await clickEntity("TOP_F003_CENTER");
  const point = await current();
  await page.locator(".measurement-card .metric-primary[data-editable]").click();
  const pointEdit = await current();
  await clearSelection();

  await clickEntity("TOP_F003_C001");
  const circle = await current();
  await page.locator(".measurement-card .metric-primary[data-editable]").click();
  const circleEdit = await current();

  const layout = await page.evaluate(() => ({
    horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    measurementCards: document.querySelectorAll(".measurement-card").length,
    chinese: (document.body.innerText.match(/[\u3400-\u9fff]/g) || []).length,
  }));
  await page.screenshot({ path: screenshot, fullPage: true });
  await browser.close();

  const same = (actual, expected) => JSON.stringify(actual) === JSON.stringify(expected);
  const checks = {
    pageLoadedWithoutErrors: errors.length === 0,
    coordinateSystemIsRightHandedModelXYZ: initialCoordinates.system?.id === "MODEL_XYZ" && initialCoordinates.system?.handedness === "right" && same(initialCoordinates.system?.origin, [0, 0, 0]),
    coordinateSystemInitiallyVisible: initialCoordinates.toggle && initialCoordinates.triads === 6 && initialCoordinates.origins === 6 && initialCoordinates.svgVisible && initialCoordinates.canvasVisible,
    coordinateToggleHidesAllViews: !coordinatesOff.checked && coordinatesOff.bodyHidden && coordinatesOff.svgHidden && coordinatesOff.canvasHidden && !coordinatesOffPersisted.checked && coordinatesOffPersisted.bodyHidden && coordinatesOffPersisted.svgHidden && coordinatesOffPersisted.canvasHidden,
    coordinateToggleRestoresAllViews: coordinatesOn.checked && coordinatesOn.bodyVisible && coordinatesOn.svgVisible && coordinatesOn.canvasVisible && coordinatesOnPersisted.checked && coordinatesOnPersisted.bodyVisible && coordinatesOnPersisted.svgVisible && coordinatesOnPersisted.canvasVisible,
    lineClickShowsLengthAndEndpoints: line.kind === "line" && line.selected[0]?.measurement?.length_mm === 120 && same(line.selected[0]?.measurement?.start, [-60, -40, 0]) && same(line.selected[0]?.measurement?.end, [60, -40, 0]) && line.text.includes("长度") && line.text.includes("120"),
    lineSelectionPrefillsWidth: line.path === "profile.width" && line.value === "120",
    lineMeasurementPrefillsWidth: lineEdit.path === "profile.width" && lineEdit.value === "120",
    perpendicularEdgeUsesHeight: secondLine.selected[0]?.measurement?.length_mm === 80 && secondLine.selected[0]?.measurement?.controller_path === "profile.height",
    pointClickShowsXYZ: point.kind === "point" && same(point.selected[0]?.measurement?.coordinates, [0, 0, 12]) && point.text.includes("点坐标"),
    pointSelectionPrefillsCenter: point.path === "profile.center" && point.value.replace(/\s/g, "") === "0,0",
    pointMeasurementPrefillsCenter: pointEdit.path === "profile.center" && pointEdit.value.replace(/\s/g, "") === "0,0",
    circleClickShowsRadiusDiameterAndCenter: circle.kind === "circle" && circle.selected[0]?.measurement?.radius_mm === 15 && circle.selected[0]?.measurement?.diameter_mm === 30 && same(circle.selected[0]?.measurement?.center, [0, 0, 12]) && circle.text.includes("半径") && circle.text.includes("直径"),
    circleSelectionPrefillsRadius: circle.path === "profile.radius" && circle.value === "15",
    circleMeasurementPrefillsRadius: circleEdit.path === "profile.radius" && circleEdit.value === "15",
    measurementPanelSingleSelection: layout.measurementCards === 1,
    utf8AndNoHorizontalOverflow: layout.chinese > 100 && layout.horizontalOverflow === 0,
    screenshotWritten: fs.existsSync(screenshot) && fs.statSync(screenshot).size > 0,
  };
  const ok = Object.values(checks).every(Boolean);
  const report = {
    ok, status: ok ? "pass" : "failed", browser: executablePath || "playwright-managed-chromium",
    review, screenshot, checks,
    evidence: { initialCoordinates, coordinatesOff, coordinatesOffPersisted, coordinatesOn, coordinatesOnPersisted, line, lineEdit, secondLine, point, pointEdit, circle, circleEdit, layout },
    errors,
    hashes: { review: hash(review), screenshot: hash(screenshot) },
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");
  if (!ok) process.exitCode = 1;
}

main().catch(error => { console.error(error); process.exit(1); });
