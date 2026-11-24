<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";
import { planColorReplace, type Pattern } from "./engine";
import { isDatabasePalette, loadDatabasePalette } from "./palettes/catalog";
import PatternPreview from "./PatternPreview.vue";
import type { Project } from "./project";

type Item = { id: string; brand: string; series: string; sizeMm: number; code: string; hex: string; quantity: number; unitPrice: string | null; stableColorKey: string };
type Version = { id: string; brand: string; series: string; version: string };
type Material = { code: string; hex: string; needed: number; withReserve: number; onHand: number | null; shortage: number | null; estimatedCost: string | null };
const props = defineProps<{ session: AccountSession }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);
const items = ref<Item[]>([]), palettes = ref<Version[]>([]), selected = ref(""), csv = ref("");
const message = ref(""), busy = ref(false), movementItem = ref(""), reservePercent = ref(5);
const quantity = ref(1), piecesPerPack = ref<number>(), kind = ref("stock_in"), movements = ref<unknown>();
const projects = ref<{ id: string; name: string; revision: number }[]>([]), projectId = ref("");
const materials = ref<Material[]>([]), materialsTitle = ref("");
type Saved = { id: string; name: string; revision: number; source_id: string | null; mask_id: string | null; version: { revision: number }; project: Project };
type Option = { code: string; hex: string; quantity: number; distance: number };
const materialProject = ref<Saved>(), sourceCode = ref(""), options = ref<Option[]>([]);
const preview = ref<{ pattern: Pattern; affected: number }>();
const stockOptions = ref<{ code: string; stableColorKey: string }[]>([]), newColor = ref(""), unitPrice = ref("");
const chosenProject = computed(() => projects.value.find(row => row.id === projectId.value));
const pendingKey = "bead-stock-pending:" + props.session.user?.id;
let pending: { key: string; id: string } | undefined;
try { pending = JSON.parse(sessionStorage.getItem(pendingKey) ?? "null") ?? undefined; } catch {}

function requestId(value: unknown) {
  const key = JSON.stringify(value);
  if (pending?.key === key) return pending.id;
  if (pending) throw Error("上一笔库存操作待核对，请重试原参数或检查流水");
  pending = { key, id: crypto.randomUUID() };
  sessionStorage.setItem(pendingKey, JSON.stringify(pending));
  return pending.id;
}
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; message.value = "";
  try { await action(); } catch (e) {
    message.value = (e as Error).message;
  }
  finally { busy.value = false; }
}
async function refresh() {
  items.value = await call<Item[]>("/inventory");
}
onMounted(() => work(async () => {
  const [, catalog, directory] = await Promise.all([refresh(), call<Version[]>("/palettes"), call<{ items: typeof projects.value }>("/projects")]);
  palettes.value = catalog; selected.value = catalog[0]?.id ?? "";
  projects.value = directory.items; projectId.value = projects.value[0]?.id ?? "";
}));
async function importStock() {
  const data = { versionId: selected.value, csv: csv.value };
  await call("/inventory/import", jsonRequest("POST", { ...data, requestId: requestId(data) }));
  pending = undefined;
  sessionStorage.removeItem(pendingKey);
  await refresh();
  message.value = "入库完成";
}
async function move() {
  const data = { itemId: movementItem.value, quantity: quantity.value, kind: kind.value, piecesPerPack: piecesPerPack.value || undefined };
  await call("/inventory/movements", jsonRequest("POST", { ...data, requestId: requestId(data) }));
  pending = undefined;
  sessionStorage.removeItem(pendingKey);
  await refresh();
  message.value = "流水已登记";
}
async function loadStockOptions() {
  stockOptions.value = selected.value ? (await call<{ colors: typeof stockOptions.value }>("/palettes/" + selected.value)).colors : [];
  newColor.value = stockOptions.value[0]?.stableColorKey ?? "";
}
async function saveItem() {
  await call("/inventory", jsonRequest("POST", { stableColorKey: newColor.value, unitPrice: unitPrice.value || null }));
  await refresh();
  message.value = "库存色号已登记";
}
function clearPending() {
  pending = undefined;
  sessionStorage.removeItem(pendingKey);
  message.value = "已清除本机待确认记录";
}
async function listMaterials() {
  const project = chosenProject.value;
  if (!project) return;
  const current = await call<Saved>("/projects/" + project.id);
  const data = await call<{ rows: Material[] }>("/projects/" + project.id + "/versions/" + current.version.revision + "/materials?reservePercent=" + reservePercent.value);
  materials.value = data.rows;
  materialsTitle.value = project.name + " · 版本 " + current.version.revision;
  materialProject.value = current;
  options.value = []; preview.value = undefined;
}
async function suggest(code: string) {
  const row = materialProject.value;
  if (!row) return;
  sourceCode.value = code;
  options.value = []; preview.value = undefined;
  const result = await call<{ options: Option[] }>("/projects/" + row.id + "/versions/" + row.version.revision +
    "/substitutions/" + encodeURIComponent(code));
  options.value = result.options;
  if (!result.options.length) message.value = "当前没有同色卡库存替选";
}
async function showSwap(code: string) {
  const project = materialProject.value?.project;
  if (!project?.pattern) return;
  const id = project.pattern.paletteId;
  if (id && isDatabasePalette(id)) await loadDatabasePalette(id.slice(3));
  preview.value = planColorReplace(project.pattern, sourceCode.value, code, project.locked);
}
async function saveSwap() {
  const row = materialProject.value, swap = preview.value;
  if (!row || !swap) return;
  await call("/projects/" + row.id, jsonRequest("PATCH", { name: row.name, expected_revision: row.revision,
    source_id: row.source_id, mask_id: row.mask_id, project: { ...row.project, pattern: swap.pattern } }));
  await listMaterials();
  message.value = "替色已保存为新版本";
}
</script>

<template>
  <section class="platform-panel panel">
    <h2>我的材料</h2>
    <details>
      <summary>批量入库</summary>
      <form class="platform-form" @submit.prevent="work(importStock)">
        <label>数据库色卡 <select v-model="selected" required><option v-for="p in palettes" :key="p.id" :value="p.id">{{ p.brand }} / {{ p.series }} · {{ p.version }}</option></select></label>
        <p v-if="!palettes.length">请先由管理员发布色卡。</p>
        <label>入库 CSV <textarea v-model="csv" rows="4" placeholder="code,quantity,unitPrice" required /></label>
        <button class="primary" :disabled="busy || !selected">入库</button>
      </form>
    </details>
    <details @toggle="work(loadStockOptions)">
      <summary>登记色号或修改单价</summary>
      <form class="platform-form" @submit.prevent="work(saveItem)">
        <label>数据库色卡 <select v-model="selected" @change="work(loadStockOptions)"><option v-for="p in palettes" :key="p.id" :value="p.id">{{ p.brand }} / {{ p.series }} · {{ p.version }}</option></select></label>
        <label>色号 <select v-model="newColor" required><option v-for="option in stockOptions" :key="option.stableColorKey" :value="option.stableColorKey">{{ option.code }}</option></select></label>
        <label>每颗单价（元） <input v-model="unitPrice" type="number" min="0" step="0.0001" placeholder="可留空" /></label>
        <button :disabled="busy || !newColor">保存色号和单价</button>
      </form>
    </details>
    <div v-for="item in items" :key="item.id" class="platform-tools">
      <span class="stock-swatch" :style="{backgroundColor:item.hex}"></span>
      <strong>{{ item.code }}</strong><span>{{ item.brand }} · {{ item.series }} · {{ item.sizeMm }} mm</span>
      <span>{{ item.quantity }} 颗</span><span>{{ item.unitPrice ?? "未设置单价" }}</span>
      <button :disabled="busy" @click="movementItem = item.id; movements = undefined">登记流水</button>
      <button :disabled="busy" @click="work(async () => { movements = await call('/inventory/' + item.id + '/movements') })">查看流水</button>
    </div>
    <form v-if="movementItem" class="platform-tools" @submit.prevent="work(move)">
      <select v-model="kind" aria-label="流水类型"><option value="stock_in">入库</option><option value="issue">领用</option><option value="return">退回</option><option value="loss">损耗</option></select>
      <label>数量 <input v-model.number="quantity" type="number" min="1" required /></label>
      <label>每包颗数 <input v-model.number="piecesPerPack" type="number" min="1" placeholder="留空按颗" /></label>
      <button :disabled="busy">确认登记</button>
    </form>
    <pre v-if="movements">{{ movements }}</pre>
    <h3>缺料清单</h3>
    <form class="platform-tools" @submit.prevent="work(listMaterials)">
      <select v-model="projectId" aria-label="材料清单项目"><option v-for="project in projects" :key="project.id" :value="project.id">{{ project.name }}</option></select>
      <label>余量 % <input v-model.number="reservePercent" type="number" min="0" max="100" required /></label>
      <button :disabled="busy || !projectId">计算缺料</button>
    </form>
    <p v-if="materialsTitle">{{ materialsTitle }}</p>
    <table v-if="materials.length">
      <thead><tr><th>色号</th><th>图纸</th><th>含余量</th><th>库存</th><th>缺料</th><th>估算</th></tr></thead>
      <tbody><tr v-for="line in materials" :key="line.code"><th>{{ line.code }}</th><td>{{ line.needed }}</td><td>{{ line.withReserve }}</td><td>{{ line.onHand ?? "未映射" }}</td><td>{{ line.shortage ?? "—" }}</td><td>{{ line.estimatedCost ?? "—" }}</td><td><button v-if="line.shortage" :disabled="busy" @click="work(() => suggest(line.code))">替色建议</button></td></tr></tbody>
    </table>
    <div v-if="options.length" class="platform-tools">
      <span>替换 {{ sourceCode }}</span>
      <button v-for="option in options" :key="option.code" :disabled="busy" @click="work(() => showSwap(option.code))">{{ option.code }} · 库存 {{ option.quantity }} · ΔE76 {{ option.distance }}</button>
    </div>
    <template v-if="preview && materialProject?.project.pattern">
      <div class="swap-preview">
        <div><strong>原版本</strong><PatternPreview :pattern="materialProject.project.pattern" /></div>
        <div><strong>替色后 · {{ preview.affected }} 格</strong><PatternPreview :pattern="preview.pattern" /></div>
      </div>
      <button class="primary" :disabled="busy" @click="work(saveSwap)">采用并保存新版本</button>
    </template>
    <p v-if="message" role="status">{{ message }}</p>
    <button v-if="message.includes('待核对')" @click="clearPending">已核对流水，清除待确认记录</button>
  </section>
</template>

<style scoped>
.stock-swatch{width:1.25rem;height:1.25rem;border:1px solid #abbdb3;border-radius:3px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:.45rem;border-bottom:1px solid #dce5df}
.swap-preview{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin:1rem 0}
</style>
