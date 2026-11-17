<script setup lang="ts">
import { computed, ref, watch } from "vue";
const props = defineProps<{ source: string; modelValue: number[] }>();
const emit = defineEmits<{ 'update:modelValue': [number[]] }>();
const surface = ref<HTMLDivElement>();
const preview = ref<number[]>();
let pointer: number | undefined, start: [number, number] | undefined;
const rect = computed(() => {
  const r = preview.value ?? props.modelValue;
  return r.length === 4 && r.every(n => Number.isFinite(n) && n >= 0 && n <= 1) && r[2] > r[0] && r[3] > r[1] ? r : undefined;
});
function point(e: PointerEvent): [number, number] {
  const r = surface.value!.getBoundingClientRect();
  return [Math.max(0, Math.min(1, (e.clientX-r.left)/r.width)), Math.max(0, Math.min(1, (e.clientY-r.top)/r.height))];
}
function down(e: PointerEvent) {
  if (!e.isPrimary || e.button !== 0 || pointer !== undefined) return;
  pointer = e.pointerId;
  start = point(e);
  surface.value!.setPointerCapture(pointer);
  preview.value = [...start, ...start];
}
function move(e: PointerEvent) {
  if (e.pointerId !== pointer || !start) return;
  const p = point(e);
  preview.value = [Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.max(start[0],p[0]),Math.max(start[1],p[1])];
}
function end(e?: PointerEvent, commit = false) {
  if (e && e.pointerId !== pointer) return;
  const id = pointer, r = preview.value;
  pointer = undefined;
  start = undefined;
  preview.value = undefined;
  if (id !== undefined && surface.value?.hasPointerCapture(id)) surface.value.releasePointerCapture(id);
  if (commit && r && r[2]-r[0] >= .005 && r[3]-r[1] >= .005) emit('update:modelValue', r.map(n => Math.round(n*1000)/1000));
}
function up(e: PointerEvent) { move(e); end(e,true); }
watch(() => props.source, () => end());
</script>
<template>
  <figure class="region-picker">
    <div ref="surface" class="region-surface" @pointerdown.prevent="down" @pointermove="move" @pointerup="up" @pointercancel="end($event)" @lostpointercapture="end($event)">
      <img :src="source" alt="细节区域参考图；拖动框选，也可使用下方坐标输入" draggable="false" />
      <div v-if="rect" class="region-box" :style="{left:rect[0]*100+'%',top:rect[1]*100+'%',width:(rect[2]-rect[0])*100+'%',height:(rect[3]-rect[1])*100+'%'}"></div>
    </div>
    <figcaption>拖动框选，确认后应用</figcaption>
  </figure>
</template>
<style scoped>
.region-picker{margin:12px 0}.region-surface{display:inline-block;position:relative;max-width:100%;touch-action:none;cursor:crosshair;line-height:0;background:#fff}.region-surface img{display:block;max-width:100%;max-height:280px;pointer-events:none}.region-box{position:absolute;border:2px solid #9b3c91;background:#a74a991a;pointer-events:none}.region-picker figcaption{font-size:12px;color:#596d61;margin-top:5px}
</style>
