import { readFileSync } from "node:fs";
import { arch, cpus, platform, release, totalmem } from "node:os";
import { generatePattern, stats } from "../frontend/src/engine";

const fixture = new URL("./generated/synthetic-3.json", import.meta.url);
const input = JSON.parse(readFileSync(fixture, "utf8"));
const rgba = new Uint8ClampedArray(input.rgba);
const mask = new Uint8Array(input.mask);
const targetWidth = 64;
const colorLimit = 16;

function measure() {
  const started = performance.now();
  const pattern = generatePattern(rgba, input.width, input.height, mask, targetWidth, colorLimit);
  const ms = Math.round((performance.now() - started) * 100) / 100;
  const total = stats(pattern.cells).total;
  return { ms, grid: [pattern.width, pattern.height], beans: total, colors: pattern.palette.length };
}

const processSetupMs = Math.round(process.uptime() * 1000);
const first = measure();
const warm = Array.from({ length: 3 }, measure);
if (warm.some(run => run.beans !== first.beans || run.colors !== first.colors))
  throw Error("The repeated fixture produced inconsistent totals.");
console.log(JSON.stringify({
  fixture: "synthetic-3", inputPixels: [input.width, input.height], targetWidth, colorLimit,
  algorithm: "hue4 / mean", node: process.version, os: [platform(), release(), arch()],
  cpu: cpus()[0]?.model, logicalCpus: cpus().length, ramMiB: Math.round(totalmem() / 1024 ** 2),
  processSetupMs, first, warm, processPeakRssKiB: process.resourceUsage().maxRSS,
}, null, 2));
