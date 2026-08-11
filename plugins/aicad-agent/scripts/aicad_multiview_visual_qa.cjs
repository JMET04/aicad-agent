#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (_error) {
    return require(path.join(
      os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime",
      "dependencies", "node", "node_modules", "playwright"
    ));
  }
}

function sha256(filePath) {
  return require("crypto").createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

async function clickHit(page, id) {
  const selector = `.view-hit[data-view-entity-id="${id}"]`;
  await page.locator(selector).first().evaluate((element) => element.dispatchEvent(new MouseEvent("click", { bubbles: true })));
}

async function main() {
  const reviewPath = path.resolve(process.argv[2] || "");
  const reportPath = path.resolve(process.argv[3] || "multiview.visual.json");
  const screenshotPath = path.resolve(process.argv[4] || "multiview.png");
  const correctionPath = path.resolve(process.argv[5] || "multiview.correction.json");
  if (!fs.existsSync(reviewPath)) throw new Error(`review not found: ${reviewPath}`);
  for (const filePath of [reportPath, screenshotPath, correctionPath]) fs.mkdirSync(path.dirname(filePath), { recursive: true });

  const { chromium } = loadPlaywright();
  const browserCandidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  ];
  const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 });
  const consoleErrors = [];
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  await page.goto(pathToFileURL(reviewPath).href, { waitUntil: "load" });

  await clickHit(page, "FRONT_F001_B_1");
  await page.locator("#moveAxis").selectOption("y");
  await page.locator("#moveValue").fill("-1");
  await page.locator("#addMove").click();
  await clickHit(page, "FRONT_F001_B_1");

  await clickHit(page, "TOP_F003_C001");
  await clickHit(page, "TOP_F004_C001");
  await page.locator('[data-relation="concentric"]').click();
  await clickHit(page, "TOP_F003_C001");
  await clickHit(page, "TOP_F004_C001");
  await clickHit(page, "TOP_F001_P_1");
  await page.locator("#moveAxis").selectOption("y");
  await page.locator("#valueMode").selectOption("absolute");
  await page.locator("#preserve").selectOption("keep_center");
  await page.locator("#moveValue").fill("-45");
  await page.locator("#addMove").click();

  const correction = await page.evaluate(() => formalCorrection());
  fs.writeFileSync(correctionPath, JSON.stringify(correction, null, 2) + "\n", "utf8");
  await page.screenshot({ path: screenshotPath, fullPage: true });
  const dom = await page.evaluate(() => {
    const bodyText = document.body.innerText;
    return {
      charset: document.characterSet,
      lang: document.documentElement.lang,
      visibleChineseCharacters: (bodyText.match(/[\u3400-\u9fff]/g) || []).length,
      suspiciousMojibake: /[\ufffd\u951f\u704f\u95ab\u7470\u93b4\u942e\u7eeb]/.test(document.documentElement.innerHTML),
      horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      exactSelectedReferenceKeys: window.aicadReviewState.selectedRefs.map((row) => row.reference_key),
      operationTypes: window.aicadReviewState.operations.map((row) => row.op),
      noteStatuses: window.aicadReviewState.notes.map((row) => row.status),
      relationButtonCount: document.querySelectorAll("[data-relation]").length,
      canvasSize: [document.querySelector("#aicad3d-selector").width, document.querySelector("#aicad3d-selector").height],
      draftContainsSourceHash: document.querySelector("#draft").textContent.includes(pkg.source_sha256),
    };
  });
  await browser.close();

  const checks = {
    utf8: dom.charset.toUpperCase() === "UTF-8",
    zhLanguage: dom.lang === "zh-CN",
    chineseVisible: dom.visibleChineseCharacters > 30,
    noMojibake: !dom.suspiciousMojibake,
    noConsoleErrors: consoleErrors.length === 0,
    noHorizontalOverflow: dom.horizontalOverflowPx === 0,
    exactSingleSelectionAfterDraft: JSON.stringify(dom.exactSelectedReferenceKeys) === JSON.stringify(["F001|profile.edge.1"]),
    twoFormalOperations: JSON.stringify(dom.operationTypes) === JSON.stringify(["add_subobject_relation", "move_subobject"]),
    ambiguousProjectionBlocked: dom.noteStatuses.includes("requires_disambiguation") && correction.correction.operations.length === 2,
    sourceHashBound: /^[0-9a-f]{64}$/.test(correction.source_sha256) && dom.draftContainsSourceHash,
    reviewPolicyLocked: correction.review_policy.reviewOnly === true && correction.review_policy.accepted === false && correction.review_policy.ruleEnabled === false,
    exactReferencesCarried: correction.correction.selected_refs.length === 3,
    screenshotWritten: fs.existsSync(screenshotPath) && fs.statSync(screenshotPath).size > 10000,
  };
  const report = {
    ok: Object.values(checks).every(Boolean), status: Object.values(checks).every(Boolean) ? "pass" : "failed",
    browser: executablePath || "playwright-managed-chromium", reviewPath, correctionPath, screenshotPath,
    checks, dom, consoleErrors,
    hashes: { review: sha256(reviewPath), correction: sha256(correctionPath), screenshot: sha256(screenshotPath) },
  };
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify(report) + "\n");
  if (!report.ok) process.exitCode = 2;
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ ok: false, status: "failed", error: error.stack || error.message }) + "\n");
  process.exitCode = 2;
});
