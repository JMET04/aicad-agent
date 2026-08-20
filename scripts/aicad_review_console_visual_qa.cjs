#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
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

function fileSha256(filePath) {
  return crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
}

async function inspectViewport(browser, reviewPath, outputDir, viewport) {
  const context = await browser.newContext({
    viewport: { width: viewport.width, height: viewport.height },
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(pathToFileURL(reviewPath).href, { waitUntil: "load" });

  const firstHit = page.locator(".view-hit").first();
  await firstHit.focus();
  await firstHit.press("Enter");
  await page.locator("#aiInstruction").fill("保留中心与支撑关系，复核尺寸链后再回传。 ");
  await page.locator("#addInstruction").click();

  const screenshotPath = path.join(outputDir, `review-console-${viewport.width}.png`);
  await firstHit.focus();
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const dom = await page.evaluate(() => {
    const root = document.documentElement;
    const focusedHit = document.activeElement?.classList?.contains("view-hit") ? document.activeElement : null;
    const focusedPrimitive = focusedHit?.closest(".entity-pair")?.querySelector(".view-entity");
    const command = document.querySelector(".command-zone");
    const frames = [...document.querySelectorAll(".annotation-box")].map((box) => {
      const frame = box.querySelector(".annotation-frame");
      const text = box.querySelector(".native-text,.dimension-value");
      if (!frame || !text || typeof frame.getBBox !== "function" || typeof text.getBBox !== "function") {
        return { contained: false };
      }
      const a = frame.getBBox();
      const b = text.getBBox();
      const epsilon = Math.max(0.01, a.width * 0.002);
      return {
        contained: b.x >= a.x - epsilon && b.y >= a.y - epsilon &&
          b.x + b.width <= a.x + a.width + epsilon &&
          b.y + b.height <= a.y + a.height + epsilon,
        frame: [a.x, a.y, a.width, a.height],
        text: [b.x, b.y, b.width, b.height],
      };
    });
    const labelledControls = [...document.querySelectorAll("button,input,select,textarea")].map((control) => {
      const id = control.id;
      const label = control.closest("label") || (id ? document.querySelector(`label[for='${CSS.escape(id)}']`) : null);
      return {
        id: id || control.tagName.toLowerCase(),
        labelled: !!(label || control.getAttribute("aria-label") || control.getAttribute("aria-labelledby") || control.textContent.trim()),
      };
    });
    const commandStyle = command ? getComputedStyle(command) : null;
    const primitiveStyle = focusedPrimitive ? getComputedStyle(focusedPrimitive) : null, focusStyle = focusedHit ? getComputedStyle(focusedHit) : null;
    return {
      overflowPx: Math.max(0, root.scrollWidth - root.clientWidth),
      activeElementIsViewHit: !!focusedHit,
      focusPairClass: focusedHit?.closest(".entity-pair")?.classList.contains("keyboard-focus") || false,
      stage: root.dataset.reviewStage,
      explicitStates: document.querySelector(".status-strip")?.innerText || "",
      stageCount: document.querySelectorAll(".stage-step").length,
      selectedCount: window.__aicadUi?.selectedRefs.length ?? -1,
      instructionCount: window.__aicadUi?.instructions.length ?? -1,
      commandEnabled: !document.querySelector("#submitRequest")?.disabled,
      commandPosition: commandStyle?.position,
      focusStroke: primitiveStyle?.stroke,
      focusStrokeWidth: primitiveStyle?.strokeWidth,
      focusHitStroke: focusStyle?.stroke,
      focusHitStrokeWidth: focusStyle?.strokeWidth,
      reducedMotionDuration: getComputedStyle(document.querySelector(".switch-track"), "::after").transitionDuration,
      annotationCount: frames.length,
      annotationsContained: frames.every((row) => row.contained),
      frameFailures: frames.filter((row) => !row.contained).slice(0, 5),
      unlabelledControls: labelledControls.filter((row) => !row.labelled),
      bodyWidth: document.body.getBoundingClientRect().width,
      viewportWidth: root.clientWidth,
    };
  });

  await context.close();
  const checks = {
    noConsoleErrors: errors.length === 0,
    noHorizontalOverflow: dom.overflowPx === 0,
    fiveStageRail: dom.stageCount === 5,
    explicitFreshnessSeverityBlock: dom.explicitStates.includes("SNAPSHOT BOUND") &&
      dom.explicitStates.includes("WARNING") && dom.explicitStates.includes("BLOCKED"),
    keyboardSelectionWorks: dom.selectedCount === 1,
    commandUnlocksAfterDraft: dom.instructionCount === 1 && dom.commandEnabled && dom.stage === "verify",
    keyboardFocusVisible: dom.activeElementIsViewHit && dom.focusPairClass && Number.parseFloat(dom.focusStrokeWidth || "0") >= 2.4 && dom.focusStroke === "rgb(0, 111, 187)",
    reducedMotionApplied: ["0s", "0.00001s", "1e-05s"].includes(dom.reducedMotionDuration),
    annotationsFramedWhenPresent: dom.annotationsContained,
    controlsLabelled: dom.unlabelledControls.length === 0,
    screenshotWritten: fs.existsSync(screenshotPath) && fs.statSync(screenshotPath).size > 10000,
  };
  return {
    viewport,
    ok: Object.values(checks).every(Boolean),
    checks,
    dom,
    errors,
    screenshotPath,
    screenshotSha256: fileSha256(screenshotPath),
  };
}

async function main() {
  const reviewPath = path.resolve(process.argv[2] || "");
  const outputDir = path.resolve(process.argv[3] || path.join("output", "review-console-visual"));
  if (!fs.existsSync(reviewPath)) throw new Error(`review not found: ${reviewPath}`);
  fs.mkdirSync(outputDir, { recursive: true });

  const { chromium } = loadPlaywright();
  const browserCandidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  ];
  const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const viewports = [
    { width: 1440, height: 1000, label: "desktop" },
    { width: 768, height: 1000, label: "tablet" },
    { width: 360, height: 800, label: "phone" },
  ];
  const results = [];
  for (const viewport of viewports) results.push(await inspectViewport(browser, reviewPath, outputDir, viewport));
  await browser.close();

  const ok = results.every((result) => result.ok);
  const report = {
    schemaVersion: "1.0",
    status: ok ? "pass" : "failed",
    browser: executablePath || "playwright-managed-chromium",
    reviewPath,
    reviewSha256: fileSha256(reviewPath),
    results,
  };
  const reportPath = path.join(outputDir, "review-console-visual-audit.json");
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8");
  process.stdout.write(JSON.stringify({ ...report, reportPath }) + "\n");
  if (!ok) process.exitCode = 2;
}

main().catch((error) => {
  process.stderr.write(JSON.stringify({ status: "failed", error: error.stack || error.message }) + "\n");
  process.exitCode = 2;
});
