<script setup lang="ts">
import { onMounted, ref } from "vue";
import { validateProject } from "./project";
import { createProjectStorage, type SavedProject } from "./storage";
import { jsonRequest, platformApi, readAsset, type AccountSession } from "./platformApi";

type Summary = { id: string; name: string; revision: number; createdAt: string; updatedAt: string; deleted: boolean; reused?: boolean };
type Detail = Summary & { project: unknown; source_id: string | null; mask_id: string | null };
type Version = { id: string; revision: number; beadCount: number; colorCount: number };
type Room = { id: string; projectId: string; sequence: number; baseRevision: number; status: string };

const props = defineProps<{
  session: AccountSession;
  snapshot: () => Promise<SavedProject>;
  open: (row: SavedProject) => Promise<void>;
  link: (id: string, cloud: NonNullable<SavedProject["cloud"]>) => Promise<void>;
}>();
const emit = defineEmits<{ close: [] }>();
const entries = ref<Summary[]>([]), versions = ref<Version[]>([]), selected = ref<Summary>();
const status = ref(""), busy = ref(false), search = ref(""), trash = ref(false), page = ref(1), total = ref(0);
const guestStorage = createProjectStorage(), guestRows = ref<SavedProject[]>([]), showGuest = ref(false);
const structural = ref<Room>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);

async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true;
  status.value = "";
  try { await action(); }
  catch (e) {
    const error = e as Error & { status?: number };
    status.value = error.status === 409 ? error.message + "。当前本机内容仍可另存。" : error.message;
  } finally { busy.value = false; }
}
async function refresh() {
  const res = await call<{ items: Summary[]; total: number }>("/projects?" +
    new URLSearchParams({ q: search.value, trash: String(trash.value), page: String(page.value) }));
  entries.value = res.items;
  total.value = res.total;
}
onMounted(() => work(refresh));

async function getDetail(id: string) {
  return call<Detail>("/projects/" + encodeURIComponent(id));
}
async function sendAsset(source: string | undefined, kind: "source" | "mask", previous: string | null) {
  if (!source) return null;
  if (previous && await readAsset(previous, props.session) === source) return previous;
  const form = new FormData();
  form.set("file", await (await fetch(source)).blob(), kind + ".png");
  form.set("kind", kind);
  return (await call<{ id: string }>("/assets", { method: "POST", body: form })).id;
}
async function sync(row: SavedProject, operation: "save" | "copy" | "import" | "structure") {
  const { source, mask, ...project } = row.project;
  const old = (operation === "save" || operation === "structure") && row.cloud ? await getDetail(row.cloud.id) : undefined;
  if (old && old.revision !== row.cloud!.revision) throw Error("服务器项目已有新版本。请另存账号副本，或重新打开服务器版本");
  const confirmedRoom = operation === "structure" ? structural.value : undefined;
  if (operation === "structure" && (!confirmedRoom || confirmedRoom.projectId !== old?.id)) {
    throw Error("当前项目已切换，请重新选择同步");
  }
  if (operation === "save" && old) {
    structural.value = undefined;
    const { roomId } = await call<{ roomId: string | null }>("/collab/projects/" + old.id);
    if (roomId) {
      const state = await call<Room>("/collab/rooms/" + roomId);
      if (state.status === "open" && state.baseRevision === old.revision) structural.value = state;
      else status.value = "请在协作页处理当前房间后重试";
      return;
    }
  }
  if (!old && operation !== "copy") {
    const prior = await call<{ project: Summary | null }>("/project-imports/" + encodeURIComponent(row.id));
    if (prior.project) {
      status.value = "此项目已导入。可打开账号版本，或将本机修改另存为账号副本";
      return;
    }
  }
  const [source_id, mask_id] = await Promise.all([
    sendAsset(source, "source", old?.source_id ?? null),
    sendAsset(mask, "mask", old?.mask_id ?? null),
  ]);
  const body = { name: row.name, project, source_id, mask_id };
  const result = confirmedRoom && old
    ? await commitStructure(confirmedRoom, old.revision, body)
    : old
    ? await call<Summary>("/projects/" + old.id, jsonRequest("PATCH", { ...body, expected_revision: row.cloud!.revision }))
    : await call<Summary>("/projects", jsonRequest("POST", { ...body, request_id: operation === "copy" ? crypto.randomUUID() : row.id }));
  structural.value = undefined;
  if ((operation === "save" || operation === "structure") && !result.reused) {
    await props.link(row.id, { id: result.id, revision: result.revision });
  }
  status.value = result.reused ? "此项目已经导入账号，可在项目列表打开" :
    confirmedRoom ? "已保存新版本，原协作图纸可在协作页查看" : "已保存到账号";
  page.value = 1; trash.value = false; search.value = "";
  await refresh();
}
async function commitStructure(room: Room, revision: number, body: object) {
  const url = "/collab/rooms/" + room.id + "/structure";
  const { leaseId } = await call<{ leaseId: string }>(url + "/lease", jsonRequest("POST", {
    expectedRevision: revision, expectedSequence: room.sequence, requestId: crypto.randomUUID(),
  }));
  try {
    return await call<Summary>(url + "/commit", jsonRequest("POST", {
      ...body, expected_revision: revision, expectedSequence: room.sequence, leaseId,
    }));
  } catch (error) {
    await call(url + "/lease/" + leaseId, { method: "DELETE" }).catch(() => {});
    throw error;
  }
}
async function openProject(row: Summary) {
  const saved = await getDetail(row.id);
  const [source, mask] = await Promise.all([readAsset(saved.source_id, props.session), readAsset(saved.mask_id, props.session)]);
  const project = validateProject({ ...(saved.project as object), source, mask });
  await props.open({ id: saved.id, name: saved.name, createdAt: Date.parse(saved.createdAt),
    updatedAt: Date.parse(saved.updatedAt), cloud: { id: saved.id, revision: saved.revision }, project });
  emit("close");
}
async function history(row: Summary) {
  selected.value = row;
  versions.value = (await call<{ items: Version[] }>("/projects/" + row.id + "/versions")).items;
}
async function restore(version: Version) {
  const row = selected.value!;
  const saved = await call<Summary>("/projects/" + row.id + "/versions/" + version.id + "/restore",
    jsonRequest("POST", { expected_revision: row.revision }));
  await openProject(saved);
}
async function move(row: Summary) {
  await call("/projects/" + row.id + (row.deleted ? "/untrash" : "/trash"),
    jsonRequest("POST", { expected_revision: row.revision }));
  selected.value = undefined;
  await refresh();
}
async function showImports() {
  await guestStorage.migrateDraft();
  guestRows.value = (await guestStorage.listProjects()).filter(row => !row.deleted);
  showGuest.value = true;
}
</script>

<template>
  <section class="platform-panel panel" aria-label="我的账号项目">
    <div class="platform-tools">
      <h2>账号项目</h2>
      <button :disabled="busy" @click="emit('close')">返回创作</button>
    </div>
    <div class="platform-tools">
      <button class="primary" :disabled="busy" @click="work(async () => sync(await snapshot(), 'save'))">同步当前项目</button>
      <button :disabled="busy" @click="work(async () => sync(await snapshot(), 'copy'))">另存账号副本</button>
      <button :disabled="busy" @click="work(showImports)">导入本机游客草稿</button>
    </div>
    <div v-if="structural" class="platform-tools">
      <span>协作正在进行。提交本机图纸会关闭当前房间，并保留原协作图纸。</span>
      <button :disabled="busy" @click="work(async () => sync(await snapshot(), 'structure'))">提交为新版本</button>
      <button :disabled="busy" @click="structural = undefined">取消</button>
    </div>
    <div v-if="showGuest" class="platform-tools">
      <span v-if="!guestRows.length">没有游客草稿</span>
      <button v-for="row in guestRows" :key="row.id" :disabled="busy"
        @click="work(async () => sync(await guestStorage.loadProject(row.id), 'import'))">复制「{{ row.name }}」</button>
    </div>
    <form class="platform-tools" @submit.prevent="work(async () => { page = 1; selected = undefined; await refresh(); })">
      <input v-model="search" aria-label="搜索账号项目" placeholder="项目名称" maxlength="80" />
      <label><input v-model="trash" type="checkbox" @change="work(async () => { page = 1; selected = undefined; await refresh(); })" /> 回收站</label>
      <button :disabled="busy">搜索</button>
    </form>
    <p v-if="busy" role="status">处理中…</p>
    <p v-if="status" role="status">{{ status }}</p>
    <p v-if="!busy && !entries.length">没有项目</p>
    <div v-for="entry in entries" :key="entry.id" class="platform-tools">
      <strong>{{ entry.name }}</strong><span>版本 {{ entry.revision }}</span>
      <button v-if="!entry.deleted" :disabled="busy" @click="work(() => openProject(entry))">打开</button>
      <button v-if="!entry.deleted" :disabled="busy" @click="work(() => history(entry))">历史版本</button>
      <button :disabled="busy" @click="work(() => move(entry))">{{ entry.deleted ? "还原项目" : "移入回收站" }}</button>
    </div>
    <div v-if="total > 20" class="platform-tools">
      <button :disabled="busy || page <= 1" @click="work(async () => { page--; await refresh(); })">上一页</button>
      <span>{{ page }} / {{ Math.ceil(total / 20) }}</span>
      <button :disabled="busy || page * 20 >= total" @click="work(async () => { page++; await refresh(); })">下一页</button>
    </div>
    <div v-if="selected">
      <h3>{{ selected.name }} · 历史版本</h3>
      <div v-for="version in versions" :key="version.id" class="platform-tools">
        <span>版本 {{ version.revision }} · {{ version.beadCount }} 颗 · {{ version.colorCount }} 色</span>
        <button :disabled="busy" @click="work(() => restore(version))">从此版恢复</button>
      </div>
    </div>
  </section>
</template>
