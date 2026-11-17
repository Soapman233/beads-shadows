<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from "vue";
import type { Pattern } from "./engine";
type Point = { x: number; y: number };
type Selection = [number, number, number, number];
const props = defineProps<{ pattern: Pattern; chosen: string | null }>();
const emit = defineEmits<{
  stroke: [cells: (string | null)[]];
  pick: [code: string | null];
  selection: [rect: Selection | null];
}>();
const canvas = ref<HTMLCanvasElement>(),
  stage = ref<HTMLDivElement>();
const zoom = ref(1),
  tool = ref("brush"),
  highlight = ref(""),
  selection = ref<Selection | null>(null);
let working: (string | null)[] | undefined,
  last: Point | undefined,
  anchor: Point | undefined;
let pan: number[] | undefined, pointer: number | undefined;
function draw() {
  const c = canvas.value;
  if (!c) return;
  const p = props.pattern;
  c.width = p.width * 14;
  c.height = p.height * 14;
  const ctx = c.getContext("2d")!,
    cells = working ?? p.cells,
    colors = new Map(p.palette.map((v) => [v.code, v.hex]));
  for (let i = 0; i < cells.length; i++) {
    ctx.globalAlpha =
      highlight.value && cells[i] !== highlight.value ? 0.25 : 1;
    ctx.fillStyle = colors.get(cells[i] ?? "") ?? "#edf0ea";
    ctx.fillRect((i % p.width) * 14, Math.floor(i / p.width) * 14, 14, 14);
    ctx.strokeStyle = "#0002";
    ctx.strokeRect((i % p.width) * 14, Math.floor(i / p.width) * 14, 14, 14);
  }
  ctx.globalAlpha = 1;
  if (selection.value) {
    const [x0, y0, x1, y1] = selection.value;
    ctx.strokeStyle = "#d96b00";
    ctx.lineWidth = 2;
    ctx.strokeRect(
      x0 * 14 + 1,
      y0 * 14 + 1,
      (x1 - x0 + 1) * 14 - 2,
      (y1 - y0 + 1) * 14 - 2,
    );
  }
}
function pos(e: PointerEvent): Point | null {
  const rect = canvas.value!.getBoundingClientRect();
  if (
    !rect.width ||
    !rect.height ||
    e.clientX < rect.left ||
    e.clientX >= rect.right ||
    e.clientY < rect.top ||
    e.clientY >= rect.bottom
  )
    return null;
  return {
    x: Math.floor(((e.clientX - rect.left) * props.pattern.width) / rect.width),
    y: Math.floor(
      ((e.clientY - rect.top) * props.pattern.height) / rect.height,
    ),
  };
}
function paint(e: PointerEvent) {
  const p = pos(e);
  if (!p) {
    last = undefined;
    return;
  }
  const a = last ?? p,
    n = Math.max(Math.abs(p.x - a.x), Math.abs(p.y - a.y), 1);
  for (let i = 0; i <= n; i++) {
    const x = Math.round(a.x + ((p.x - a.x) * i) / n),
      y = Math.round(a.y + ((p.y - a.y) * i) / n);
    working![y * props.pattern.width + x] = props.chosen;
  }
  last = p;
  draw();
}
function end(commit = false) {
  const cells = working,
    id = pointer;
  working = undefined;
  last = undefined;
  pan = undefined;
  anchor = undefined;
  pointer = undefined;
  if (id !== undefined && canvas.value?.hasPointerCapture(id))
    canvas.value.releasePointerCapture(id);
  if (commit && cells && cells.some((v, i) => v !== props.pattern.cells[i]))
    emit("stroke", cells);
  draw();
}
function down(e: PointerEvent) {
  if (!e.isPrimary || e.button !== 0 || pointer !== undefined) return;
  const p = pos(e);
  if (!p) return;
  if (tool.value === "pick") {
    emit("pick", props.pattern.cells[p.y * props.pattern.width + p.x]);
    tool.value = "brush";
    return;
  }
  pointer = e.pointerId;
  canvas.value!.setPointerCapture(pointer);
  if (tool.value === "pan")
    pan = [
      e.clientX,
      e.clientY,
      stage.value!.scrollLeft,
      stage.value!.scrollTop,
    ];
  else if (tool.value === "select") {
    anchor = p;
    selection.value = [p.x, p.y, p.x, p.y];
    emit("selection", selection.value);
    draw();
  } else {
    working = props.pattern.cells.slice();
    paint(e);
  }
}
function move(e: PointerEvent) {
  if (e.pointerId !== pointer) return;
  if (pan) {
    stage.value!.scrollLeft = pan[2] + pan[0] - e.clientX;
    stage.value!.scrollTop = pan[3] + pan[1] - e.clientY;
  } else if (anchor) {
    const p = pos(e);
    if (p) {
      selection.value = [
        Math.min(anchor.x, p.x),
        Math.min(anchor.y, p.y),
        Math.max(anchor.x, p.x),
        Math.max(anchor.y, p.y),
      ];
      emit("selection", selection.value);
      draw();
    }
  } else if (working) paint(e);
}
function up(e: PointerEvent) {
  if (e.pointerId === pointer) end(true);
}
function cancel(e: PointerEvent) {
  if (e.pointerId === pointer) end();
}
function clearSelection() {
  selection.value = null;
  emit("selection", null);
  draw();
}
function fit() {
  const el = stage.value;
  if (!el) return;
  zoom.value = Math.max(
    0.25,
    Math.min(
      1,
      (el.clientWidth - 32) / (props.pattern.width * 14),
      (Math.min(el.clientHeight, 600) - 32) / (props.pattern.height * 14),
    ),
  );
  el.scrollTop = 0;
  el.scrollLeft = 0;
}
watch(tool, () => end());
watch(
  () => props.pattern,
  () => {
    end();
    void nextTick(draw);
  },
  { deep: true },
);
watch(() => [props.pattern.width, props.pattern.height], clearSelection);
watch(highlight, draw);
onMounted(draw);
onBeforeUnmount(() => end());
</script>
<template>
  <div>
    <div class="grid-tools">
      <button aria-label="缩小" @click="zoom = Math.max(0.25, zoom - 0.25)">
        −</button
      ><span>{{ Math.round(zoom * 100) }}%</span
      ><button aria-label="放大" @click="zoom = Math.min(4, zoom + 0.25)">
        ＋</button
      ><button @click="fit">适应</button><button @click="zoom = 1">100%</button>
      <button
        v-for="[id, label] in [
          ['brush', '画笔'],
          ['pan', '移动'],
          ['pick', '吸色'],
          ['select', '选区'],
        ]"
        :key="id"
        :class="{ active: tool === id }"
        @click="tool = id"
      >
        {{ label }}
      </button>
      <button v-if="selection" @click="clearSelection">清除选区</button
      ><span v-if="selection"
        >行 {{ selection[1] + 1 }}–{{ selection[3] + 1 }} · 列
        {{ selection[0] + 1 }}–{{ selection[2] + 1 }} ·
        {{
          (selection[2] - selection[0] + 1) * (selection[3] - selection[1] + 1)
        }}
        格</span
      >
      <select v-model="highlight" aria-label="高亮颜色">
        <option value="">全部颜色</option>
        <option v-for="c in pattern.palette" :key="c.code" :value="c.code">
          {{ c.code }}
        </option>
      </select>
    </div>
    <div class="grid-scroll" ref="stage">
      <canvas
        ref="canvas"
        aria-label="图纸编辑画布"
        :style="{
          width: pattern.width * 14 * zoom + 'px',
          height: pattern.height * 14 * zoom + 'px',
          touchAction: 'none',
        }"
        @pointerdown="down"
        @pointermove="move"
        @pointerup="up"
        @pointercancel="cancel"
        @lostpointercapture="cancel"
      />
    </div>
  </div>
</template>
