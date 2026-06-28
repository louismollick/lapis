import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";
import { describe, it } from "node:test";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const cliPath = path.join(repoRoot, "tools/repro/src/cli.js");

describe("lookup click replay", () => {
  it("opens kanji and word popovers from a complete bundle", () => {
    const bundleDir = createBundle({ manifest: true, shard: true });

    const result = runReplay(bundleDir);

    assert.equal(result.status, 0, result.stderr);
    const report = readReport(bundleDir);
    assert.equal(report.ok, true);
    assert.equal(report.checks.manifestLoaded, true);
    assert.equal(report.checks.kanjiPopoverOpen, true);
    assert.equal(report.checks.wordPopoverOpen, true);
  });

  it("reports missing manifest clearly", () => {
    const bundleDir = createBundle({ manifest: false, shard: false });

    const result = runReplay(bundleDir);

    assert.notEqual(result.status, 0);
    const report = readReport(bundleDir);
    assert.equal(report.reason, "Lookup store manifest did not load.");
  });

  it("reports missing shard as replay failure", () => {
    const bundleDir = createBundle({ manifest: true, shard: false });

    const result = runReplay(bundleDir);

    assert.notEqual(result.status, 0);
    const report = readReport(bundleDir);
    assert.match(report.reason, /failed requests/);
    assert.equal(report.checks.kanjiPopoverOpen, true);
  });
});

function runReplay(bundleDir) {
  return spawnSync(process.execPath, [cliPath, "--bundle", bundleDir, "--kanji", "粒"], {
    cwd: path.join(repoRoot, "tools/repro"),
    encoding: "utf8",
  });
}

function readReport(bundleDir) {
  return JSON.parse(fs.readFileSync(path.join(bundleDir, "repro-report.json"), "utf8"));
}

function createBundle({ manifest, shard }) {
  const bundleDir = fs.mkdtempSync(path.join(os.tmpdir(), "lapis-repro-"));
  fs.mkdirSync(path.join(bundleDir, "notes"));
  const payload = {
    version: 2,
    expression: "粒子",
    kanji: [{ char: "粒", wordRefs: ["粒子"], components: ["米"] }],
  };
  const html = renderBackHtml({
    Expression: "粒子",
    ExpressionFurigana: "",
    ExpressionReading: "りゅうし",
    KanjiLookupData: JSON.stringify(payload),
  });
  fs.writeFileSync(path.join(bundleDir, "notes/note_1.html"), html);
  fs.writeFileSync(
    path.join(bundleDir, "bundle.json"),
    `${JSON.stringify({
      version: 1,
      notes: [
        {
          id: 1,
          replayHtml: "notes/note_1.html",
          expression: "粒子",
          kanjiLookupData: JSON.stringify(payload),
        },
      ],
    })}\n`,
  );

  if (manifest) {
    fs.writeFileSync(
      path.join(bundleDir, "_lapis_lookup_store.js"),
      `window.__lapisLookupInstallStore(${JSON.stringify({
        version: 2,
        type: "manifest",
        encoding: "zlib+base64-json",
        shardCount: 64,
        shardPrefix: "_lapis_lookup_store_",
        shardSuffix: ".js",
      })});\n`,
    );
  }
  if (shard) {
    const shardIndex = lookupTermShard("粒子");
    fs.writeFileSync(
      path.join(bundleDir, `_lapis_lookup_store_${String(shardIndex).padStart(2, "0")}.js`),
      `window.__lapisLookupInstallStore(${JSON.stringify({
        version: 2,
        type: "shard",
        encoding: "zlib+base64-json",
        shard: shardIndex,
        payload: compressLookupPayload({
          version: 2,
          terms: {
            "粒子": {
              term: "粒子",
              reading: "りゅうし",
              frequency: { value: 100, source: "JPDB" },
              entryHtml: "<div>particle</div>",
            },
          },
        }),
      })});\n`,
    );
  }
  return bundleDir;
}

function renderBackHtml(fields) {
  const template = fs.readFileSync(path.join(repoRoot, "src/back.html"), "utf8");
  const css = fs.readFileSync(path.join(repoRoot, "src/styling.css"), "utf8");
  let body = template;
  for (const [name, value] of Object.entries(fields)) {
    body = renderSections(body, name, value);
  }
  body = body.replace(/{{[#^][^}]+}}[\s\S]*?{{\/[^}]+}}/g, "");
  body = body.replace(/{{(?:text:|furigana:|kana:|kanji:)?([^}]+)}}/g, (_match, name) => fields[name.trim()] || "");
  return [
    "<!doctype html>",
    '<html lang="ja">',
    "<head>",
    '<meta charset="utf-8">',
    '<base href="../">',
    `<style>${css}</style>`,
    "</head>",
    "<body>",
    body,
    "</body>",
    "</html>",
  ].join("\n");
}

function renderSections(template, name, value) {
  const escaped = escapeRegExp(name);
  return template
    .replace(new RegExp(`{{#${escaped}}}([\\s\\S]*?){{/${escaped}}}`, "g"), value ? "$1" : "")
    .replace(new RegExp(`{{\\^${escaped}}}([\\s\\S]*?){{/${escaped}}}`, "g"), value ? "" : "$1");
}

function compressLookupPayload(payload) {
  return zlib.deflateSync(Buffer.from(JSON.stringify(payload), "utf8"), { level: 9 }).toString("base64");
}

function lookupTermShard(term) {
  return stableLookupHash(term) % 64;
}

function stableLookupHash(value) {
  let result = 2166136261;
  for (const character of String(value)) {
    result ^= character.codePointAt(0);
    result = Math.imul(result, 16777619) >>> 0;
  }
  return result >>> 0;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
