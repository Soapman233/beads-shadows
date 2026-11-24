import { hexRgb, type Color, type SampleGrid } from "../frontend/src/engine";
import { srgbLab } from "./metrics";

type Lab = number[];
type Sample = { lab: Lab; index: number };

function squareDistance(a: Lab, b: Lab) {
  return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2;
}

function nearest(lab: Lab, centers: Lab[]) {
  let best = 0;
  let distance = squareDistance(lab, centers[0]);
  for (let i = 1; i < centers.length; i++) {
    const candidate = squareDistance(lab, centers[i]);
    if (candidate < distance) {
      best = i;
      distance = candidate;
    }
  }
  return best;
}

// Deterministic farthest-first seeds in row order, followed by Lloyd updates.
// Every non-empty grid cell has equal weight, including repeated colors.
function cluster(samples: Sample[], limit: number) {
  const centers = [samples[0].lab];
  const distances = samples.map(({ lab }) => squareDistance(lab, centers[0]));
  while (centers.length < limit) {
    let farthest = 0;
    for (let i = 1; i < distances.length; i++) {
      if (distances[i] > distances[farthest]) farthest = i;
    }
    if (distances[farthest] === 0) break;
    const seed = samples[farthest].lab;
    centers.push(seed);
    for (let i = 0; i < samples.length; i++) {
      distances[i] = Math.min(distances[i], squareDistance(samples[i].lab, seed));
    }
  }

  let iterations = 0;
  while (iterations < 50) {
    iterations++;
    const sums = centers.map(() => [0, 0, 0, 0]);
    for (const { lab } of samples) {
      const totals = sums[nearest(lab, centers)];
      totals[0] += lab[0];
      totals[1] += lab[1];
      totals[2] += lab[2];
      totals[3]++;
    }
    let maxShift = 0;
    for (let i = 0; i < centers.length; i++) {
      const [l, a, b, count] = sums[i];
      if (!count) continue;
      const updated = [l / count, a / count, b / count];
      maxShift = Math.max(maxShift, squareDistance(centers[i], updated));
      centers[i] = updated;
    }
    if (maxShift < 1e-8) break;
  }
  return { centers, iterations };
}

export function kmeansLab(grid: SampleGrid, colors: Color[], limit: number) {
  if (!Number.isInteger(limit) || limit < 1 || !colors.length) {
    throw Error("K and available palette must be positive");
  }
  const samples = grid.values.flatMap((value, index) => value ? [{ lab: srgbLab(value), index }] : []);
  if (!samples.length) throw Error("The comparison needs a nonempty foreground");
  const { centers, iterations } = cluster(samples, limit);
  const paletteLab = colors.map(({ hex }) => srgbLab(hexRgb(hex)));
  // Centroids may share a physical bead color. Map each to its nearest CIELAB
  // swatch, deduplicate, then give each grid cell its nearest selected swatch.
  const picked = [...new Set(centers.map(center => nearest(center, paletteLab)))];
  const selected = picked.map(index => paletteLab[index]);
  const cells = grid.values.map<string | null>(() => null);
  for (const { index, lab } of samples) cells[index] = colors[picked[nearest(lab, selected)]].code;
  const used = new Set(cells);
  return { cells, palette: colors.filter(color => used.has(color.code)), clusters: centers.length, iterations };
}
