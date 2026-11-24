<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  type ProjectStorage,
  type SavedProject,
} from "./storage";
const props = defineProps<{
  storage: ProjectStorage;
  current: string;
  beforeAction: (id: string, name?: string) => Promise<void>;
}>();
const { listProjects, loadProject, saveProject } = props.storage;
const emit = defineEmits<{
  open: [row: SavedProject];
  create: [];
  close: [];
  rename: [id: string, name: string];
}>();
const rows = ref<SavedProject[]>([]),
  error = ref("");
async function refresh() {
  rows.value = await listProjects();
}
onMounted(() => refresh().catch((e) => (error.value = e.message)));
async function open(row: SavedProject) {
  if (busy.value) return;
  busy.value = true;
  try {
    emit("open", await loadProject(row.id));
  } catch {
    error.value = "项目损坏，请打开备份";
  } finally {
    busy.value = false;
  }
}
const busy = ref(false);
async function change(row: SavedProject, action: string) {
  if (busy.value) return;
  busy.value = true;
  try {
    await props.beforeAction(
      row.id,
      action === "rename"
        ? row.name.trim().slice(0, 80) || "未命名"
        : undefined,
    );
    if (action === "rename" && row.id === props.current) {
      emit("rename", row.id, row.name.trim().slice(0, 80) || "未命名");
      await refresh();
      return;
    }
    const full = await loadProject(row.id);
    if (action === "copy") {
      full.id = crypto.randomUUID();
      full.revision = 0;
      delete full.cloud;
      full.name += " 副本";
      full.createdAt = Date.now();
    } else if (action === "delete") full.deleted = Date.now();
    else if (action === "restore") delete full.deleted;
    else full.name = row.name.trim().slice(0, 80) || "未命名";
    full.updatedAt = Date.now();
    await saveProject(full);
    if (action === "rename") emit("rename", full.id, full.name);
    await refresh();
  } catch {
    error.value = "保存失败，请备份项目";
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <section class="project-list">
    <div class="panel-heading">
      <h2>项目</h2>
      <button :disabled="busy" @click="$emit('create')">新建</button
      ><button :disabled="busy" @click="$emit('close')">关闭</button>
    </div>
    <p role="alert" v-if="error">{{ error }}</p>
    <div :inert="busy" v-for="r in rows" class="project-row">
      <img v-if="r.thumbnail" :src="r.thumbnail" width="45" height="45" /><input
        v-model="r.name"
        :aria-label="'项目名称 ' + r.id"
      /><button @click="change(r, 'rename')">命名</button
      ><span>{{ r.deleted ? "回收站" : r.id === current ? "当前" : "" }}</span
      ><template v-if="!r.deleted"
        ><button @click="open(r)">打开</button
        ><button @click="change(r, 'copy')">复制</button
        ><button :disabled="r.id === current" @click="change(r, 'delete')">
          移入回收站
        </button></template
      ><button v-else @click="change(r, 'restore')">恢复</button>
    </div>
  </section>
</template>
