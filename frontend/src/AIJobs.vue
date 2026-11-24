<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import type { SavedProject } from "./storage";
import { jsonRequest, platformApi, readAsset, type AccountSession } from "./platformApi";

type Job = { id: string; inputId: string; outputId: string | null; provider: string; status: string; error: string | null; createdAt: string };
const props = defineProps<{ session: AccountSession; snapshot: () => Promise<SavedProject>; adopt: (file: File) => Promise<boolean> }>();
const emit = defineEmits<{ close: [] }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>("/ai" + path, options, props.session);
const quota = ref({ remaining: 0, reserved: 0, used: 0 });
const jobs = ref<Job[]>([]), provider = ref<string>(), model = ref<string>(), kind = ref("人像");
const consent = ref(false), busy = ref(false), error = ref("");
const before = ref(""), after = ref(""), showJob = ref<Job>();
const statuses: Record<string, string> = { queued: "排队中", running: "处理中", cancel_requested: "已请求取消", succeeded: "已完成",
  failed: "失败", cancelled: "已取消", unknown: "待核对费用", billed: "已核对计费" };
type Pending = { id: string; inputId: string; prompt: string; provider: string; name: string };
const pendingKey = "bead-ai-pending:" + props.session.user?.id;
const pending = ref<Pending>();
try {
  const saved = sessionStorage.getItem(pendingKey);
  if (saved) pending.value = JSON.parse(saved) as Pending;
} catch {}
let timer: number | undefined;
let disposed = false;
async function refresh() {
  const [next, counts] = await Promise.all([call<{ items: Job[] }>("/jobs"), call<typeof quota.value>("/quota")]);
  jobs.value = next.items;
  quota.value = counts;
}
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); } catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}
onMounted(async () => {
  await work(async () => {
    const caps = await call<{ provider?: string; model?: string }>("/capabilities");
    provider.value = caps.provider; model.value = caps.model;
    await refresh();
  });
  if (!disposed) timer = window.setInterval(() => { if (!busy.value) void refresh().catch(() => {}); }, 3500);
});
onBeforeUnmount(() => { disposed = true; window.clearInterval(timer); });
async function create() {
  if (pending.value) throw Error("请先核对上一次提交");
  if (!provider.value || !consent.value) return;
  const currentProvider = provider.value;
  const row = await props.snapshot(), source = row.project.source;
  if (!source) throw Error("请在创作页导入原图");
  const prompt = `把参考照片中的${kind.value}绘成便于拼豆的像素画。保留主体数量、姿势和辨识特征，使用清晰轮廓和大色块。去掉背景杂物，保留主体中的白色区域。不要添加色号、文字、网格或水印。`;
  const blob = await (await fetch(source)).blob();
  if (blob.size > 10 * 1024 * 1024) throw Error("重绘参考图须小于 10MB");
  const form = new FormData();
  form.set("file", blob, "source.png"); form.set("kind", "source");
  const { id } = await platformApi<{ id: string }>("/assets", { method: "POST", body: form }, props.session);
  pending.value = { id: crypto.randomUUID(), inputId: id, prompt, provider: currentProvider, name: row.name };
  sessionStorage.setItem(pendingKey, JSON.stringify(pending.value));
  await retry();
}
function clearPending() {
  sessionStorage.removeItem(pendingKey);
  pending.value = undefined;
}
async function retry() {
  const request = pending.value;
  if (!request || !consent.value || provider.value !== request.provider) return;
  try {
    await call("/jobs", jsonRequest("POST", { assetId: request.inputId, requestId: request.id,
      prompt: request.prompt, provider: request.provider, consent: true }));
  } catch (e) {
    if ([400, 401, 403, 404, 409, 422, 429].includes((e as { status?: number }).status ?? 0)) clearPending();
    throw e;
  }
  clearPending(); consent.value = false;
  await refresh();
}
async function inspect(row: Job) {
  const [a, b] = await Promise.all([readAsset(row.inputId, props.session), readAsset(row.outputId, props.session)]);
  before.value = a ?? ""; after.value = b ?? ""; showJob.value = row;
}
async function adopt() {
  if (!after.value) return;
  const blob = await (await fetch(after.value)).blob();
  if (await props.adopt(new File([blob], "redraw.png", { type: "image/png" }))) emit("close");
  else throw Error("未能采用结果，请回到创作页查看提示");
}
</script>
<template>
  <section class="platform-panel panel">
    <h2>图片重绘</h2>
    <p v-if="!provider">服务未启用。可在创作页导入外部像素画。</p>
    <p v-else>{{ provider === "simulation" ? "本地模拟 · 仅验证任务流程" : "百炼 · " + model }}</p>
    <p>可用 {{ quota.remaining }} · 已预留 {{ quota.reserved }} · 已使用 {{ quota.used }}</p>
    <form v-if="provider" class="platform-tools" @submit.prevent="work(create)">
      <label>主体 <select v-model="kind"><option>人像</option><option>宠物</option><option>双人</option></select></label>
      <label><input v-model="consent" type="checkbox" required />{{ provider === "simulation" ? "使用本地样例处理" : "同意将当前原图发送至百炼，调用可能计费" }}</label>
      <button class="primary" :disabled="busy || !!pending || !quota.remaining || !consent">提交重绘</button>
    </form>
    <div v-if="pending" class="platform-tools">
      <span>待确认的提交 · {{ pending.name }} · {{ pending.provider }}</span>
      <button :disabled="busy || !consent || provider !== pending.provider" @click="work(retry)">重试同一请求</button>
      <button :disabled="busy" @click="clearPending">清除本机记录</button>
    </div>
    <div v-for="row in jobs" :key="row.id" class="platform-tools">
      <span>{{ new Date(row.createdAt).toLocaleString() }}</span>
      <strong>{{ statuses[row.status] ?? row.status }}</strong>
      <span>{{ row.provider === "simulation" ? "模拟" : "百炼" }}</span>
      <span v-if="row.error">{{ row.error }}</span>
      <button v-if="row.outputId" :disabled="busy" @click="work(() => inspect(row))">预览</button>
      <button v-if="['queued','running'].includes(row.status)" :disabled="busy"
        @click="work(async () => { await call('/jobs/' + row.id + '/cancel', { method:'POST' }); await refresh(); })">请求取消</button>
    </div>
    <template v-if="showJob">
      <div class="ai-preview"><figure><figcaption>原图</figcaption><img :src="before" alt="任务原图" /></figure><figure><figcaption>重绘结果</figcaption><img :src="after" alt="任务结果" /></figure></div>
      <div class="platform-tools">
        <button class="primary" :disabled="busy" @click="work(adopt)">采用并另存</button>
        <button @click="showJob = undefined; before = ''; after = ''">关闭预览</button>
      </div>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>.ai-preview{display:grid;grid-template-columns:1fr 1fr;gap:1rem}.ai-preview figure{margin:0;text-align:center}.ai-preview img{max-width:100%;max-height:50vh;object-fit:contain}</style>
