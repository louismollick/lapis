#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[index + 1];
    if (!next || next.startsWith("--")) {
      args[key] = true;
      continue;
    }
    args[key] = next;
    index += 1;
  }
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.bundle) {
    throw new Error("Usage: npm run repro:lookup-click -- --bundle <dir> [--note <id>] [--kanji <char>]");
  }

  const bundleDir = path.resolve(String(args.bundle));
  const bundle = JSON.parse(fs.readFileSync(path.join(bundleDir, "bundle.json"), "utf8"));
  const note = selectNote(bundle, args.note);
  const report = await runReplay(bundleDir, note, args.kanji ? String(args.kanji) : null);
  writeArtifacts(bundleDir, report);

  if (!report.ok) {
    console.error(report.reason);
    process.exitCode = 1;
    return;
  }
  console.log(`Lookup click reproduced: note ${note.id}, kanji ${report.clickedKanji}`);
}

function selectNote(bundle, noteId) {
  const notes = Array.isArray(bundle.notes) ? bundle.notes : [];
  if (!notes.length) throw new Error("Bundle has no notes.");
  if (!noteId) return notes[0];
  const note = notes.find((item) => String(item.id) === String(noteId));
  if (!note) throw new Error(`Note ${noteId} not found in bundle.`);
  return note;
}

async function runReplay(bundleDir, note, requestedKanji) {
  const report = {
    ok: false,
    reason: "",
    noteId: note.id,
    clickedKanji: null,
    console: [],
    pageErrors: [],
    requestFailures: [],
    checks: {},
  };
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on("console", (message) => {
    report.console.push({ type: message.type(), text: message.text() });
  });
  page.on("pageerror", (error) => {
    report.pageErrors.push(String(error));
  });
  page.on("requestfailed", (request) => {
    report.requestFailures.push({
      url: request.url(),
      failure: request.failure()?.errorText || "request failed",
    });
  });

  try {
    const replayPath = path.join(bundleDir, note.replayHtml || `notes/note_${note.id}.html`);
    await page.goto(pathToFileURL(replayPath).href, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle").catch(() => {});

    report.checks.cardLoaded = true;
    report.checks.manifestLoaded = await page.evaluate(() => Boolean(window.__lapisLookupStoreManifest));
    if (!report.checks.manifestLoaded) {
      return fail(report, "Lookup store manifest did not load.");
    }

    const targetCount = await page.locator(".lapis-lookup-kanji-target").count();
    report.checks.kanjiTargets = targetCount;
    if (targetCount < 1) {
      return fail(report, "No .lapis-lookup-kanji-target elements found.");
    }

    const target = requestedKanji
      ? page.locator(`.lapis-lookup-kanji-target[data-kanji="${cssEscape(requestedKanji)}"]`).first()
      : page.locator(".lapis-lookup-kanji-target").first();
    if ((await target.count()) < 1) {
      return fail(report, `Requested kanji target not found: ${requestedKanji}`);
    }
    report.clickedKanji = await target.getAttribute("data-kanji");
    await target.click();
    await page.waitForFunction(() => {
      const overlay = document.querySelector("#lapis-lookup-overlay");
      const view = document.querySelector("#kanji-popover-view");
      return overlay && view && !overlay.classList.contains("hidden") && !view.classList.contains("hidden");
    }, null, { timeout: 5000 }).catch(() => {});

    report.checks.kanjiPopoverOpen = await page.evaluate(() => {
      const overlay = document.querySelector("#lapis-lookup-overlay");
      const view = document.querySelector("#kanji-popover-view");
      return Boolean(overlay && view && !overlay.classList.contains("hidden") && !view.classList.contains("hidden"));
    });
    if (!report.checks.kanjiPopoverOpen) {
      return fail(report, "Kanji popover did not open after click.");
    }

    const wordRows = page.locator(".lapis-lookup-word-row");
    report.checks.relatedWordRows = await wordRows.count();
    if (report.checks.relatedWordRows > 0) {
      report.checks.firstWordRowTermHtml = await page
        .locator(".lapis-lookup-word-row .lapis-lookup-word-term")
        .first()
        .innerHTML();
      report.checks.firstWordRowFrequencySource = await page
        .locator(".lapis-lookup-word-row .lapis-lookup-word-frequency-source")
        .first()
        .textContent()
        .catch(() => null);
      await wordRows.first().click();
      await page.waitForFunction(() => {
        const view = document.querySelector("#word-popover-view");
        return view && !view.classList.contains("hidden");
      }, null, { timeout: 5000 }).catch(() => {});
      report.checks.wordPopoverOpen = await page.evaluate(() => {
        const view = document.querySelector("#word-popover-view");
        return Boolean(view && !view.classList.contains("hidden"));
      });
      if (!report.checks.wordPopoverOpen) {
        return fail(report, "Word popover did not open after related-word click.");
      }
      report.checks.wordTitleHtml = await page.locator("#lapis-lookup-word-title").innerHTML();
      report.checks.wordSubtitleText = await page.locator("#lapis-lookup-word-subtitle").textContent();
    } else {
      report.checks.wordPopoverOpen = "not-applicable";
    }

    if (report.pageErrors.length || report.requestFailures.length) {
      return fail(report, "Replay had page errors or failed requests.");
    }

    report.ok = true;
    return report;
  } finally {
    await page.screenshot({ path: path.join(bundleDir, "screenshot.png"), fullPage: true }).catch(() => {});
    await browser.close();
  }
}

function fail(report, reason) {
  report.ok = false;
  report.reason = reason;
  return report;
}

function writeArtifacts(bundleDir, report) {
  fs.writeFileSync(path.join(bundleDir, "repro-report.json"), `${JSON.stringify(report, null, 2)}\n`);
  fs.writeFileSync(
    path.join(bundleDir, "console.log"),
    report.console.map((item) => `[${item.type}] ${item.text}`).join("\n"),
  );
  fs.writeFileSync(
    path.join(bundleDir, "network-failures.json"),
    `${JSON.stringify(report.requestFailures, null, 2)}\n`,
  );
}

function cssEscape(value) {
  return String(value).replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
