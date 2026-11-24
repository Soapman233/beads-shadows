import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { DEFAULT_PALETTE, generatePattern, hexRgb, sampleGrid } from "../frontend/src/engine";
import { kmeansLab } from "./kmeans-lab";
import { deltaE00, srgbLab, summarize } from "./metrics";

const directory = new URL("./generated/", import.meta.url);
const read = (name: string) => JSON.parse(readFileSync(new URL(name, directory), "utf8"));
const manifest: { id: string; kind: string; public: boolean }[] = read("manifest.json");
const palette = DEFAULT_PALETTE;
const width = 64;
const k = 16;
const rows = [];

for (const item of manifest.filter(entry => entry.public)) {
  const source = read(item.id + ".json");
  const rgba = new Uint8ClampedArray(source.rgba);
  const mask = new Uint8Array(source.mask);
  const grid = sampleGrid(rgba, source.width, source.height, mask, width, "mean");
  const reference = grid.values.map(value => value ? srgbLab(value) : null);
  const paletteLab = new Map(palette.map(color => [color.code, srgbLab(hexRgb(color.hex))]));

  const measured = <T,>(operation: () => T) => {
    const start = performance.now();
    const output = operation();
    return { output, elapsedMs: performance.now() - start };
  };
  const baseline = measured(() => kmeansLab(sampleGrid(rgba, source.width, source.height, mask, width, "mean"), palette, k));
  const hue4 = measured(() => generatePattern(rgba, source.width, source.height, mask, width, k, palette, "mean"));
  assert.deepEqual([hue4.output.width, hue4.output.height], [grid.width, grid.height]);
  const score = (cells: (string | null)[], elapsedMs: number) => {
    assert.equal(cells.length, reference.length);
    const errors = [];
    const used = new Set<string>();
    for (const [index, lab] of reference.entries()) {
      const code = cells[index];
      assert.equal(code === null, lab === null, "same foreground occupancy");
      if (code === null || lab === null) continue;
      const matched = paletteLab.get(code);
      assert.ok(matched, "every code belongs to the fixed physical palette");
      used.add(code);
      errors.push(deltaE00(lab, matched));
    }
    assert.ok(used.size <= k);
    return { ...summarize(errors), actualColors: used.size, elapsedMs };
  };
  rows.push({
    ...item,
    width: grid.width,
    height: grid.height,
    crop: grid.crop,
    kmeans: { ...score(baseline.output.cells, baseline.elapsedMs), clusters: baseline.output.clusters,
      iterations: baseline.output.iterations },
    hue4: score(hue4.output.cells, hue4.elapsedMs),
  });
}

const outcome = {
  settings: { width, k, sampling: "mean", palette: "maxcleme/beadcolors legacy MARD220", runtime: process.version },
  rows,
};
const destination = new URL("kmeans-lab-results.json", directory);
writeFileSync(destination, JSON.stringify(outcome, null, 2));
const format = (n: number) => n.toFixed(3);
console.log("ID\tbeans\tkmeans K used\thue4 K used\tkmeans mean\thue4 mean\tkmeans P95\thue4 P95");
for (const { id, kmeans, hue4 } of rows) {
  console.log([id, kmeans.count, kmeans.actualColors, hue4.actualColors,
    format(kmeans.mean), format(hue4.mean), format(kmeans.p95), format(hue4.p95)].join("\t"));
}
console.log(`${rows.length} public inputs, results: ${fileURLToPath(destination)}`);
