/** Original geometric fixture -> 32x32, K8 physical validation kit. No hashes. */
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve, join, dirname } from "node:path";
import { generatePattern, stats } from "../frontend/src/engine";
import { validateProject } from "../frontend/src/project";
import { materialsCSV } from "../frontend/src/materials";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(repo, "experiments/generated/synthetic-3.json");
if (!existsSync(source))
  throw Error(
    "Prepare existing synthetic fixtures first: python tests/prepare_experiments.py (see docs/experiments.md).",
  );
const input = JSON.parse(readFileSync(source, "utf8"));
const pattern = generatePattern(
  new Uint8ClampedArray(input.rgba),
  input.width,
  input.height,
  new Uint8Array(input.mask),
  32,
  8,
);
if (pattern.width !== 32 || pattern.height !== 32)
  throw Error("Expected square 32x32 fixture");
const project = validateProject({
  schemaVersion: 2,
  pattern,
  points: [],
  locked: [],
  step: 3,
  pitch: 2.6,
  selectionMode: "whole",
  selectionDirty: false,
  tuning: { width: 32, colors: 8 },
});
const counts = stats(pattern.cells),
  used = pattern.palette.filter((c) => counts.counts[c.code]);
const symbols = new Map(used.map((c, i) => [c.code, String(i + 1)]));
const colors = new Map(used.map((c) => [c.code, c.hex]));
const esc = (value: string) =>
  value.replace(
    /[&<>"']/g,
    (c) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&apos;",
      })[c]!,
  );
const cells = pattern.cells
  .map((code, i) => {
    const x = (i % 32) * 16 + 24,
      y = Math.floor(i / 32) * 16 + 24;
    if (code === null)
      return `<rect x="${x}" y="${y}" width="16" height="16" fill="white" stroke="#bbb" stroke-width=".4"/><path d="M${x + 5},${y + 5}l6,6m0,-6l-6,6" stroke="#666" stroke-width=".6"/>`;
    return `<rect x="${x}" y="${y}" width="16" height="16" fill="${colors.get(code)}" stroke="#333" stroke-width=".4"/><rect x="${x + 3}" y="${y + 2}" width="10" height="12" fill="white"/><text x="${x + 8}" y="${y + 11}" text-anchor="middle" font-size="10" fill="black">${symbols.get(code)}</text>`;
  })
  .join("");
const marks = Array.from(
  { length: 32 },
  (_, i) =>
    `<text x="${i * 16 + 32}" y="18" text-anchor="middle" font-size="6">${i + 1}</text><text x="18" y="${i * 16 + 35}" text-anchor="end" font-size="6">${i + 1}</text>`,
).join("");
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 548 548" width="160mm" height="160mm" role="img" aria-label="32x32 bead pattern"><rect width="548" height="548" fill="white"/><g font-family="sans-serif">${cells}${marks}</g></svg>`;
const legend = used
  .map(
    (c) =>
      `<tr><td>${symbols.get(c.code)}</td><td>${esc(c.code)}</td><td><span style="display:inline-block;width:10mm;height:3mm;border:1px solid #333;background:${c.hex}"></span> ${c.hex}</td><td>${counts.counts[c.code]}</td><td>${Math.ceil(counts.counts[c.code] * 1.1)}</td></tr>`,
  )
  .join("");
const html = `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>豆影 32×32 实物验证包</title><style>@page{size:A4;margin:12mm}*{box-sizing:border-box}body{font:10pt sans-serif;color:#111;margin:0}h1{font-size:15pt}p{margin:2mm 0}svg{display:block;width:160mm;height:160mm}table{border-collapse:collapse;font-size:9pt;width:160mm}td,th{border:1px solid #777;padding:1mm;text-align:left}section{break-inside:avoid}button{margin:4mm 0}@media print{button{display:none}}</style><h1>32 × 32 · 原创几何图</h1><p>${counts.total} 颗 · ${used.length} 色 · K上限8 · 从左上角开始，行向下、列向右</p><p>数字对应色号；×为空格；白色豆同样标数字。打印按格施工，非豆板1:1模板。</p><button onclick="window.print()">打印 / 保存 PDF</button>${svg}<section><table><thead><tr><th>符号</th><th>色号</th><th>屏幕参考</th><th>实际数量</th><th>备料+10%</th></tr></thead><tbody>${legend}</tbody></table><p>MARD · ${esc(pattern.paletteInfo?.version ?? "")}。采购前按实物确认色号和批次，屏幕参考不等于实物校色。</p></section></html>`;
const out = join(repo, "experiments/generated/human-kit");
mkdirSync(out, { recursive: true });
writeFileSync(
  join(out, "project-32x32.json"),
  JSON.stringify(project, null, 2),
);
writeFileSync(join(out, "materials-10percent.csv"), materialsCSV(pattern, 10));
writeFileSync(join(out, "pattern.svg"), svg);
writeFileSync(join(out, "print.html"), html);
writeFileSync(
  join(out, "record-template.md"),
  `# 实体制作记录（待本人填写）\n\n图纸：32×32，K8，${counts.total}颗，${used.length}色。\n\n|日期|拼豆品牌/批次|豆板钉距|打印缩放|制作耗时|缺豆/错色|实物观感与光源|\n|---|---|---|---|---|---|---|\n|待填写|||||||\n\n请附实物照片；不要将生成材料包写为完成实体验证。\n`,
);
console.log(
  JSON.stringify(
    {
      output: "experiments/generated/human-kit",
      grid: "32x32",
      beans: counts.total,
      colors: used.length,
      counts: counts.counts,
      physicalValidation: "pending",
    },
    null,
    2,
  ),
);
