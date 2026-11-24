<script setup lang="ts">
import { onMounted, ref } from "vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";
type Person = { id: string; username: string; nickname: string };
type Notice = { id: string; text: string; read: boolean; createdAt: string };
type Message = { id: string; senderId: string; text: string };
const props = defineProps<{ session: AccountSession }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);
const inbox = ref<Notice[]>([]), conversations = ref<{ id: string; peer: Person }[]>([]), peer = ref<Person>();
const messages = ref<Message[]>([]), blocked = ref(false), busy = ref(false), status = ref("");
const username = ref(""), draft = ref(""), reason = ref("");
let pending: { id: string; peer: string; text: string } | undefined;
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; status.value = "";
  try { await action(); } catch (e) { status.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function refresh() {
  const [a, b] = await Promise.all([call<{ items: Notice[] }>("/notifications"),
    call<{ items: typeof conversations.value }>("/conversations")]);
  inbox.value = a.items; conversations.value = b.items;
}
async function talk(person: Person) {
  const row = await call<{ items: Message[]; blocked: boolean }>("/messages/" + person.id);
  peer.value = person; messages.value = [...row.items].reverse(); blocked.value = row.blocked;
}
async function send() {
  const person = peer.value;
  if (!person) return;
  const text = draft.value.trim();
  if (!pending || pending.peer !== person.id || pending.text !== text) pending = { id: crypto.randomUUID(), peer: person.id, text };
  await call("/messages/" + person.id, jsonRequest("POST", { text, requestId: pending.id }));
  pending = undefined; draft.value = "";
  await Promise.all([talk(person), refresh()]);
}
onMounted(() => work(refresh));
</script>
<template>
  <section class="platform-panel panel">
    <h2>消息</h2>
    <button :disabled="busy" @click="work(refresh)">刷新</button>
    <h3>通知</h3>
    <p v-if="!inbox.length">暂无通知</p>
    <div class="platform-tools" v-for="row in inbox" :key="row.id"><span>{{ row.text }}</span>
      <button v-if="!row.read" :disabled="busy" @click="work(async () => { await call('/notifications/' + row.id + '/read', {method:'PATCH'}); row.read = true; })">标为已读</button>
    </div>
    <h3>私信</h3>
    <form class="platform-tools" @submit.prevent="work(async () => talk(await call('/people/' + encodeURIComponent(username))))">
      <input v-model="username" aria-label="收件账号" placeholder="对方账号" required maxlength="64" /><button :disabled="busy">打开会话</button>
    </form>
    <div class="platform-tools"><button v-for="row in conversations" :key="row.id" :disabled="busy" @click="work(() => talk(row.peer))">{{ row.peer.nickname }}</button></div>
    <template v-if="peer">
      <h3>{{ peer.nickname }}</h3>
      <div class="platform-tools">
        <button :disabled="busy" @click="work(async () => { await call('/blocks/' + peer!.id, {method: blocked ? 'DELETE' : 'PUT'}); await talk(peer!); })">{{ blocked ? "解除屏蔽" : "屏蔽对方" }}</button>
        <input v-model="reason" aria-label="私信举报理由" placeholder="举报理由" maxlength="300" />
      </div>
      <div class="platform-tools" v-for="row in messages" :key="row.id">
        <strong>{{ row.senderId === session.user?.id ? "我" : peer.nickname }}</strong><span>{{ row.text }}</span>
        <button v-if="row.senderId !== session.user?.id" :disabled="busy || !reason.trim()"
          @click="work(async () => { await call('/messages/report/' + row.id, jsonRequest('POST', { reason })); reason = ''; status = '已举报'; })">举报</button>
      </div>
      <form v-if="!blocked" class="platform-tools" @submit.prevent="work(send)">
        <input v-model="draft" maxlength="1000" aria-label="私信内容" placeholder="输入消息" required />
        <button :disabled="busy">发送</button>
      </form>
    </template>
    <p v-if="status" role="status">{{ status }}</p>
  </section>
</template>
