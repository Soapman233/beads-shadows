import {
  sampleGrid,
  generatePattern,
  DEFAULT_PALETTE,
  DEFAULT_PALETTE_NAME,
  DEFAULT_PALETTE_INFO,
  type Pattern,
  srgbToOklab,
  hexRgb,
  hueDistanceSquared,
} from "./engine";
export type Constraints = {
  required: string[];
  roi?: [number, number, number, number];
  weight?: number;
};
export const CONSTRAINED_ALGORITHM = "hue4-weighted-required-v1";
export function validateConstraints(v: unknown, k = 32): Constraints {
  const c = v as Constraints;
  if (
    !c ||
    !Array.isArray(c.required) ||
    c.required.length > 4 ||
    new Set(c.required).size !== c.required.length ||
    c.required.length > k ||
    c.required.some((code) => !DEFAULT_PALETTE.some((c) => c.code === code))
  )
    throw Error("候选必选色无效（最多4色，计入颜色上限）");
  if (
    c.roi &&
    (!Array.isArray(c.roi) ||
      c.roi.length !== 4 ||
      !c.roi.every((n) => Number.isFinite(n) && n >= 0 && n <= 1) ||
      c.roi[2] <= c.roi[0] ||
      c.roi[3] <= c.roi[1])
  )
    throw Error("细节区域无效");
  if (
    c.weight !== undefined &&
    (!Number.isFinite(c.weight) || c.weight < 1 || c.weight > 4)
  )
    throw Error("区域权重须为1–4");
  return {
    required: [...c.required],
    ...(c.roi ? { roi: [...c.roi] as Constraints["roi"] } : {}),
    weight: c.weight ?? 3,
  };
}
// Same mean sampling and hue4 distance; only bounded palette-selection weights change.
export function generateConstrainedPattern(
  pixels: Uint8ClampedArray,
  w: number,
  h: number,
  mask: Uint8Array,
  n: number,
  k: number,
  input: Constraints,
): Pattern {
  const c = validateConstraints(input, k);
  if (!c.required.length && !c.roi)
    return generatePattern(pixels, w, h, mask, n, k);
  const grid = sampleGrid(pixels, w, h, mask, n),
    labs = DEFAULT_PALETTE.map((c) => srgbToOklab(hexRgb(c.hex)));
  const points = grid.values.map((v, i) => {
    const x =
        (grid.crop[0] +
          (((i % grid.width) + 0.5) * (grid.crop[2] - grid.crop[0])) /
            grid.width) /
        w,
      y =
        (grid.crop[1] +
          ((Math.floor(i / grid.width) + 0.5) * (grid.crop[3] - grid.crop[1])) /
            grid.height) /
        h;
    return v
      ? {
          dist: Float64Array.from(labs, (lab) =>
            hueDistanceSquared(srgbToOklab(v), lab),
          ),
          weight:
            c.roi &&
            x >= c.roi[0] &&
            x <= c.roi[2] &&
            y >= c.roi[1] &&
            y <= c.roi[3]
              ? c.weight!
              : 1,
        }
      : null;
  });
  const selected = c.required.map((code) =>
      DEFAULT_PALETTE.findIndex((c) => c.code === code),
    ),
    best = Float64Array.from(points, (p) =>
      p && selected.length
        ? Math.min(...selected.map((i) => p.dist[i]))
        : Infinity,
    );
  for (let round = selected.length; round < k; round++) {
    let candidate = -1,
      score = Infinity,
      current = 0;
    for (let i = 0; i < points.length; i++)
      if (points[i]) current += best[i] * points[i]!.weight;
    for (let j = 0; j < labs.length; j++) {
      if (selected.includes(j)) continue;
      let sum = 0;
      for (let i = 0; i < points.length; i++)
        if (points[i])
          sum += Math.min(best[i], points[i]!.dist[j]) * points[i]!.weight;
      if (sum < score) {
        score = sum;
        candidate = j;
      }
    }
    if (candidate < 0 || score >= current - 1e-15) break;
    selected.push(candidate);
    for (let i = 0; i < points.length; i++)
      if (points[i]) best[i] = Math.min(best[i], points[i]!.dist[candidate]);
  }
  const cells = points.map((p) => {
      if (!p) return null;
      let best = selected[0];
      for (const j of selected) if (p.dist[j] < p.dist[best]) best = j;
      return DEFAULT_PALETTE[best].code;
    }),
    used = new Set(cells);
  return {
    width: grid.width,
    height: grid.height,
    cells,
    palette: selected
      .map((i) => DEFAULT_PALETTE[i])
      .filter((v) => used.has(v.code) || c.required.includes(v.code)),
    colorLimit: k,
    paletteName: DEFAULT_PALETTE_NAME,
    paletteInfo: { ...DEFAULT_PALETTE_INFO },
    algorithm: CONSTRAINED_ALGORITHM,
    sampling: "mean",
    constraints: c,
  };
}
