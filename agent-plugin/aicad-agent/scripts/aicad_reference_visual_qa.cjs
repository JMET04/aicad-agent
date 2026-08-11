#!/usr/bin/env node
"use strict";

const fs = require("fs");
const crypto = require("crypto");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch (_error) {
    const bundled = path.join(
      os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime",
      "dependencies", "node", "node_modules", "playwright"
    );
    return require(bundled);
  }
}

async function main() {
  const preview = path.resolve(process.argv[2] || "");
  const reportPath = path.resolve(process.argv[3] || "reference-preview.visual.json");
  const screenshotPath = path.resolve(process.argv[4] || "reference-preview.png");
  if (!fs.existsSync(preview)) throw new Error(`preview not found: ${preview}`);
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });

  const { chromium } = loadPlaywright();
  const browserCandidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  ];
  const executablePath = browserCandidates.find((candidate) => fs.existsSync(candidate));
  const browser = await chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage({ viewport: { width: 1400, height: 1000 }, deviceScaleFactor: 1 });
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  await page.goto(pathToFileURL(preview).href, { waitUntil: "load" });
  await page.screenshot({ path: screenshotPath, fullPage: true });

  const dom = await page.evaluate(() => {
    const rect = (element) => {
      const value = element.getBoundingClientRect();
      return [value.left, value.top, value.right, value.bottom];
    };
    const overlaps = (first, second, padding = 0) => !(
      first[2] + padding <= second[0] || second[2] + padding <= first[0]
      || first[3] + padding <= second[1] || second[3] + padding <= first[1]
    );
    const annotationElements = [...document.querySelectorAll("svg text[data-annotation-id]")];
    const annotations = annotationElements.map((element) => ({
      id: element.getAttribute("data-annotation-id"),
      text: (element.textContent || "").trim(),
      rect: rect(element),
      visible: !!(element.getClientRects().length && getComputedStyle(element).visibility !== "hidden"),
    }));
    const textOverlaps = [];
    for (let index = 0; index < annotations.length; index += 1) {
      for (let other = index + 1; other < annotations.length; other += 1) {
        if (overlaps(annotations[index].rect, annotations[other].rect, 1)) {
          textOverlaps.push([annotations[index].id, annotations[other].id]);
        }
      }
    }
    const geometry = [...document.querySelectorAll("svg [data-object-id]")].map((element) => ({
      id: element.getAttribute("data-object-id"), rect: rect(element),
    }));
    const annotationGeometryOverlaps = [];
    for (const annotation of annotations) {
      for (const object of geometry) {
        if (overlaps(annotation.rect, object.rect, 1)) annotationGeometryOverlaps.push([annotation.id, object.id]);
      }
    }
    const section = document.querySelector("section");
    const svg = document.querySelector("svg");
    return {
      charset: document.characterSet,
      lang: document.documentElement.lang,
      gate: (document.querySelector(".gate")?.textContent || "").trim(),
      nativeSvgTextCount: document.querySelectorAll("svg text").length,
      annotations,
      geometryObjectCount: geometry.length,
      textOverlaps,
      annotationGeometryOverlaps,
      sectionBackground: section ? getComputedStyle(section).backgroundColor : null,
      svgBackground: svg ? getComputedStyle(svg).backgroundColor : null,
      bodyText: document.body.innerText,
      svgRect: svg ? rect(svg) : null,
      svgViewBox: svg ? {
        width: svg.viewBox.baseVal.width,
        height: svg.viewBox.baseVal.height,
        preserveAspectRatio: svg.getAttribute("preserveAspectRatio"),
      } : null,
    };
  });

  const requiredIds = ["TXT_TITLE", "DIM_WIDTH", "DIM_HEIGHT", "DIM_HOLE", "TXT_STATUS"];
  const visibleIds = new Set(dom.annotations.filter((item) => item.visible).map((item) => item.id));
  const checks = {
    utf8: dom.charset === "UTF-8" && dom.lang === "zh-CN",
    opaqueWhiteBackground: dom.sectionBackground === "rgb(255, 255, 255)" && dom.svgBackground === "rgb(255, 255, 255)",
    nativeSvgText: dom.nativeSvgTextCount >= 6,
    viewBoxAspectPreserved: !!dom.svgRect && !!dom.svgViewBox
      && Math.abs((dom.svgRect[2] - dom.svgRect[0]) / (dom.svgRect[3] - dom.svgRect[1])
        - dom.svgViewBox.width / dom.svgViewBox.height) <= 0.001,
    allRequiredAnnotationsVisible: requiredIds.every((id) => visibleIds.has(id)),
    chineseContentVisible: dom.bodyText.includes("机械安装板参考图（毫米）") && dom.bodyText.includes("网页仅作结构与版式参考"),
    noTextOverlap: dom.textOverlaps.length === 0,
    noAnnotationGeometryOverlap: dom.annotationGeometryOverlaps.length === 0,
    noMojibakeMarkers: !/[\uFFFD\uE000-\uF8FF]/u.test(dom.bodyText),
    noConsoleErrors: consoleErrors.length === 0,
  };
  const report = {
    status: Object.values(checks).every(Boolean) ? "pass" : "failed",
    preview,
    screenshot: screenshotPath,
    checks,
    consoleErrors,
    dom,
  };
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  const manifestPath = preview.endsWith(".preview.html")
    ? preview.slice(0, -".preview.html".length) + ".manifest.json"
    : null;
  if (manifestPath && fs.existsSync(manifestPath)) {
    const digest = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
    const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    manifest.visual_validation = {
      status: report.status,
      report: reportPath,
      screenshot: screenshotPath,
      checks,
      browser: executablePath || "playwright-managed-chromium",
    };
    manifest.artifacts = { ...(manifest.artifacts || {}), visual_validation: reportPath, preview_png: screenshotPath };
    manifest.sha256 = { ...(manifest.sha256 || {}), visual_validation: digest(reportPath), preview_png: digest(screenshotPath) };
    fs.writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
  }
  await browser.close();
  process.stdout.write(`${JSON.stringify(report)}\n`);
  if (report.status !== "pass") process.exitCode = 2;
}

main().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exitCode = 1;
});
