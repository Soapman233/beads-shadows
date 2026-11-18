import { stats, type Pattern } from "./engine";
export function paint(
  c: HTMLCanvasElement,
  p: Pattern,
  size = 14,
  exporting = false,
  name = "",
) {
  const margin = exporting ? 30 : 0,
    used = stats(p.cells),
    legend = exporting ? 104 + Math.ceil(p.palette.length / 4) * 28 : 0;
  c.width = p.width * size + margin * 2;
  c.height = p.height * size + margin * 2 + legend;
  const colors = new Map(p.palette.map((c) => [c.code, c]));
  const x = c.getContext("2d")!;
  x.fillStyle = "white";
  x.fillRect(0, 0, c.width, c.height);
  for (let j = 0; j < p.height; j++)
    for (let i = 0; i < p.width; i++) {
      const code = p.cells[j * p.width + i],
        col = colors.get(code ?? ""),
        xx = margin + i * size,
        yy = margin + j * size;
      x.fillStyle = col?.hex ?? "#edf0ea";
      x.fillRect(xx, yy, size, size);
      if (size >= 10) {
        x.strokeStyle = "#0002";
        x.lineWidth = 0.5;
        x.strokeRect(xx, yy, size, size);
      }
      if (exporting && col) {
        const h = col.hex;
        x.fillStyle =
          parseInt(h.slice(1, 3), 16) * 0.299 +
            parseInt(h.slice(3, 5), 16) * 0.587 +
            parseInt(h.slice(5), 16) * 0.114 >
          145
            ? "#15201c"
            : "white";
        x.font = "10px sans-serif";
        x.textAlign = "center";
        x.fillText(code!, xx + size / 2, yy + 19, size - 2);
      }
    }
  if (exporting) {
    x.font = "10px sans-serif";
    x.fillStyle = "#20372e";
    x.textAlign = "center";
    for (let i = 0; i < p.width; i++)
      x.fillText(String(i + 1), margin + i * size + size / 2, 18);
    for (let j = 0; j < p.height; j++)
      x.fillText(String(j + 1), 14, margin + j * size + 20);
    x.strokeStyle = "#344e43";
    x.lineWidth = 1.5;
    for (let i = 0; i <= p.width; i += 5) {
      x.beginPath();
      x.moveTo(margin + i * size, margin);
      x.lineTo(margin + i * size, margin + p.height * size);
      x.stroke();
    }
    for (let j = 0; j <= p.height; j += 5) {
      x.beginPath();
      x.moveTo(margin, margin + j * size);
      x.lineTo(margin + p.width * size, margin + j * size);
      x.stroke();
    }
    x.textAlign = "left";
    x.font = "14px sans-serif";
    x.fillText(
      `${name} | ${p.width} x ${p.height} | ${used.total} beads | ${Object.keys(used.counts).length} colors | ${p.paletteName}`,
      15,
      margin * 2 + p.height * size + 25,
    );
    x.fillText(
      p.paletteInfo?.version ?? "",
      15,
      margin * 2 + p.height * size + 46,
      c.width - 30,
    );
    p.palette.forEach((col, i) => {
      const xx = ((i % 4) * c.width) / 4 + 15,
        yy = margin * 2 + p.height * size + 79 + Math.floor(i / 4) * 28;
      x.fillStyle = col.hex;
      x.fillRect(xx, yy - 12, 14, 14);
      x.fillStyle = "#20372e";
      x.fillText(`${col.code} x ${used.counts[col.code] ?? 0}`, xx + 20, yy);
    });
  }
}
