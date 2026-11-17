import { generateConstrainedPattern } from "./constraints";
import {
  generateCandidates,
  generatePattern,
  generateRefinedPattern,
  DEFAULT_PALETTE,
} from "./engine";
self.onmessage = ({ data: v }) => {
  try {
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
              DEFAULT_PALETTE,
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
                DEFAULT_PALETTE,
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
                ),
              },
            ])
        : generateCandidates(pixels, v.width, v.height, mask);
    self.postMessage({ id: v.id, result });
  } catch (e) {
    self.postMessage({ id: v.id, error: (e as Error).message });
  }
};
