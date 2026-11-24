import assert from "node:assert/strict";
import fs from "node:fs";
import { generatePattern, generateRefinedPattern, hexRgb, sampleGrid, DEFAULT_PALETTE } from "../frontend/src/engine.ts";
import { generateConstrainedPattern } from "../frontend/src/constraints.ts";
import { deltaE00, srgbLab, summarize } from "./metrics.ts";

const dir = "experiments/generated";
const samples: { id: string }[] = JSON.parse(fs.readFileSync(dir + "/manifest.json", "utf8"));
const stock = DEFAULT_PALETTE.filter((_, i) => i % 2 === 0);
const wanted = new Set(["astronaut", "chelsea", "coffee", "synthetic-3", "synthetic-4", "synthetic-9"]);
const results = [];

for (const sample of samples.filter(row => wanted.has(row.id))) {
  const image = JSON.parse(fs.readFileSync(dir + "/" + sample.id + ".json", "utf8"));
  const pixels = new Uint8ClampedArray(image.rgba);
  const mask = new Uint8Array(image.mask);
  const grid = sampleGrid(pixels, image.width, image.height, mask, 64);
  const args = [pixels, image.width, image.height, mask, 64, 16] as const;
  const runs = {
    base: generatePattern(...args),
    roi: generateConstrainedPattern(...args, { required: [], roi: [0.25, 0.25, 0.75, 0.75], weight: 3 }),
    swap: generateRefinedPattern(...args),
    stock: generatePattern(...args, stock),
  };
  const outputs = Object.fromEntries(Object.entries(runs).map(([key, pattern]) => {
    const palette = new Map(pattern.palette.map(c => [c.code, srgbLab(hexRgb(c.hex))]));
    assert.ok(pattern.palette.length <= 16);
    assert.equal(pattern.width, grid.width); assert.equal(pattern.height, grid.height);
    const errors = grid.values.flatMap((value, index) => {
      const code = pattern.cells[index];
      assert.equal(value === null, code === null);
      if (value === null || code === null) return [];
      if (key === "stock") assert.ok(stock.some(color => color.code === code));
      const target = palette.get(code);
      assert.ok(target);
      return [deltaE00(srgbLab(value), target)];
    });
    return [key, { ...summarize(errors), colors: new Set(pattern.cells.filter(c => c !== null)).size }];
  }));
  results.push({ id: sample.id, ...outputs });
}
assert.equal(results.length, wanted.size);
fs.writeFileSync(dir + "/platform-ablation.json", JSON.stringify({ assumedStockColorCount: stock.length, results }, null, 2));
console.table(results.map(row => ({ id: row.id, base: row.base.mean.toFixed(3), roi: row.roi.mean.toFixed(3),
  swap: row.swap.mean.toFixed(3), stock: row.stock.mean.toFixed(3) })));
