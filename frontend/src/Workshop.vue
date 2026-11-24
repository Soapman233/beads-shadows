<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import type { Pattern } from "./engine";
import PatternPreview from "./PatternPreview.vue";
import { jsonRequest, platformApi, readAsset, type AccountSession } from "./platformApi";

type Project = { id: string; name: string };
type Build = { id: string; name: string; revision: number; blockSize: number; beadCount: number; completedBeads: number };
type Block = { x: number; y: number; beads: number; completed: boolean };
type Detail = Build & { pattern: Pattern; blocks: Block[] };
const props = defineProps<{ session: AccountSession }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);
const projects = ref<Project[]>([]), builds = ref<Build[]>([]), detail = ref<Detail>();
const projectId = ref(""), blockSize = ref(29), color = ref(""), selected = ref<Block>();
const status = ref(""), busy = ref(false);
type Completion = { minutes: number; note: string; photoId: string | null };
const minutes = ref(0), note = ref(""), photoId = ref<string | null>(null), photo = ref<string>();
const percent = computed(() => detail.value ? Math.floor(detail.value.completedBeads * 100 / detail.value.beadCount) : 0);
let request: { projectId: string; versionId: string; blockSize: number; requestId: string } | undefined;
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; status.value = "";
  try { await action(); } catch (e) { status.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function list() { builds.value = (await call<{ items: Build[] }>("/builds")).items; }
onMounted(() => work(async () => {
  await list();
  projects.value = (await call<{ items: Project[] }>("/projects")).items;
  projectId.value = projects.value[0]?.id ?? "";
}));
function display(row: Detail) {
  detail.value = row;
  selected.value = row.blocks[0]; color.value = "";
}
async function start() {
  const id = projectId.value;
  const { version } = await call<{ version: { id: string } }>("/projects/" + id);
  if (!request || request.projectId !== id || request.versionId !== version.id || request.blockSize !== blockSize.value) {
    request = { projectId: id, versionId: version.id, blockSize: blockSize.value, requestId: crypto.randomUUID() };
  }
  display(await call<Detail>("/builds", jsonRequest("POST", request)));
  await loadCompletion(detail.value!.id);
  request = undefined;
  await list();
}
async function loadCompletion(id: string) {
  const { completion } = await call<{ completion: Completion | null }>("/builds/" + id + "/completion");
  minutes.value = completion?.minutes ?? 0;
  note.value = completion?.note ?? "";
  photoId.value = completion?.photoId ?? null;
  photo.value = await readAsset(photoId.value, props.session);
}
async function open(id: string) {
  display(await call<Detail>("/builds/" + id));
  await loadCompletion(id);
}
async function uploadPhoto(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file || !detail.value) return;
  const raw = new FormData();
  raw.set("file", file);
  const { image } = await call<{ image: string }>("/images", { method: "POST", body: raw });
  const form = new FormData();
  form.set("file", await (await fetch(image)).blob(), "finished.png"); form.set("kind", "finished");
  photoId.value = (await call<{ id: string }>("/assets", { method: "POST", body: form })).id;
  photo.value = image;
}
async function saveCompletion() {
  if (!detail.value) return;
  await call("/builds/" + detail.value.id + "/completion", jsonRequest("PUT",
    { minutes: minutes.value, note: note.value, photoId: photoId.value }));
  status.value = "成品档案已保存";
}
async function toggle() {
  const row = detail.value, block = selected.value;
  if (!row || !block) return;
  try {
    detail.value = await call<Detail>("/builds/" + row.id + "/blocks", jsonRequest("PATCH",
      { x: block.x, y: block.y, completed: !block.completed, expectedRevision: row.revision }));
    selected.value = detail.value.blocks.find(item => item.x === block.x && item.y === block.y);
    await list();
  } catch (e) {
    if ((e as { status?: number }).status === 409) await open(row.id);
    throw e;
  }
}
</script>
<template>
  <section class="platform-panel panel">
    <h2>制作记录</h2>
    <form class="platform-tools" @submit.prevent="work(start)">
      <select v-model="projectId" aria-label="制作项目"><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select>
      <label>板块 <select v-model.number="blockSize"><option :value="16">16 格</option><option :value="29">29 格</option><option :value="32">32 格</option></select></label>
      <button class="primary" :disabled="busy || !projectId">开始制作</button>
    </form>
    <div class="platform-tools">
      <button v-for="row in builds" :key="row.id" :disabled="busy" @click="work(() => open(row.id))">{{ row.name }} · {{ row.completedBeads }}/{{ row.beadCount }}</button>
    </div>
    <template v-if="detail">
      <h3>{{ detail.name }} · {{ percent }}%</h3>
      <label>分色高亮 <select v-model="color"><option value="">全部色号</option><option v-for="c in detail.pattern.palette" :key="c.code">{{ c.code }}</option></select></label>
      <PatternPreview :pattern="detail.pattern" :highlight="color" :block-size="detail.blockSize" :selected="selected" />
      <div class="platform-tools">
        <button v-for="block in detail.blocks" :key="`${block.x}:${block.y}`" :aria-pressed="selected === block"
          @click="selected = block">板 {{ block.y + 1 }}-{{ block.x + 1 }} · {{ block.beads }} 颗{{ block.completed ? " ✓" : "" }}</button>
      </div>
      <button v-if="selected" class="primary" :disabled="busy" @click="work(toggle)">{{ selected.completed ? "取消完成标记" : "标为完成" }}</button>
      <form v-if="percent === 100" class="platform-form" @submit.prevent="work(saveCompletion)">
        <h3>成品档案</h3>
        <label>实际用时（分钟） <input v-model.number="minutes" type="number" min="0" max="100000" required /></label>
        <label>制作笔记 <textarea v-model="note" maxlength="2000" rows="3" /></label>
        <label>成品照片 <input type="file" accept="image/png,image/jpeg" :disabled="busy" @change="work(() => uploadPhoto($event))" /></label>
        <img v-if="photo" :src="photo" alt="私有成品照片" style="max-width:100%;max-height:240px;object-fit:contain" />
        <button :disabled="busy">保存成品档案</button>
      </form>
    </template>
    <p v-if="status" role="status">{{ status }}</p>
  </section>
</template>
