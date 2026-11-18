<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
const props = defineProps<{ source: string; busy: boolean }>();
const emit = defineEmits<{ adopt: [file: File] }>();
const kind = ref('人像'), file = ref<File>(), preview = ref(''), message = ref('');
const available = ref(false), consent = ref(false), aiBusy = ref(false);
const controller = new AbortController();
let disposed = false;
onMounted(async () => {
  try { const r = await fetch('/api/ai/capabilities', { signal: controller.signal });
    if (r.ok) available.value = (await r.json()).available === true;
  } catch { /* Offline image import remains available. */ }
});
async function generate() {
  if (!consent.value || aiBusy.value || props.busy || !available.value) return;
  aiBusy.value = true; message.value = '正在重绘，请勿重复提交';
  const source = props.source;
  try {
    const r = await fetch('/api/ai/pixel-art', { method: 'POST', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image: source, prompt: prompt.value, consent: true }) });
    const data = await r.json();
    if (!r.ok) throw Error(typeof data.detail === 'string' ? data.detail : 'AI请求失败');
    if (disposed || source !== props.source) return;
    if (typeof data.image !== 'string' || !data.image.startsWith('data:image/png;base64,')) throw Error('AI结果格式无效');
    const blob = await (await fetch(data.image)).blob();
    if (preview.value) URL.revokeObjectURL(preview.value);
    file.value = new File([blob], 'bailian-pixel-art.png', { type: 'image/png' });
    preview.value = URL.createObjectURL(file.value); message.value = '检查预览后再采用；AI可能改变细节';
  } catch (e) { if (!disposed) message.value = (e as Error).message; }
  finally { aiBusy.value = false; }
}
const prompt = computed(() => `将参考照片中的${kind.value}重绘为适合拼豆的像素画。保留主体身份特征、服饰、姿势与主体数量，不增加人物或物品。简化背景为透明背景，主体白色区域必须保留为不透明。使用清晰轮廓和大色块，减少细碎孤立像素、渐变和抗锯齿。不得添加文字、水印、网格、色号或材料表。输出完整主体PNG。最终网格和拼豆色卡由后续软件处理。`);
function select(e: Event) {
  const input = e.target as HTMLInputElement, next = input.files?.[0];
  input.value = '';
  if (!next) return;
  if (!['image/png', 'image/jpeg'].includes(next.type) || next.size > 20 * 1024 * 1024) { message.value = '请选择20MB以内的PNG或JPG'; return; }
  if (preview.value) URL.revokeObjectURL(preview.value);
  file.value = next; preview.value = URL.createObjectURL(next); message.value = '';
}
async function copy() {
  try { await navigator.clipboard.writeText(prompt.value); message.value = '已复制'; }
  catch { message.value = '请展开提示词手动复制'; }
}
onBeforeUnmount(() => { disposed = true; controller.abort(); if (preview.value) URL.revokeObjectURL(preview.value); });
</script>
<template>
  <details class="pixel-import panel">
    <summary>照片 → 像素画 → 图纸</summary>
    <p>采用后另存项目，原项目保留。{{ available ? '百炼 Qwen-Image-Edit-Plus' : '百炼未配置，可导入外部像素画。' }}</p>
    <div v-if="available">
      <label><input v-model="consent" type="checkbox" :disabled="aiBusy" />同意上传当前照片至百炼，可能产生费用</label>
      <button :disabled="!consent || busy || aiBusy" @click="generate">{{ aiBusy ? '重绘中…' : 'AI重绘' }}</button>
      <small v-if="aiBusy">离开页面不会取消服务端生成或费用。</small>
    </div>
    <div class="tools">
      <label>主体 <select v-model="kind"><option>人像</option><option>宠物</option><option>双人</option></select></label>
      <button :disabled="busy" @click="copy">复制重绘提示词</button>
      <label class="upload">导入像素画<input aria-label="导入像素画" type="file" accept="image/png,image/jpeg" :disabled="busy || aiBusy" @change="select" /></label>
    </div>
    <div class="pixel-comparison">
      <figure><figcaption>原图</figcaption><img :src="source" alt="原照片" /></figure>
      <figure><figcaption>像素画</figcaption><img v-if="preview" :src="preview" alt="待采用的像素画" @error="file = undefined; message = '图片无法预览，请重新选择'" /><p v-else>尚未导入</p></figure>
    </div>
    <button class="primary" :disabled="busy || aiBusy || !file" @click="file && emit('adopt', file)">另存并生成图纸</button>
    <span role="status">{{ message }}</span>
    <details><summary>重绘提示词</summary><textarea readonly :value="prompt" aria-label="重绘提示词" /></details>
  </details>
</template>
<style scoped>
.pixel-import{padding:16px;margin:0 0 20px}.pixel-import>summary{cursor:pointer;font-weight:600}.tools{padding:8px 0;flex-wrap:wrap;align-items:center}.pixel-comparison{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:12px 0}.pixel-comparison figure{margin:0;text-align:center;background:#fff;border-radius:8px;padding:10px}.pixel-comparison img{width:100%;height:260px;object-fit:contain}.pixel-import textarea{width:100%;min-height:110px}.pixel-import p,.pixel-import>span{font-size:12px;color:#627464}.pixel-import>details{margin-top:10px}
</style>
