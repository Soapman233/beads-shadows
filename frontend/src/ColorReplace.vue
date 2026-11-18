<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue";
import {
  getPatternPalette,
  planColorReplace,
  stats,
  type Pattern,
  type GridSelection,
} from "./engine";
const props = defineProps<{
  pattern: Pattern;
  locked: string[];
  selection?: GridSelection | null;
}>();
const emit = defineEmits<{ apply: [pattern: Pattern] }>();
const scope = ref("all");
const from = ref(""),
  to = ref(""),
  query = ref(""),
  before = ref<HTMLCanvasElement>(),
  after = ref<HTMLCanvasElement>();
const reference = computed(() => getPatternPalette(props.pattern));
const compatible = computed(() => !!reference.value);
const counts = computed(() => stats(props.pattern.cells).counts);
const used = computed(() =>
  props.pattern.palette.filter((c) => counts.value[c.code]),
);
const options = computed(() =>
  (reference.value?.colors ?? []).filter((c) =>
    c.code.toLowerCase().includes(query.value.trim().toLowerCase()),
  ),
);
const sourceColor = computed(() =>
  props.pattern.palette.find((c) => c.code === from.value),
);
const targetColor = computed(() =>
  reference.value?.colors.find((c) => c.code === to.value),
);
const result = computed(() => {
  if (scope.value === "selection" && !props.selection)
    return { message: "先在图纸上框选范围" };
  if (!from.value || !to.value) return { message: "选择替代色" };
  try {
    return {
      plan: planColorReplace(
        props.pattern,
        from.value,
        to.value,
        props.locked,
        scope.value === "selection"
          ? (props.selection ?? undefined)
          : undefined,
      ),
      message: "",
    };
  } catch (e) {
    return { message: (e as Error).message };
  }
});
function draw(canvas: HTMLCanvasElement | undefined, p: Pattern) {
  if (!canvas) return;
  canvas.width = p.width * 5;
  canvas.height = p.height * 5;
  const ctx = canvas.getContext("2d")!,
    colors = new Map(p.palette.map((c) => [c.code, c.hex]));
  for (let i = 0; i < p.cells.length; i++) {
    ctx.fillStyle = colors.get(p.cells[i] ?? "") ?? "#edf0ea";
    ctx.fillRect((i % p.width) * 5, Math.floor(i / p.width) * 5, 5, 5);
  }
}
watch(
  () => [props.pattern, props.locked],
  () => {
    from.value = used.value.some((c) => c.code === from.value)
      ? from.value
      : (used.value[0]?.code ?? "");
    to.value = "";
  },
  { deep: true, immediate: true },
);
watch(result, async () => {
  await nextTick();
  draw(before.value, props.pattern);
  if (result.value.plan) draw(after.value, result.value.plan.pattern);
});
function apply() {
  if (result.value.plan) emit("apply", result.value.plan.pattern);
}
</script>
<template>
  <details class="replace-panel">
    <summary>替换颜色</summary>
    <label
      >范围
      <select v-model="scope" aria-label="替换范围">
        <option value="all">全图</option>
        <option value="selection">选区</option>
      </select></label
    >
    <p v-if="!compatible">此项目色卡不兼容，无法整色替换。</p>
    <template v-else>
      <label
        >原色
        <select v-model="from" aria-label="原色">
          <option v-for="c in used" :key="c.code" :value="c.code">
            {{ c.code }} · {{ counts[c.code] }} 颗{{
              locked.includes(c.code) ? " · 已锁" : ""
            }}
          </option>
        </select></label
      >
      <label class="replace-search"
        >替代色
        <input v-model="query" aria-label="替代色" placeholder="搜索色号"
      /></label>
      <p>{{ reference?.name }} · {{ reference?.colors.length }} 色</p>
      <div class="replace-swatches" role="group" aria-label="参考色卡">
        <button
          v-for="c in options"
          :key="c.code"
          :class="{ active: to === c.code }"
          :aria-label="'替代色 ' + c.code + ' ' + c.hex"
          :aria-pressed="to === c.code"
          @click="to = c.code"
        >
          <i :style="{ background: c.hex }"></i>{{ c.code }}
        </button>
      </div>
      <p v-if="!options.length">无匹配色号</p>
      <p v-if="sourceColor && targetColor" class="replace-pair">
        <i :style="{ background: sourceColor.hex }"></i>{{ sourceColor.code }}
        {{ sourceColor.hex }} → <i :style="{ background: targetColor.hex }"></i
        >{{ targetColor.code }} {{ targetColor.hex }}
      </p>
      <p v-if="result.message" role="status">{{ result.message }}</p>
      <div v-if="result.plan">
        <div class="replace-comparison">
          <div><b>当前图纸</b><canvas ref="before"></canvas></div>
          <div><b>预览</b><canvas ref="after"></canvas></div>
        </div>
        <p>
          影响 {{ result.plan.affected }} 格 · 豆数
          {{ stats(pattern.cells).total }} →
          {{ stats(result.plan.pattern.cells).total }} · 色数
          {{ Object.keys(counts).length }} →
          {{ Object.keys(stats(result.plan.pattern.cells).counts).length }}
        </p>
        <button class="primary" @click="apply">应用替换</button>
        <button @click="to = ''">取消</button>
      </div>
    </template>
  </details>
</template>
