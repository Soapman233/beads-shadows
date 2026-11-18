import { getPalette } from "./palettes/catalog";
import { generateConstrainedPattern } from "./constraints";
import {
  generateCandidates,
  generatePattern,
  generateRefinedPattern,
} from "./engine";
self.onmessage = ({ data: v }) => {
  try {
    const palette = getPalette(v.paletteId ?? "legacy-mard220");
    if (!palette?.available) throw Error("所选色卡当前不可用");
    const colors = palette.colors;
    const pixels = new Uint8ClampedArray(v.pixels),
      mask = new Uint8Array(v.mask);
    const result = v.constraints
      ? [
          {
            label: "默认（同条件）",
            pattern: generatePattern(
              pixels,
              v.width,
              v.height,
              mask,
              v.n,
              v.k,
              colors,
              "mean",
            ),
          },
          {
            label: "细节方案",
            pattern: generateConstrainedPattern(
              pixels,
              v.width,
              v.height,
              mask,
              v.n,
              v.k,
              v.constraints,
              colors,
            ),
          },
        ]
      : v.custom
        ? (["mean", "dominant"] as const)
            .map((sampling, i) => ({
              label: i ? "色块" : "平滑",
              pattern: generatePattern(
                pixels,
                v.width,
                v.height,
                mask,
                v.n,
                v.k,
                colors,
                sampling,
              ),
            }))
            .concat([
              {
                label: "优化候选",
                pattern: generateRefinedPattern(
                  pixels,
                  v.width,
                  v.height,
                  mask,
                  v.n,
                  v.k,
                  colors,
                ),
              },
            ])
        : generateCandidates(pixels, v.width, v.height, mask, colors);
    self.postMessage({ id: v.id, result: result.map(candidate => ({
      ...candidate,
      pattern: {...candidate.pattern, paletteId: palette.id, paletteName: palette.name, paletteInfo: {...palette.info}},
    })) });
  } catch (e) {
    self.postMessage({ id: v.id, error: (e as Error).message });
  }
};
