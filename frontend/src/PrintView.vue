<script setup lang="ts">
import { computed, ref } from "vue";
import { stats, type Pattern } from "./engine";
import { printBlocks } from "./materials";
const props = defineProps<{ pattern: Pattern; size: number; name?: string }>();
defineEmits<{ close: [] }>();
const monochrome = ref(true);
const blocks = computed(() => printBlocks(props.pattern, props.size));
const counts = computed(() => stats(props.pattern.cells));
const colors = computed(
  () => new Map(props.pattern.palette.map((c) => [c.code, c.hex])),
);
const used = computed(() =>
  props.pattern.palette.filter((c) => counts.value.counts[c.code]),
);
const symbols = computed(
  () => new Map(used.value.map((c, i) => [c.code, String(i + 1)])),
);
const color = (c: string | null) =>
  c ? (colors.value.get(c) ?? "#fff") : "#fff";
const foreground = (hex: string) =>
  parseInt(hex.slice(1, 3), 16) * 0.299 +
    parseInt(hex.slice(3, 5), 16) * 0.587 +
    parseInt(hex.slice(5), 16) * 0.114 >
  145
    ? "#111"
    : "#fff";
const cell = (x: number, y: number) =>
  props.pattern.cells[y * props.pattern.width + x];
function print() {
  window.print();
}
</script>
<template>
  <div class="print-view">
    <div class="no-print">
      <button @click="print">打印 / 保存 PDF</button
      ><button @click="$emit('close')">关闭</button
      ><label><input type="checkbox" v-model="monochrome" />黑白符号</label>
      <p>数字为豆色；× 为空格。按格制作，核对实物钉距。</p>
    </div>
    <section class="print-page">
      <h2>{{ name || "图纸" }} · 总览</h2>
      <p>
        {{ pattern.width }} × {{ pattern.height }} · {{ counts.total }} 颗 ·
        {{ used.length }} 色 · {{ blocks.length }} 块 · 第 1 /
        {{ blocks.length + 1 }} 页
      </p>
      <p class="version">
        {{ pattern.paletteName }} · {{ pattern.paletteInfo?.version }}
      </p>
      <svg
        :viewBox="`-.5 -.5 ${pattern.width + 1} ${pattern.height + 1}`"
        class="print-overview"
      >
        <rect
          v-for="(c, i) in pattern.cells"
          :x="i % pattern.width"
          :y="Math.floor(i / pattern.width)"
          width="1"
          height="1"
          :fill="color(c)"
        />
        <g v-for="(b, i) in blocks">
          <rect
            :x="b.x"
            :y="b.y"
            :width="b.width"
            :height="b.height"
            fill="none"
            stroke="black"
            stroke-width=".3"
          />
          <text :x="b.x + 1" :y="b.y + 4" font-size="3">{{ i + 1 }}</text>
        </g>
      </svg>
      <p>拼接：先从左向右，再从上向下。× 为空格，不备豆。</p>
      <div class="print-legend">
        <span v-for="c in used"
          >{{ symbols.get(c.code) }} = {{ c.code }} ·
          {{ counts.counts[c.code] }} 颗</span
        >
      </div>
    </section>
    <section v-for="(b, index) in blocks" class="print-page">
      <h2>{{ name || "图纸" }} · 块 {{ index + 1 }} / {{ blocks.length }}</h2>
      <p>
        第 {{ index + 2 }} / {{ blocks.length + 1 }} 页 · 行 {{ b.y + 1 }}–{{
          b.y + b.height
        }}
        · 列 {{ b.x + 1 }}–{{ b.x + b.width }} · 左→右，上→下
      </p>
      <svg :viewBox="`-1 -1 ${size + 2} ${size + 2}`" class="print-block">
        <template v-for="row in b.height">
          <g v-for="col in b.width">
            <rect
              :x="col - 1"
              :y="row - 1"
              width="1"
              height="1"
              :fill="
                monochrome ? '#fff' : color(cell(b.x + col - 1, b.y + row - 1))
              "
              stroke="#888"
              stroke-width=".025"
            />
            <text
              :x="col - 0.5"
              :y="row - 0.32"
              font-size=".4"
              text-anchor="middle"
              :fill="
                monochrome
                  ? '#111'
                  : foreground(color(cell(b.x + col - 1, b.y + row - 1)))
              "
            >
              {{ symbols.get(cell(b.x + col - 1, b.y + row - 1) ?? "") ?? "×" }}
            </text>
          </g>
        </template>
        <text
          v-for="col in b.width"
          :x="col - 0.5"
          y="-.25"
          font-size=".28"
          text-anchor="middle"
        >
          {{ b.x + col }}
        </text>
        <text
          v-for="row in b.height"
          x="-.2"
          :y="row - 0.35"
          font-size=".28"
          text-anchor="end"
        >
          {{ b.y + row }}
        </text>
      </svg>
      <div class="print-legend">
        <span v-for="c in used">{{ symbols.get(c.code) }} = {{ c.code }}</span>
      </div>
    </section>
  </div>
</template>
<style scoped>
.print-view {
  position: fixed;
  inset: 0;
  background: white;
  z-index: 20;
  overflow: auto;
  padding: 24px;
  color: #111;
}
.print-page {
  width: 180mm;
  max-width: 100%;
  margin: 20px auto;
  break-after: page;
  box-sizing: border-box;
}
.print-page:last-child {
  break-after: auto;
}
.print-page h2 {
  font-size: 18px;
  margin: 0 0 8px;
}
.print-page p {
  font-size: 12px;
  margin: 6px 0;
}
.version {
  overflow-wrap: anywhere;
}
.print-block {
  width: 100%;
  height: 180mm;
}
.print-overview {
  display: block;
  height: 125mm;
  max-width: 100%;
  margin: auto;
}
.print-legend {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 4px;
  font-size: 10px;
  overflow-wrap: anywhere;
}
@media print {
  .no-print {
    display: none;
  }
  .print-view {
    position: static;
    overflow: visible;
    padding: 0;
  }
  .print-page {
    margin: 0;
    min-height: 0;
    break-inside: avoid;
  }
  .print-page:last-child {
    page-break-after: auto;
  }
}
</style>
<style>
@media print {
  html,
  body {
    background: white !important;
  }
}
@page {
  size: A4;
  margin: 12mm;
}
</style>
