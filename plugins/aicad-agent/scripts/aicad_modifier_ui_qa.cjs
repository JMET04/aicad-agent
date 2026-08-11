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
  const stagePath = reportPath + ".stage.txt";
  const stage = value => fs.writeFileSync(stagePath, value + "\n", "utf8");
  stage("arguments");
  for (const file of [reportPath, screenshot]) fs.mkdirSync(path.dirname(file), { recursive: true });
  const { chromium } = loadPlaywright();
  const candidates = ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"];
  const executablePath = candidates.find(fs.existsSync);
  stage("before-launch");
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  stage("launched");
  const page = await browser.newPage({ viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 1 });
  const errors = [];
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", e => errors.push(e.message));
  stage("before-goto");
  await page.goto(pathToFileURL(review).href, { waitUntil: "load" });
  stage("page-loaded");
  await page.waitForFunction(() => window.__aicadUi && window.__aicadSection && window.__aicadSection.hitCount > 0);

  stage("ui-ready");
  const pitch = page.locator('.view-hit[data-view-entity-id="TOP_F002_PITCH"]');
  const pitchVisible = pitch.locator('xpath=..').locator('.view-entity');
  const hiddenOpacity = await pitchVisible.evaluate(el => getComputedStyle(el).opacity);
  stage("pitch-hidden-checked");
  await pitch.scrollIntoViewIfNeeded();
  const pitchBox = await pitch.boundingBox();
  if (!pitchBox) throw new Error("pitch circle has no browser bounding box");
  await page.mouse.move(pitchBox.x + pitchBox.width - 2, pitchBox.y + pitchBox.height / 2);
  await page.waitForTimeout(80);
  const hoverOpacity = await pitchVisible.evaluate(el => getComputedStyle(el).opacity);
  await page.mouse.click(pitchBox.x + pitchBox.width - 2, pitchBox.y + pitchBox.height / 2);
  const pitchSelection = await page.evaluate(() => window.__aicadUi.selectedRefs.map(x => x.reference_key));

  stage("pitch-clicked");
  await page.locator('.parameter-row[data-feature="F003"][data-param="radius"]').click();
  const parameterBefore = await page.locator("#parameterValue").inputValue();
  await page.locator("#parameterValue").fill("16");
  await page.locator("#setParameter").click();
  const parameterOperation = await page.evaluate(() => window.__aicadUi.operations[0]);

  stage("parameter-edited");
  await page.locator('#sectionRequest').fill('看 X=10 截面');
  await page.locator('#makeSection').click();
  const axisSection = await page.evaluate(() => ({ plane: window.__aicadSection.plane, count: window.__aicadSection.hitCount, point: window.__aicadSection.firstHitPoint() }));
  const sectionBox = await page.locator('#freeSectionCanvas').boundingBox();
  if (sectionBox && axisSection.point) {
    await page.mouse.move(sectionBox.x + axisSection.point.x, sectionBox.y + axisSection.point.y);
    await page.mouse.click(sectionBox.x + axisSection.point.x, sectionBox.y + axisSection.point.y);
  }
  stage("axis-section-clicked");
  const sectionSelection = await page.evaluate(() => window.__aicadUi.selectedRefs.map(x => x.reference_key));

  stage("axis-section-selected");
  await page.locator('#sectionRequest').fill('法向 1,1,0 过原点');
  await page.locator('#makeSection').click();
  const oblique = await page.evaluate(() => ({ plane: window.__aicadSection.plane, count: window.__aicadSection.hitCount }));

  stage("oblique-section");
  await page.evaluate(() => { for (const ref of [...window.__aicadUi.selectedRefs]) window.__aicadUi.toggleSelectionRef(ref); });
  await page.locator('.view-hit[data-view-entity-id="TOP_F003_CENTER"]').evaluate(el => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  await page.locator('.view-hit[data-view-entity-id="TOP_F004_CENTER"]').evaluate(el => el.dispatchEvent(new MouseEvent("click", { bubbles: true })));
  const pointRelationVisible = await page.locator('[data-relation="coincident"]').count();
  if (pointRelationVisible) await page.locator('[data-relation="coincident"]').click();

  stage("point-relation");
  await page.locator('#aiInstruction').fill('中心孔保持同心，其他核心尺寸不变');
  await page.locator('#addInstruction').click();
  const state = await page.evaluate(() => ({
    selected: window.__aicadUi.selectedRefs.map(x => x.reference_key),
    operations: window.__aicadUi.operations,
    instructions: window.__aicadUi.instructions,
    handoff: window.__aicadUi.handoff(),
    body: document.body.innerText,
    advancedOpen: document.querySelector('details.advanced').open,
    coreGroups: document.querySelectorAll('.parameter-group').length,
    parameterRows: document.querySelectorAll('.parameter-row').length,
    horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
    chinese: (document.body.innerText.match(/[\u3400-\u9fff]/g) || []).length,
    mojibake: /[\ufffd\u951f\u704f\u95ab\u7470\u93b4\u942e\u7eeb]/.test(document.documentElement.innerHTML),
  }));
  stage("before-screenshot");
  await page.screenshot({ path: screenshot, fullPage: true });
  stage("screenshot-done");
  await browser.close();
  stage("browser-closed");

  const close = (a,b) => Math.abs(a-b) < 1e-6;
  const checks = {
    pageLoadedWithoutErrors: errors.length === 0,
    hiddenKeyGeometryDefault: hiddenOpacity === "0",
    hiddenKeyGeometryOnHover: hoverOpacity === "1",
    pitchCircleSelectable: JSON.stringify(pitchSelection) === JSON.stringify(["F002|profile.pattern.pitch_circle"]),
    coreParametersVisible: state.coreGroups === 4 && state.parameterRows === 16,
    numericClickPrefillsEditor: parameterBefore === "15",
    numericEditCreatesExactOperation: parameterOperation && parameterOperation.op === "set_subobject_parameter" && parameterOperation.path === "profile.radius" && parameterOperation.value === 16,
    axisSectionGenerated: axisSection.count > 0 && close(axisSection.plane.n[0],1) && close(axisSection.plane.p[0],10),
    sectionGeometrySelectable: sectionSelection.some(x => /^F00[1-4]\|/.test(x)),
    obliqueSectionGenerated: oblique.count > 0 && close(oblique.plane.n[0],Math.SQRT1_2) && close(oblique.plane.n[1],Math.SQRT1_2),
    pointRelationOfferedAndRecorded: pointRelationVisible === 1 && state.operations.some(x => x.op === "add_subobject_relation" && x.relation === "coincident"),
    unifiedNaturalLanguageList: state.instructions.length === 1 && state.body.includes('修改清单') && !state.body.includes('纠错意图') && !state.body.includes('正式事务'),
    advancedDetailsCollapsed: state.advancedOpen === false,
    formalSafetyLocks: state.handoff.exact_transaction.review_policy.reviewOnly === true && state.handoff.exact_transaction.review_policy.accepted === false && state.handoff.exact_transaction.review_policy.ruleEnabled === false,
    utf8AndNoMojibake: state.chinese > 80 && !state.mojibake,
    noHorizontalOverflow: state.horizontalOverflow === 0,
    screenshotWritten: fs.existsSync(screenshot) && fs.statSync(screenshot).size > 30000,
  };
  const ok = Object.values(checks).every(Boolean);
  const report = { ok, status: ok ? "pass" : "failed", browser: executablePath || "playwright-managed-chromium", review, screenshot, checks, evidence: { hiddenOpacity, hoverOpacity, pitchSelection, parameterBefore, parameterOperation, axisSection, sectionSelection, oblique, pointRelationVisible, state: { selected: state.selected, operations: state.operations, instructions: state.instructions, coreGroups: state.coreGroups, parameterRows: state.parameterRows, horizontalOverflow: state.horizontalOverflow, chinese: state.chinese } }, errors, hashes: { review: hash(review), screenshot: hash(screenshot) } };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");
  if (!ok) process.exitCode = 2;
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 2; });
