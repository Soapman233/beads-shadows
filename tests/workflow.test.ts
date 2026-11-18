import test from "node:test";
import assert from "node:assert/strict";
import { materialsCSV, printBlocks } from "../frontend/src/materials";
import {
  generatePattern,
  generateRefinedPattern,
  stats,
  type Pattern,
} from "../frontend/src/engine";
test("print tiles cover every cell once and CSV counts actual white beads safely", () => {
  const p: Pattern = {
    width: 33,
    height: 35,
    cells: Array(1155).fill("=X"),
    palette: [{ code: "=X", hex: "#FFFFFF" }],
    colorLimit: 1,
    paletteName: "=unsafe",
  };
  const seen = new Set<number>();
  for (const b of printBlocks(p, 16))
    for (let y = b.y; y < b.y + b.height; y++)
      for (let x = b.x; x < b.x + b.width; x++) {
        const i = y * p.width + x;
        assert.equal(seen.has(i), false);
        seen.add(i);
      }
  assert.equal(seen.size, p.cells.length);
  const csv = materialsCSV(p, 10);
  assert.ok(csv.startsWith("\uFEFF"));
  assert.ok(csv.includes("'=unsafe"));
  assert.ok(csv.includes('"1155","1271"'));
});
test("bounded refinement preserves mask and budget", () => {
  const rgba = new Uint8ClampedArray(32 * 32 * 4),
    mask = new Uint8Array(1024).fill(1);
  for (let i = 0; i < 1024; i++) rgba.set([i % 250, 160, 210, 255], i * 4);
  const a = generatePattern(rgba, 32, 32, mask, 32, 8),
    b = generateRefinedPattern(rgba, 32, 32, mask, 32, 8);
  assert.equal(stats(a.cells).total, stats(b.cells).total);
  assert.equal(b.width, a.width);
  assert.ok(b.palette.length <= 8);
});

test("materials clamps finite allowance and defaults nonfinite input without counting empty cells", () => {
  const p: Pattern = {
    width: 3,
    height: 1,
    cells: ["H2", null, "H2"],
    palette: [{ code: "H2", hex: "#FFFFFF" }],
    colorLimit: 1,
    paletteName: '=x,"quoted"\nline',
  };
  for (const extra of [NaN, Infinity, -Infinity, -1, undefined]) {
    const output = materialsCSV(p, extra);
    assert.ok(output.includes('"2","2"'));
    assert.ok(!output.includes("NaN"));
    assert.ok(!output.includes("Infinity"));
  }
  assert.ok(materialsCSV(p, 10).includes('"2","3"'));
  assert.ok(materialsCSV(p, 1000).includes('"2","4"'));
  assert.ok(materialsCSV(p).includes('"\'=x,""quoted""\nline"'));
});
