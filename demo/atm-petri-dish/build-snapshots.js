#!/usr/bin/env node
/*
 * Build snapshot data for ATM Petri demo.
 *
 * Usage (from repo root):
 *   node temp_workspace/AI-learning-notes/demo/atm-petri-dish/build-snapshots.js
 *
 * Reads:
 *   - artifacts/atm-atomize/demand-police.report.json
 *   - atomic_workbench/capsules/<slug>/capsule.manifest.json (12 selected)
 *   - atomic_workbench/anchors/<slug>/anchor.manifest.json (1)
 *
 * Writes (next to this script):
 *   - data/capsules.snapshot.json
 *   - data/anchors.snapshot.json
 *   - data/demand-police.snapshot.json
 *
 * Each output is wrapped with a _meta header so the game can warn users
 * that they are looking at a point-in-time snapshot, not live data.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const REPO_ROOT = path.resolve(__dirname, '..', '..', '..', '..');
const OUT_DIR = path.resolve(__dirname, 'data');

const SELECTED_CAPSULES = [
  'parse-color',
  'normalize-css-color-to-hex',
  'build-draft-from-html',
  'collect-behavior',
  'merge-computed-style',
  'parse-fragment-list',
  'resolve-font-family-to-asset',
  'apply-text-transform-general',
  'compute-letter-spacing',
  'infer-tab-semantic-hints',
  'build-font-face-registry',
  'normalize-rect',
];

const SELECTED_ANCHORS = ['draft-builder-core-82992a5f'];

const DEMAND_POLICE_REPORT = path.join(
  REPO_ROOT,
  'artifacts',
  'atm-atomize',
  'demand-police.report.json'
);

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function writeJson(filePath, value) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2) + '\n', 'utf8');
  const rel = path.relative(REPO_ROOT, filePath).replace(/\\/g, '/');
  console.log(`✅ Wrote ${rel}`);
}

function pickCapsuleFields(manifest) {
  return {
    capsuleId: manifest.capsuleId,
    symbolName: manifest.symbolName,
    anchorId: manifest.anchorId,
    moduleSlug: manifest.moduleSlug,
    source: {
      file: manifest.source?.file,
      sourceRange: manifest.source?.sourceRange,
      semanticFingerprint: manifest.source?.semanticFingerprint,
    },
    tier: manifest.tier,
    recommendedTier: manifest.recommendedTier,
    classification: manifest.classification,
    behaviorContract: manifest.behaviorContract,
    usageRefStats: manifest.usageRefStats,
    lineage: manifest.lineage,
    promotion: manifest.promotion,
  };
}

function pickAnchorFields(manifest) {
  return {
    anchorId: manifest.anchorId,
    kind: manifest.kind,
    role: manifest.role,
    logicalName: manifest.logicalName,
    source: manifest.source,
    semanticFingerprint: manifest.semanticFingerprint,
    children: manifest.children,
    lineage: manifest.lineage,
    promotion: manifest.promotion,
  };
}

function buildCapsulesSnapshot() {
  const items = [];
  for (const slug of SELECTED_CAPSULES) {
    const manifestPath = path.join(
      REPO_ROOT,
      'atomic_workbench',
      'capsules',
      slug,
      'capsule.manifest.json'
    );
    if (!fs.existsSync(manifestPath)) {
      console.warn(`  ⚠ missing capsule: ${slug}`);
      continue;
    }
    items.push(pickCapsuleFields(readJson(manifestPath)));
  }
  return {
    _meta: {
      generatedAt: new Date().toISOString(),
      generatedBy: 'TASK-WEB-0001',
      source: 'atomic_workbench/capsules/<slug>/capsule.manifest.json',
      selected: SELECTED_CAPSULES,
      isSnapshot: true,
      note: '這是某一時點的 ATM 快照。重生指令見本目錄的 README.md。',
    },
    capsules: items,
  };
}

function buildAnchorsSnapshot() {
  const items = [];
  for (const slug of SELECTED_ANCHORS) {
    const manifestPath = path.join(
      REPO_ROOT,
      'atomic_workbench',
      'anchors',
      slug,
      'anchor.manifest.json'
    );
    if (!fs.existsSync(manifestPath)) {
      console.warn(`  ⚠ missing anchor: ${slug}`);
      continue;
    }
    items.push(pickAnchorFields(readJson(manifestPath)));
  }
  return {
    _meta: {
      generatedAt: new Date().toISOString(),
      generatedBy: 'TASK-WEB-0001',
      source: 'atomic_workbench/anchors/<slug>/anchor.manifest.json',
      selected: SELECTED_ANCHORS,
      isSnapshot: true,
    },
    anchors: items,
  };
}

function buildDemandPoliceSnapshot() {
  if (!fs.existsSync(DEMAND_POLICE_REPORT)) {
    console.warn(`  ⚠ run: node tools_node/atm-atomize.js demand-police --json`);
    return {
      _meta: {
        generatedAt: new Date().toISOString(),
        generatedBy: 'TASK-WEB-0001',
        source: 'artifacts/atm-atomize/demand-police.report.json',
        isSnapshot: true,
        note: 'Report not found; run atm-atomize demand-police first.',
      },
      report: null,
    };
  }
  const report = readJson(DEMAND_POLICE_REPORT);
  // Trim findings to the SELECTED capsules to keep snapshot small.
  const selectedCapsuleIds = new Set(
    SELECTED_CAPSULES.map(
      (slug) => 'H2U-CAPSULE-' + slug.toUpperCase().replace(/-/g, '-')
    )
  );
  const filteredFindings = (report.findings || []).filter((f) => {
    if (f.capsuleId && selectedCapsuleIds.has(f.capsuleId)) return true;
    if (
      Array.isArray(f.capsuleIds) &&
      f.capsuleIds.some((id) => selectedCapsuleIds.has(id))
    )
      return true;
    return false;
  });
  return {
    _meta: {
      generatedAt: new Date().toISOString(),
      generatedBy: 'TASK-WEB-0001',
      source: 'artifacts/atm-atomize/demand-police.report.json',
      isSnapshot: true,
      filterNote: '只保留 SELECTED 12 顆 capsule 相關的 findings',
    },
    summary: report.summary,
    passed: report.passed,
    blockingCount: report.blockingCount,
    findings: filteredFindings,
  };
}

function main() {
  console.log(`▶ Building snapshots from ${REPO_ROOT}`);
  writeJson(path.join(OUT_DIR, 'capsules.snapshot.json'), buildCapsulesSnapshot());
  writeJson(path.join(OUT_DIR, 'anchors.snapshot.json'), buildAnchorsSnapshot());
  writeJson(
    path.join(OUT_DIR, 'demand-police.snapshot.json'),
    buildDemandPoliceSnapshot()
  );
  console.log(`✅ Done.`);
}

if (require.main === module) {
  main();
}
