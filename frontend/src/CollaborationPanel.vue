<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef } from "vue";
import PatternPreview from "./PatternPreview.vue";
import type { Pattern } from "./engine";
import { validateProject } from "./project";
import { createProjectStorage, type SavedProject } from "./storage";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";

type Member = { id: string; username: string; nickname: string; role: "owner" | "editor" | "viewer" };
type Shared = { id: string; name: string; role: Member["role"] };
type Invitation = { id: string; projectId: string; name: string; role: Member["role"] };
type Sharing = Shared & { roomId: string | null; archivedRoomId?: string | null; members: Member[] };
type Room = { id: string; name: string; role: Member["role"]; status: string; sequence: number; lastEditableOperationId?: string; structureLockedUntil?: string | null; pattern: Pattern };
type Change = { index: number; code: string | null };
type Operation = { id: string; sequence: number; changes: Change[] };
type Presence = { nickname: string; index: number | null };
const props = defineProps<{ session: AccountSession; openCopy: (row: SavedProject) => Promise<void> }>();
const localStorage = createProjectStorage(props.session.user!.id);
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>("/collab" + path, options, props.session);
const projects = ref<Shared[]>([]), invites = ref<Invitation[]>([]), sharing = ref<Sharing>(), room = ref<Room>();
const busy = ref(false), status = ref(""), color = ref(""), target = ref(""), role = ref("editor");
const connected = ref(false), presence = ref<Presence[]>([]);
const locked = computed(() => !!room.value?.structureLockedUntil);
const editable = computed(() => connected.value && !locked.value && room.value?.status === "open" && room.value.role !== "viewer");
const offlineCopy = shallowRef<SavedProject>();
const localPattern = computed(() => offlineCopy.value?.project.pattern ?? room.value?.pattern);
let socket: WebSocket | undefined;
let lastPresence = 0;
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; status.value = "";
  try { await action(); } catch (e) { status.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function refresh() {
  const [a, b] = await Promise.all([call<{ items: Shared[] }>("/projects"), call<{ items: Invitation[] }>("/invitations")]);
  projects.value = a.items; invites.value = b.items;
}
onMounted(() => work(refresh));
onBeforeUnmount(() => socket?.close());
function apply(operations: Operation[]) {
  const state = room.value;
  if (!state) return;
  for (const operation of operations) {
    if (operation.sequence <= state.sequence) continue;
    for (const change of operation.changes) state.pattern.cells[change.index] = change.code;
    state.sequence = operation.sequence;
  }
}
function connect(id: string) {
  socket?.close();
  connected.value = false; presence.value = [];
  const url = new URL("/api/collab/ws/" + id, location.href);
  url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const link = new WebSocket(url);
  socket = link;
  link.onmessage = event => {
    if (socket !== link) return;
    const data = JSON.parse(event.data);
    presence.value = data.presence ?? [];
    if (data.type === "snapshot") {
      room.value = data.room as Room;
      if (!room.value.pattern.palette.some(c => c.code === color.value)) color.value = room.value.pattern.palette[0]?.code ?? "";
    } else if (data.type === "operations" && room.value) {
      apply(data.operations);
      room.value.status = data.status; room.value.role = data.role;
      room.value.structureLockedUntil = data.structureLockedUntil;
      room.value.lastEditableOperationId = data.lastEditableOperationId;
    }
    connected.value = true;
  };
  link.onclose = e => {
    if (socket !== link) return;
    connected.value = false;
    if ([4401, 4403, 4404].includes(e.code)) {
      room.value = undefined; sharing.value = undefined; offlineCopy.value = undefined;
      status.value = "协作会话或权限已失效";
    }
  };
}
async function selectProject(id: string) {
  socket?.close(); socket = undefined;
  connected.value = false; room.value = undefined; offlineCopy.value = undefined;
  sharing.value = await call<Sharing>("/projects/" + id);
  if (sharing.value.roomId) await openRoom(sharing.value.roomId);
}
async function openRoom(id: string) {
  offlineCopy.value = undefined;
  room.value = await call<Room>("/rooms/" + id);
  color.value = room.value.pattern.palette[0]?.code ?? "";
  connect(id);
}
async function createRoom() {
  const row = sharing.value!;
  const saved = await call<Room>("/projects/" + row.id + "/room", { method: "POST" });
  sharing.value = { ...row, roomId: saved.id };
  await openRoom(saved.id);
}
async function sendInvite() {
  await call("/projects/" + sharing.value!.id + "/invite", jsonRequest("POST", { username: target.value, role: role.value }));
  target.value = ""; status.value = "邀请已发出";
}
async function paint(index: number) {
  const state = room.value;
  if (!state) return;
  const change: Change = { index, code: color.value || null };
  if (offlineCopy.value?.project.pattern) {
    const current = offlineCopy.value;
    const pattern = current.project.pattern!;
    const cells = [...pattern.cells];
    cells[index] = change.code;
    const row = { ...current, updatedAt: Date.now(), project: { ...current.project, pattern: { ...pattern, cells } } };
    const revision = await localStorage.saveProject(row);
    offlineCopy.value = { ...row, revision };
    return;
  }
  if (!editable.value) return;
  const op = await call<Operation>("/rooms/" + state.id + "/operations",
    jsonRequest("POST", { requestId: crypto.randomUUID(), changes: [change] }));
  // A WS update provides ordered changes, including edits made by others just before this one.
  state.lastEditableOperationId = op.id;
}
function indicate(index: number) {
  const now = performance.now();
  if (connected.value && socket?.readyState === WebSocket.OPEN && now - lastPresence > 300) {
    socket.send(JSON.stringify({type:"presence", index})); lastPresence = now;
  }
}
async function undo() {
  const state = room.value;
  if (!state?.lastEditableOperationId) return;
  await call("/rooms/" + state.id + "/undo", jsonRequest("POST",
    { requestId: crypto.randomUUID(), operationId: state.lastEditableOperationId }));
}
async function finish(action: "commit" | "close") {
  const state = room.value!;
  await call("/rooms/" + state.id + "/" + action,
    action === "commit" ? jsonRequest("POST", { expectedSequence: state.sequence }) : { method:"POST" });
  await selectProject(sharing.value!.id);
  status.value = action === "commit" ? "已保存账号项目的新版本" : "协作已关闭";
}
async function saveCopy() {
  await props.openCopy(copyRow());
  status.value = "已保存本机副本，可在创作页继续编辑";
}
function copyRow(): SavedProject {
  if (!room.value) throw Error("请先打开协作图纸");
  const now = Date.now();
  return { id: crypto.randomUUID(), name: room.value.name + " · 协作副本", createdAt: now, updatedAt: now,
    project: validateProject({ schemaVersion: 2, step: 3, pattern: JSON.parse(JSON.stringify(room.value.pattern)) }) };
}
async function beginOfflineCopy() {
  const row = copyRow();
  const revision = await localStorage.saveProject(row, 0);
  offlineCopy.value = { ...row, revision };
}
</script>
<template>
  <section class="platform-panel panel">
    <h2>项目协作</h2>
    <div v-for="invite in invites" :key="invite.id" class="platform-tools">
      <span>{{ invite.name }} · {{ invite.role === "editor" ? "编辑" : "查看" }}</span>
      <button :disabled="busy" @click="work(async () => { await call('/invitations/' + invite.id + '/accept', {method:'POST'}); await refresh(); await selectProject(invite.projectId); })">接受邀请</button>
    </div>
    <div class="platform-tools">
      <button v-for="row in projects" :key="row.id" :disabled="busy" @click="work(() => selectProject(row.id))">{{ row.name }}</button>
    </div>
    <template v-if="sharing">
      <h3>{{ sharing.name }}</h3>
      <form v-if="sharing.role === 'owner'" class="platform-tools" @submit.prevent="work(sendInvite)">
        <input v-model="target" aria-label="受邀人账号" placeholder="受邀人账号" required />
        <select v-model="role" aria-label="协作角色"><option value="editor">编辑</option><option value="viewer">只读</option></select>
        <button :disabled="busy">邀请</button>
      </form>
      <details>
        <summary>协作成员</summary>
        <div v-for="member in sharing.members" :key="member.id" class="platform-tools">
          <span>{{ member.nickname }} · {{ {owner:"所有者", editor:"编辑", viewer:"只读"}[member.role] }}</span>
          <button v-if="sharing.role === 'owner' && member.role !== 'owner'" :disabled="busy"
            @click="work(async () => { await call('/projects/' + sharing!.id + '/members/' + member.id, {method:'DELETE'}); sharing = await call('/projects/' + sharing!.id); })">撤销</button>
        </div>
      </details>
      <button v-if="!sharing.roomId && sharing.role === 'owner'" class="primary" :disabled="busy" @click="work(createRoom)">开启协作</button>
      <button v-if="sharing.archivedRoomId && room?.id !== sharing.archivedRoomId" :disabled="busy"
        @click="work(() => openRoom(sharing!.archivedRoomId!))">查看上一间房间</button>
      <button v-if="sharing.roomId && room?.id !== sharing.roomId" :disabled="busy"
        @click="work(() => openRoom(sharing!.roomId!))">返回当前房间</button>
    </template>
    <template v-if="room && localPattern">
      <p>{{ connected ? "已连接" : "未连接" }} · 序号 {{ room.sequence }}<span v-if="room.status === 'conflict'"> · 原项目已更新，可另存协作副本</span></p>
      <p v-if="locked">所有者正在保存新版本</p>
      <p v-if="offlineCopy">编辑已保存为本机副本</p>
      <p v-if="presence.length">在线 {{ presence.map(p => p.nickname).join("、") }}</p>
      <div class="platform-tools">
        <label>填色 <select v-model="color"><option value="">擦除</option><option v-for="item in room.pattern.palette" :key="item.code">{{ item.code }}</option></select></label>
        <button :disabled="busy || !editable || !room.lastEditableOperationId" @click="work(undo)">撤销我的笔画</button>
        <button v-if="!connected && !offlineCopy && room.status === 'open'" :disabled="busy" @click="connect(room.id)">重新连接</button>
        <button v-if="!connected && !offlineCopy && room.role !== 'viewer'" :disabled="busy" @click="work(beginOfflineCopy)">编辑离线副本</button>
        <button v-if="offlineCopy" :disabled="busy" @click="offlineCopy = undefined">返回协作图纸</button>
        <button v-else-if="room.role !== 'viewer'" :disabled="busy" @click="work(saveCopy)">另存本机副本</button>
      </div>
      <PatternPreview :pattern="localPattern" @cell="work(() => paint($event))" @inspect="indicate" />
      <div v-if="room.role === 'owner'" class="platform-tools">
        <button class="primary" :disabled="busy || !editable" @click="work(() => finish('commit'))">保存协作为新版本</button>
        <button :disabled="busy || locked || !['open','conflict'].includes(room.status)" @click="work(() => finish('close'))">结束协作</button>
      </div>
    </template>
    <p v-if="status" role="status">{{ status }}</p>
  </section>
</template>
