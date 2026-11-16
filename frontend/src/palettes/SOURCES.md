# MARD classic reference palette

Retrieved 2026-11-15 from the upstream community repository:

- Data: https://github.com/maxcleme/beadcolors/blob/master/raw/mard.csv
- License: https://github.com/maxcleme/beadcolors/blob/master/LICENSE
- Repository explanation: https://github.com/maxcleme/beadcolors

`mard-source.csv` preserves the downloaded data. It has no header; columns are reference code, name, red, green, blue, contributor. The upstream dataset is community maintained, not a manufacturer's certified physical measurement. The MIT license and copyright notice are included in `LICENSE-beadcolors.txt`.

`mard.ts` was generated from A–H and M code families in the source, retaining their code/name and converting the three RGB channels to HEX. This is the 221-code classic subset, with H1 excluded by the existing MVP subset policy. That leaves 220 active entries. Correction (2026-11-16): the source has H1 RGB (226,226,226) but no material or alpha field; the previous claim that H1 is transparent was unsupported. We retain the same subset for comparison continuity, not as a claim about its physical material. Extended P/Q/R/T/Y/ZG effect families are not automatically matched.

Brand/series: MARD 221 classic reference system. Snapshot version: retrieval date 2026-11-15; no content hash was calculated. The original contributor column is kept in the source. Names in this dataset are the code itself rather than localized color names. This integration does not claim latest manufacturer completeness, brand affiliation, exact screen-to-bead color matching, or that an actual physical project was assembled. Check important colors, bead size and codes against the purchased set before preparing materials.

The palette data is unchanged by color-v3/v4. The current v4 matcher uses Oklab lightness/chroma/hue decomposition with a product-specific hue weight of 4, discrete palette selection, and no dithering. Earlier RGB and unweighted Oklab matchers remain available for controlled diagnostics. None of these changes is physical color calibration; selected HEX values always come from the same reference entries.
