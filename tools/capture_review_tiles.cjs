#!/usr/bin/env node
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { pathToFileURL } = require("url");

function playwright() {
  try { return require("playwright"); }
  catch (_) { return require(path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "node_modules", "playwright")); }
}

async function main() {
  const review = path.resolve(process.argv[2]);
  const out = path.resolve(process.argv[3]);
  fs.mkdirSync(out, { recursive: true });
  const executablePath = ["C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"].find(fs.existsSync);
  const browser = await playwright().chromium.launch({ headless: true, ...(executablePath ? { executablePath } : {}) });
  const page = await browser.newPage({ viewport: { width: 1200, height: 700 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(review).href, { waitUntil: "load" });
  await page.waitForFunction(() => window.__aicadSection && window.__aicadSection.hitCount > 0);
  const fullHeight = await page.evaluate(() => document.documentElement.scrollHeight);
  const tileHeight = 620;
  const starts = [0, Math.max(0, Math.round((fullHeight - tileHeight) / 2)), Math.max(0, fullHeight - tileHeight)];
  for (let i = 0; i < starts.length; i++) {
    await page.screenshot({ path: path.join(out, `modifier_v2_tile_${i + 1}.jpg`), type: "jpeg", quality: 48, clip: { x: 0, y: starts[i], width: 1200, height: Math.min(tileHeight, fullHeight - starts[i]) } });
  }
  await browser.close();
  console.log(JSON.stringify({ ok: true, fullHeight, starts }));
}

main().catch(error => { console.error(error.stack || error.message); process.exitCode = 2; });
