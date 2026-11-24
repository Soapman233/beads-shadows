<script setup lang="ts">
import { ref, watchEffect } from "vue";
import type { Pattern } from "./engine";

const props = defineProps<{
  pattern: Pick<Pattern, "width" | "height" | "palette" | "cells">;
  highlight?: string;
  blockSize?: number;
  selected?: { x: number; y: number };
}>();
const canvas = ref<HTMLCanvasElement>();
const emit = defineEmits<{ cell: [index: number]; inspect: [index: number] }>();
const coordinate = ref("");
const cellSize = 10;
watchEffect(() => {
  const view = canvas.value, { width, height, palette, cells } = props.pattern;
  if (!view) return;
  const ctx = view.getContext("2d")!;
  const swatches = new Map(palette.map(c => [c.code, c.hex]));
  view.width = width * cellSize;
  view.height = height * cellSize;
  ctx.fillStyle = "#e9efeb";
  ctx.fillRect(0, 0, view.width, view.height);
  cells.forEach((code, i) => {
    if (code === null) return;
    ctx.fillStyle = props.highlight && code !== props.highlight ? "#edf0ee" : swatches.get(code) ?? "#fff";
    ctx.fillRect(i % width * cellSize, Math.floor(i / width) * cellSize, cellSize, cellSize);
  });
  const size = props.blockSize ? props.blockSize * cellSize : 0;
  if (size) {
    ctx.strokeStyle = "#416256";
    ctx.lineWidth = 2;
    for (let x = 0; x < view.width; x += size) ctx.strokeRect(x, 0, size, view.height);
    for (let y = 0; y < view.height; y += size) ctx.strokeRect(0, y, view.width, size);
    if (props.selected) {
      ctx.strokeStyle = "#da6e28"; ctx.lineWidth = 5;
      ctx.strokeRect(props.selected.x * size + 2, props.selected.y * size + 2, size - 4, size - 4);
    }
  }
});
function inspectCell(event: PointerEvent) {
  const box = canvas.value!.getBoundingClientRect(), { width, height, cells } = props.pattern;
  if (!box.width || !box.height) return;
  const col = Math.max(0, Math.min(width - 1, Math.floor((event.clientX - box.left) / box.width * width)));
  const row = Math.max(0, Math.min(height - 1, Math.floor((event.clientY - box.top) / box.height * height)));
  const index = row * width + col;
  coordinate.value = `${row + 1} 行 · ${col + 1} 列 · ${cells[index] ?? "空格"}`;
  if (event.type === "pointerdown") emit("cell", index);
  else emit("inspect", index);
}
</script>
<template>
  <figure class="workshop-pattern">
    <canvas ref="canvas" aria-label="拼豆图纸预览" role="img" @pointermove="inspectCell" @pointerdown="inspectCell" />
    <figcaption>{{ coordinate || `${pattern.width} × ${pattern.height} 格` }}</figcaption>
  </figure>
</template>
<style scoped>
.workshop-pattern{margin:.75rem 0;text-align:center}
canvas{max-width:100%;max-height:55vh;object-fit:contain;image-rendering:pixelated}
</style>
