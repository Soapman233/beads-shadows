<script setup lang="ts">
import { computed, ref } from 'vue';
import { stats, type Pattern } from './engine';
const props = defineProps<{ pattern: Pattern; chosen: string | null; locked: string[] }>();
defineEmits<{ choose: [string | null]; lock: [string] }>();
const query = ref(''), order = ref('quantity');
const counts = computed(() => stats(props.pattern.cells).counts);
const colors = computed(() => {
  const q = query.value.trim().toLowerCase();
  return props.pattern.palette.filter(c => `${c.code} ${c.hex}`.toLowerCase().includes(q)).slice().sort((a,b) => order.value === 'quantity' ? (counts.value[b.code] ?? 0)-(counts.value[a.code] ?? 0) || a.code.localeCompare(b.code,undefined,{numeric:true}) : a.code.localeCompare(b.code,undefined,{numeric:true}));
});
const source = computed(() => props.pattern.paletteInfo?.source);
const safeSource = computed(() => source.value && /^https?:\/\//i.test(source.value) ? source.value : undefined);
</script>
<template>
  <aside class="colors palette-panel">
    <h3>颜色与用量 · {{ Object.keys(counts).length }} 色</h3>
    <input v-model="query" type="search" aria-label="查找已选色号或HEX" placeholder="色号 / HEX" />
    <select v-model="order" aria-label="颜色排序"><option value="quantity">用量优先</option><option value="code">色号顺序</option></select>
    <button :class="{selected:chosen === null}" @click="$emit('choose',null)">橡皮擦</button>
    <div class="palette-rows">
      <div v-for="c in colors" :key="c.code" class="color-row">
        <button :class="{selected:chosen === c.code}" :aria-pressed="chosen === c.code" :title="`${c.code} ${c.hex}`" @click="$emit('choose',c.code)"><i :style="{background:c.hex}"></i>{{ c.code }}<span>{{ counts[c.code] ?? 0 }} 颗</span></button>
        <button :aria-label="'锁定 '+c.code" :aria-pressed="locked.includes(c.code)" :class="{active:locked.includes(c.code)}" @click="$emit('lock',c.code)">{{ locked.includes(c.code) ? '已锁' : '锁色' }}</button>
      </div>
      <p v-if="!colors.length" role="status">没有匹配色号</p>
    </div>
    <details class="palette-source"><summary>色卡来源</summary><p>{{ pattern.paletteName }}</p><template v-if="pattern.paletteInfo"><p>{{ pattern.paletteInfo.version }}</p><a v-if="safeSource" :href="safeSource" target="_blank" rel="noopener noreferrer">查看数据来源</a><p v-else>{{ source }}</p><p>{{ pattern.paletteInfo.license }}</p><p>{{ pattern.paletteInfo.note }}</p></template><p v-else>导入项目未记录来源，沿用其原色值。</p></details>
  </aside>
</template>
<style scoped>
.palette-panel input,.palette-panel select{width:100%;min-width:0;margin-bottom:8px;padding:6px;border:1px solid #cbd7c7;border-radius:5px}.palette-rows{max-height:460px;overflow:auto}.palette-panel .color-row{gap:3px}.palette-panel .color-row button{gap:5px;white-space:nowrap}.palette-panel i{flex-shrink:0}.palette-source{font-size:11px;margin-top:12px;overflow-wrap:anywhere}.palette-source p{margin:6px 0}.palette-source summary{cursor:pointer}.palette-panel .color-row>button:first-child{min-width:0}
</style>
