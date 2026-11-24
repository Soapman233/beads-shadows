<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from "vue";
import App from "./App.vue";
import CloudProjects from "./CloudProjects.vue";
import InventoryPanel from "./InventoryPanel.vue";
import PlatformAdmin from "./PlatformAdmin.vue";
import PatternLibrary from "./PatternLibrary.vue";
import Workshop from "./Workshop.vue";
import AIJobs from "./AIJobs.vue";
import CommunityInbox from "./CommunityInbox.vue";
import MaterialShop from "./MaterialShop.vue";
import CollaborationPanel from "./CollaborationPanel.vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";
import { createProjectStorage } from "./storage";
import { loadPublishedPalettes } from "./palettes/catalog";
import { validateProject } from "./project";

const guest: AccountSession = { user: null, csrfToken: null };
const session = shallowRef<AccountSession>(guest);
const editor = ref<InstanceType<typeof App>>();
const accountId = computed(() => session.value.user?.id);
const storage = computed(() => createProjectStorage(accountId.value));
const screen = ref<"editor" | "cloud" | "login" | "profile" | "inventory" | "admin" | "library" | "workshop" | "ai" | "inbox" | "shop" | "collab">("editor");
const available = ref(false), initialized = ref(false), busy = ref(false), message = ref("");
const username = ref(""), password = ref(""), nickname = ref(""), preferred = ref("");
const oldPassword = ref(""), newPassword = ref(""), registering = ref(false);
const email = ref(""), recoveryCode = ref(""), closePassword = ref(""), closeConfirmed = ref(false);
const recovering = ref(false), mailEnabled = ref(false);
const incoming = shallowRef<{ file: File; sourceOrigin: string }>();
const importError = ref("");
const validRequests = new Map<string, number>();
const seenRequests = new Set<string>();
watch(accountId, () => {
  incoming.value = undefined;
  importError.value = "";
  validRequests.clear();
});

function extensionMessage(e: MessageEvent) {
  if (e.source !== window || e.origin !== location.origin || !e.data || e.data.version !== 1) return;
  const { type, requestId, file, sourceOrigin } = e.data;
  if (typeof requestId !== "string" || !/^[0-9a-f-]{36}$/i.test(requestId)) return;
  if (type === "bead-extension:probe") {
    if (validRequests.size >= 20) validRequests.clear();
    validRequests.set(requestId, Date.now() + 12000);
    window.postMessage({ type: "bead-extension:ready", version: 1, requestId }, location.origin);
  } else if (type === "bead-extension:import") {
    if (seenRequests.has(requestId) || Date.now() > (validRequests.get(requestId) ?? 0)) return;
    if (!(file instanceof File) || !["image/png", "image/jpeg"].includes(file.type) || file.size < 1 || file.size > 10 * 1024 * 1024) return;
    if (typeof sourceOrigin !== "string" || sourceOrigin.length > 512 || !/^https?:\/\//.test(sourceOrigin)) return;
    validRequests.delete(requestId);
    if (seenRequests.size >= 100) seenRequests.clear();
    seenRequests.add(requestId);
    incoming.value = { file, sourceOrigin };
    importError.value = "";
    window.postMessage({ type: "bead-extension:received", version: 1, requestId }, location.origin);
  }
}
async function acceptImport() {
  const value = incoming.value;
  if (!editor.value || !value) return;
  const identity = accountId.value;
  if (!(await editor.value.importExternal(value.file))) {
    if (incoming.value === value) importError.value = "图片导入失败，请检查格式或连接后重试";
    return;
  }
  if (identity !== accountId.value) return;
  if (incoming.value === value) incoming.value = undefined;
  screen.value = "editor";
}

onMounted(async () => {
  window.addEventListener("message", extensionMessage);
  window.addEventListener("focus", checkSession);
  try {
    available.value = !!(await platformApi<{ platformEnabled: boolean }>("/health")).platformEnabled;
    if (available.value) {
      session.value = await platformApi<AccountSession>("/auth/me");
      await loadPublishedPalettes().catch(() => {});
      const mail = await platformApi<{ mailEnabled: boolean }>("/account/recovery/status").catch(() => ({mailEnabled:false}));
      mailEnabled.value = mail.mailEnabled;
    }
  } catch { available.value = false; }
  finally { initialized.value = true; }
});
onBeforeUnmount(() => {
  window.removeEventListener("message", extensionMessage);
  window.removeEventListener("focus", checkSession);
});
async function checkSession() {
  const original = session.value;
  if (!original.user || busy.value) return;
  try { await platformApi<AccountSession>("/auth/me", {}, original); }
  catch (e) {
    if (session.value !== original || ![401, 409].includes((e as { status?: number }).status ?? 0)) return;
    await act(async () => {
      let saved = true;
      try { await editor.value?.flushProject(); }
      catch { saved = false; }
      session.value = guest;
      screen.value = "login";
      message.value = saved ? "会话已变更，请重新登录" : "会话已变更。最后一次草稿保存失败，请重新登录原账号检查此前版本";
    });
  }
}
async function act(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; message.value = "";
  try { await action(); }
  catch (e) { message.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function authenticate() {
  await editor.value?.flushProject();
  session.value = await platformApi<AccountSession>(registering.value ? "/auth/register" : "/auth/login",
    jsonRequest("POST", { username: username.value, password: password.value, ...(registering.value ? { nickname: nickname.value } : {}) }));
  password.value = "";
  screen.value = "editor";
}
async function logout() {
  await editor.value?.flushProject();
  try { await platformApi("/auth/logout", { method: "POST" }, session.value); }
  catch (e) {
    if (![401, 409].includes((e as { status?: number }).status ?? 0)) throw e;
  }
  session.value = guest;
  screen.value = "editor";
}
function profile() {
  nickname.value = session.value.user?.nickname ?? "";
  preferred.value = session.value.user?.preferredPalette ?? "";
  screen.value = "profile";
}
async function saveProfile() {
  await platformApi("/auth/me", jsonRequest("PATCH", { nickname: nickname.value, preferredPalette: preferred.value || null }), session.value);
  session.value = await platformApi<AccountSession>("/auth/me");
  message.value = "资料已保存";
}
async function changePassword() {
  await platformApi("/auth/password", jsonRequest("POST", { currentPassword: oldPassword.value, newPassword: newPassword.value }), session.value);
  session.value = await platformApi<AccountSession>("/auth/me");
  oldPassword.value = ""; newPassword.value = "";
  screen.value = session.value.user ? "editor" : "login";
}
async function sendRecovery() {
  await platformApi("/account/recovery/request", jsonRequest("POST", { username: username.value }));
  message.value = "若该账号已绑定验证邮箱，将收到验证码";
}
async function resetPassword() {
  await platformApi("/account/recovery/reset", jsonRequest("POST",
    { username: username.value, code: recoveryCode.value, password: newPassword.value }));
  recovering.value = false; recoveryCode.value = ""; newPassword.value = ""; message.value = "密码已重置，请重新登录";
}
async function bindEmail() {
  await platformApi("/account/recovery/address", jsonRequest("POST",
    { email: email.value, password: oldPassword.value }), session.value);
  oldPassword.value = ""; message.value = "验证码已发出";
}
async function verifyEmail() {
  await platformApi("/account/recovery/verify", jsonRequest("POST", { code: recoveryCode.value }), session.value);
  recoveryCode.value = ""; message.value = "邮箱已验证";
}
async function closeAccount() {
  await editor.value?.flushProject();
  await platformApi("/account/close", jsonRequest("POST",
    { password: closePassword.value, acknowledge: closeConfirmed.value }), session.value);
  closePassword.value = ""; closeConfirmed.value = false;
  session.value = guest; screen.value = "editor"; message.value = "账号已关闭";
}
async function downloadAccount() {
  if (!session.value.user) return;
  const response = await fetch("/api/account/export", { cache: "no-store",
    headers: { "X-Bead-Account": session.value.user.id } });
  if (!response.ok) throw Error("导出失败，请确认会话和服务器文件");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = "bead-account.zip";
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
}
async function openTemplate() {
  if (!editor.value) return;
  const side = 16, now = Date.now();
  const cells = Array.from({ length: side * side }, (_, i) => {
    const x = i % side - 7.5, y = Math.floor(i / side) - 7.5;
    if (Math.abs(x) + Math.abs(y) > 8) return null;
    return (Math.abs(x) + Math.abs(y) > 6 ? "EDGE" : y < 0 ? "TOP" : "BASE");
  });
  const pattern = { width: side, height: side, cells, colorLimit: 3, paletteName: "自制示例色板",
    palette: [{code:"EDGE",hex:"#214A3A"},{code:"TOP",hex:"#EFB75F"},{code:"BASE",hex:"#70AB87"}] };
  await editor.value.openAccountProject({id: crypto.randomUUID(), name: "几何菱形模板", createdAt: now, updatedAt: now,
    project: validateProject({schemaVersion:2,pattern,step:3})});
  screen.value = "editor";
}
</script>

<template>
  <p v-if="!initialized" class="platform-loading" role="status">正在打开工作区…</p>
  <template v-else>
    <section v-if="incoming" class="platform-panel panel" aria-label="扩展导入确认">
      <div class="platform-tools">
        <span>来自 {{ incoming.sourceOrigin }} 的图片 · {{ incoming.file.name }}</span>
        <button class="primary" :disabled="busy" @click="act(acceptImport)">导入为新项目</button>
        <button :disabled="busy" @click="incoming = undefined">取消</button>
      </div>
      <p v-if="importError" role="alert">{{ importError }}</p>
    </section>
    <nav v-if="available" class="platform-nav" aria-label="工作区">
      <button :disabled="busy" @click="screen = 'editor'; message = ''">创作</button>
      <button :disabled="busy" @click="screen = 'library'">图纸库</button>
      <template v-if="session.user">
        <button :disabled="busy" @click="screen = 'cloud'; message = ''">我的项目</button>
        <button :disabled="busy" @click="screen = 'inventory'">我的材料</button>
        <button :disabled="busy" @click="screen = 'workshop'">制作记录</button>
        <button :disabled="busy" @click="screen = 'ai'">图片重绘</button>
        <button :disabled="busy" @click="screen = 'inbox'">消息</button>
        <button :disabled="busy" @click="screen = 'shop'">材料商城</button>
        <button :disabled="busy" @click="screen = 'collab'">协作</button>
        <button v-if="session.user.role === 'admin'" :disabled="busy" @click="screen = 'admin'">管理</button>
        <button :disabled="busy" @click="profile">{{ session.user.nickname }}</button>
        <button :disabled="busy" @click="act(logout)">退出</button>
      </template>
      <button v-else :disabled="busy" @click="screen = 'login'">登录</button>
    </nav>
    <p v-if="message && screen === 'editor'" class="platform-loading" role="status">{{ message }}</p>
    <div v-show="screen === 'editor'">
      <App :key="session.user?.id ?? 'guest'" ref="editor" :storage="storage" :session="session" />
    </div>
    <section v-if="screen === 'login'" class="platform-panel panel">
      <h2>{{ registering ? "注册" : "登录" }}</h2>
      <form v-if="!recovering" class="platform-form" @submit.prevent="act(authenticate)">
        <label>账号 <input v-model="username" required autocomplete="username" maxlength="64" /></label>
        <label v-if="registering">昵称 <input v-model="nickname" maxlength="80" autocomplete="nickname" /></label>
        <label>密码 <input v-model="password" type="password" required :minlength="registering ? 10 : undefined"
          :autocomplete="registering ? 'new-password' : 'current-password'" /></label>
        <div class="platform-tools">
          <button class="primary" :disabled="busy">{{ registering ? "注册" : "登录" }}</button>
          <button type="button" :disabled="busy" @click="registering = !registering; message = ''">{{ registering ? "已有账号" : "创建账号" }}</button>
          <button v-if="mailEnabled && !registering" type="button" :disabled="busy" @click="recovering = true; message = ''">找回密码</button>
        </div>
      </form>
      <form v-else class="platform-form" @submit.prevent="act(resetPassword)">
        <label>账号 <input v-model="username" required autocomplete="username" /></label>
        <button type="button" :disabled="busy || !username.trim()" @click="act(sendRecovery)">发送验证码</button>
        <label>验证码 <input v-model="recoveryCode" required minlength="43" maxlength="43" /></label>
        <label>新密码 <input v-model="newPassword" type="password" required minlength="10" autocomplete="new-password" /></label>
        <div class="platform-tools"><button :disabled="busy">重置密码</button><button type="button" @click="recovering = false">返回登录</button></div>
      </form>
      <p v-if="message" role="alert">{{ message }}</p>
    </section>
    <CloudProjects v-if="screen === 'cloud' && editor && session.user" :session="session"
      :snapshot="editor.currentSnapshot" :open="editor.openAccountProject" :link="editor.rememberCloud" @close="screen = 'editor'" />
    <InventoryPanel v-if="screen === 'inventory' && session.user" :session="session" />
    <PatternLibrary v-if="screen === 'library'" :session="session" @template="act(openTemplate)" />
    <Workshop v-if="screen === 'workshop' && session.user" :session="session" />
    <CommunityInbox v-if="screen === 'inbox' && session.user" :session="session" />
    <MaterialShop v-if="screen === 'shop' && session.user" :session="session" />
    <CollaborationPanel v-if="screen === 'collab' && session.user && editor" :session="session" :open-copy="editor.openAccountProject" />
    <AIJobs v-if="screen === 'ai' && session.user && editor" :session="session" :snapshot="editor.currentSnapshot"
      :adopt="editor.adoptPixelArt" @close="screen = 'editor'" />
    <PlatformAdmin v-if="screen === 'admin' && session.user?.role === 'admin'" :session="session" />
    <section v-if="screen === 'profile'" class="platform-panel panel">
      <h2>个人设置</h2>
      <form class="platform-form" @submit.prevent="act(saveProfile)">
        <label>昵称 <input v-model="nickname" required maxlength="80" /></label>
        <label>首选色卡 <select v-model="preferred">
          <option value="">默认</option><option value="pixel-mard">MARD</option>
          <option value="pixel-perler">Perler</option><option value="pixel-hama-midi">Hama / Midi</option>
          <option value="pixel-artkal-s">Artkal</option>
        </select></label>
        <button :disabled="busy">保存资料</button>
      </form>
      <form class="platform-form" @submit.prevent="act(changePassword)">
        <label>当前密码 <input v-model="oldPassword" type="password" required autocomplete="current-password" /></label>
        <label>新密码 <input v-model="newPassword" type="password" required minlength="10" autocomplete="new-password" /></label>
        <button :disabled="busy">修改密码</button>
      </form>
      <details v-if="mailEnabled">
        <summary>绑定找回邮箱</summary>
        <form class="platform-form" @submit.prevent="act(bindEmail)">
          <label>邮箱 <input v-model="email" type="email" autocomplete="email" required /></label>
          <label>当前密码 <input v-model="oldPassword" type="password" autocomplete="current-password" required /></label>
          <button :disabled="busy">发送验证码</button>
        </form>
        <form class="platform-form" @submit.prevent="act(verifyEmail)">
          <label>验证码 <input v-model="recoveryCode" required minlength="43" maxlength="43" /></label>
          <button :disabled="busy">验证邮箱</button>
        </form>
      </details>
      <p><button :disabled="busy" @click="act(downloadAccount)">导出账号图纸与私有图片</button></p>
      <details v-if="session.user?.role === 'user'">
        <summary>关闭账号</summary>
        <form class="platform-form" @submit.prevent="act(closeAccount)">
          <p>关闭后账号退出登录，公开作品撤回。项目和操作记录进入保管状态。</p>
          <label>当前密码 <input v-model="closePassword" type="password" autocomplete="current-password" required /></label>
          <label><span><input v-model="closeConfirmed" type="checkbox" required /> 我确认关闭此账号</span></label>
          <button :disabled="busy || !closeConfirmed">关闭账号</button>
        </form>
      </details>
      <p v-if="message" role="status">{{ message }}</p>
    </section>
  </template>
</template>

<style>
.platform-nav,.platform-tools{display:flex;gap:.75rem;align-items:center;flex-wrap:wrap}
.platform-nav{padding:.75rem max(1rem,5%);background:#f8faf8;border-bottom:1px solid #dce5df}
.platform-panel,.platform-loading{margin:1.5rem auto;max-width:60rem;padding:1.25rem}
.platform-panel .platform-tools{margin-bottom:.7rem}
.platform-panel h2{margin:.3rem 0}
.platform-form{display:grid;gap:1rem;max-width:28rem;margin:1rem 0 1.5rem}
.platform-form label{display:grid;gap:.3rem}
.platform-form input,.platform-form select,.platform-tools input:not([type=checkbox]){padding:.45rem;border:1px solid #b8c9c1;border-radius:.35rem;font:inherit}
</style>
