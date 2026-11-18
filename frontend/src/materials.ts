import { stats, type Pattern } from "./engine";
function csv(v: unknown) {
  let s = String(v ?? "");
  if (/^[\s]*[=+@-]/.test(s)) s = "'" + s;
  return '"' + s.replaceAll('"', '""') + '"';
}
export function materialsCSV(p: Pattern, extra = 0, name = "图纸") {
  const { counts, total } = stats(p.cells);
  return (
    "\uFEFF" +
    [
      [
        "项目",
        "网格",
        "总豆数",
        "实际色数",
        "色卡",
        "版本",
        "色号",
        "HEX",
        "实际数量",
        "建议备料数量",
      ],
      ...p.palette
        .filter((c) => counts[c.code])
        .map((c) => [
          name,
          `${p.width}×${p.height}`,
          total,
          Object.keys(counts).length,
          p.paletteName,
          p.paletteInfo?.version ?? "",
          c.code,
          c.hex,
          counts[c.code],
          Math.ceil(
            counts[c.code] *
              (1 +
                (Number.isFinite(extra)
                  ? Math.max(0, Math.min(100, extra))
                  : 0) /
                  100),
          ),
        ]),
    ]
      .map((r) => r.map(csv).join(","))
      .join("\r\n")
  );
}
export function printBlocks(p: Pattern, size: number) {
  if (!Number.isInteger(size) || size < 8 || size > 64)
    throw Error("分块格数无效");
  const blocks = [];
  for (let y = 0; y < p.height; y += size)
    for (let x = 0; x < p.width; x += size)
      blocks.push({
        x,
        y,
        width: Math.min(size, p.width - x),
        height: Math.min(size, p.height - y),
      });
  return blocks;
}
