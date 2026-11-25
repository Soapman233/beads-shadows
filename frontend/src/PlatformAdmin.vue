<script setup lang="ts">
import { onMounted, ref } from "vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";
import { loadPublishedPalettes } from "./palettes/catalog";
import PatternPreview from "./PatternPreview.vue";
import type { Pattern } from "./engine";

type Version = { id: string; version: string; status: string };
type Palette = { id: string; brand: string; series: string; sizeMm: number; versions: Version[] };
type User = { id: string; username: string; nickname: string; role: string; status: string; closed: boolean };
type Audit = { id: string; action: string; summary: string; createdAt: string };
const props = defineProps<{ session: AccountSession }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>("/admin" + path, options, props.session);
const palettes = ref<Palette[]>([]), users = ref<User[]>([]), audit = ref<Audit[]>([]);
const error = ref(""), busy = ref(false), tab = ref("palette"), selected = ref("");
const brand = ref(""), series = ref(""), sizeMm = ref(2.6), version = ref(""), source = ref(""),
  licenseStatus = ref("unknown"), csv = ref(""), preview = ref(""), reuseCodes = ref("");
const reason = ref("");
const userSearch = ref("");
const restoreTarget = ref<User>();
const restoreCode = ref("");
const closurePreview = ref<{ cutoffUtc: string | null; expiredAccounts: number }>();
const grantCount = ref(5);
const queue = ref<{ id: string; title: string; author: string; pattern: Pattern }[]>([]);
const reports = ref<{ id: string; title: string; reason: string }[]>([]);
const moderationStatus = ref("pending");
const overview = ref<{ since: string; until: string; activeAccounts: number; savedProjects: number;
  pendingPublications: number; pendingReports: number; newAccounts: number; recentPublished: number;
  recentInventoryMovements: number }>();
const socialReports = ref<{ id: string; kind: string; text: string | null; reason: string }[]>([]);
const unknownJobs = ref<{ id: string; provider: string; error: string; createdAt: string }[]>([]);
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); } catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function refresh() {
  palettes.value = await call<Palette[]>("/palettes");
  if (!selected.value) selected.value = palettes.value[0]?.id ?? "";
}
onMounted(() => work(refresh));
async function add() {
  await call("/palettes", jsonRequest("POST", { brand: brand.value, series: series.value, sizeMm: sizeMm.value }));
  await refresh();
}
async function importVersion(path: "preview" | "versions") {
  const result = await call("/palettes/" + selected.value + "/" + path,
    jsonRequest("POST", { version: version.value, source: source.value, licenseStatus: licenseStatus.value, csv: csv.value,
      reuseColorCodes: reuseCodes.value.split(/[\s,，]+/).filter(Boolean) }));
  if (path === "preview") preview.value = JSON.stringify(result, null, 2);
  else { preview.value = ""; await refresh(); }
}
async function publish(id: string, action: "publish" | "retire") {
  await call("/palette-versions/" + id + "/" + action, { method: "POST" });
  await Promise.all([refresh(), loadPublishedPalettes()]);
}
async function listUsers() {
  const username = userSearch.value.trim();
  users.value = await call<User[]>("/users" + (username ? "?" + new URLSearchParams({ username }) : ""));
}
async function searchUsers() {
  restoreTarget.value = undefined;
  restoreCode.value = "";
  await listUsers();
}
async function setStatus(user: User) {
  await call("/users/" + user.id, jsonRequest("PATCH", { status: user.status === "active" ? "frozen" : "active", reason: reason.value }));
  await listUsers();
}
async function restoreClosedAccount(user: User) {
  await platformApi("/account/admin/closures/" + user.id + "/restore",
    jsonRequest("POST", { code: restoreCode.value.trim(), reason: reason.value }), props.session);
  restoreCode.value = "";
  restoreTarget.value = undefined;
  await listUsers();
}
async function loadClosurePreview() {
  closurePreview.value = await platformApi<NonNullable<typeof closurePreview.value>>(
    "/account/admin/closure-preview", {}, props.session);
}
async function showAudit() { audit.value = await call<Audit[]>("/audit"); }
async function loadQueue() {
  const entries = await call<{ items: typeof queue.value }>("/publications?status=" + moderationStatus.value);
  queue.value = entries.items;
  reports.value = (await call<{ items: typeof reports.value }>("/publication-reports")).items;
}
async function moderate(id: string, action: string) {
  await call("/publications/" + id + "/moderate", jsonRequest("POST", { action, reason: reason.value }));
  await loadQueue();
}
async function resolveReport(id: string) {
  await call("/publication-reports/" + id + "/resolve", jsonRequest("POST", { reason: reason.value }));
  await loadQueue();
}
async function loadOverview() { overview.value = await call<NonNullable<typeof overview.value>>("/overview?days=7"); }
async function grantQuota(user: User) {
  await platformApi("/ai/admin/quota/" + user.id,
    jsonRequest("POST", { requestId: crypto.randomUUID(), count: grantCount.value }), props.session);
  error.value = "额度已发放";
}
async function loadSocialReports() {
  socialReports.value = (await call<{ items: typeof socialReports.value }>("/social-reports")).items;
}
async function resolveSocial(id: string, action: string) {
  await call("/social-reports/" + id + "/resolve", jsonRequest("POST", { action, reason: reason.value }));
  await loadSocialReports();
}
async function loadAI() {
  unknownJobs.value = await platformApi<typeof unknownJobs.value>("/ai/admin/unknown", {}, props.session);
}
async function reconcile(id: string, billed: boolean) {
  await platformApi("/ai/admin/jobs/" + id + "/reconcile", jsonRequest("POST", { billed, reason: reason.value }), props.session);
  await loadAI();
}
</script>

<template>
  <section class="platform-panel panel">
    <h2>平台管理</h2>
    <div class="platform-tools">
      <button :disabled="busy" @click="tab = 'palette'; work(refresh)">色卡</button>
      <button :disabled="busy" @click="tab = 'user'; work(listUsers)">用户</button>
      <button :disabled="busy" @click="tab = 'audit'; work(showAudit)">操作记录</button>
      <button :disabled="busy" @click="tab = 'review'; work(loadQueue)">作品审核</button>
      <button :disabled="busy" @click="tab = 'overview'; work(loadOverview)">平台概况</button>
      <button :disabled="busy" @click="tab = 'social'; work(loadSocialReports)">社区举报</button>
      <button :disabled="busy" @click="tab = 'ai'; work(loadAI)">重绘核对</button>
    </div>
    <div v-if="tab === 'palette'">
      <form class="platform-tools" @submit.prevent="work(add)">
        <input v-model="brand" aria-label="品牌" placeholder="品牌" required />
        <input v-model="series" aria-label="系列" placeholder="系列" required />
        <label>规格 mm <input v-model.number="sizeMm" type="number" min="0.1" max="20" step="0.1" required /></label>
        <button :disabled="busy">新建色卡</button>
      </form>
      <form v-if="palettes.length" class="platform-form" @submit.prevent="work(() => importVersion('versions'))">
        <label>色卡 <select v-model="selected"><option v-for="p in palettes" :key="p.id" :value="p.id">{{ p.brand }} / {{ p.series }} / {{ p.sizeMm }} mm</option></select></label>
        <label>版本 <input v-model="version" required /></label>
        <label>来源 <input v-model="source" required /></label>
        <label>许可状态 <select v-model="licenseStatus"><option value="unknown">未知</option><option value="open">开放许可</option><option value="permission">已获授权</option><option value="internal">内部使用</option></select></label>
        <label>沿用库存身份的色号 <input v-model="reuseCodes" placeholder="确认同一实物颜色后填写，以逗号分隔" /></label>
        <label>颜色 CSV <textarea v-model="csv" rows="5" placeholder="code,hex,material" required /></label>
        <div class="platform-tools">
          <button type="button" :disabled="busy" @click="work(() => importVersion('preview'))">预览差异</button>
          <button :disabled="busy">导入草稿</button>
        </div>
        <pre v-if="preview">{{ preview }}</pre>
      </form>
      <div v-for="p in palettes" :key="p.id">
        <h3>{{ p.brand }} / {{ p.series }}</h3>
        <div v-for="v in p.versions" :key="v.id" class="platform-tools">
          <span>{{ v.version }} · {{ { draft: "草稿", published: "已发布", retired: "已退役" }[v.status] }}</span>
          <button v-if="v.status === 'draft'" :disabled="busy" @click="work(() => publish(v.id, 'publish'))">发布</button>
          <button v-if="v.status === 'published'" :disabled="busy" @click="work(() => publish(v.id, 'retire'))">退役</button>
        </div>
      </div>
    </div>
    <div v-if="tab === 'user'">
      <form class="platform-tools" @submit.prevent="work(searchUsers)">
        <label>账号 <input v-model="userSearch" maxlength="64" /></label>
        <button :disabled="busy">查找账号</button>
      </form>
      <label>操作理由 <input v-model="reason" maxlength="180" /></label>
      <label>发放次数 <input v-model.number="grantCount" type="number" min="1" max="1000" /></label>
      <button :disabled="busy" @click="work(loadClosurePreview)">查看已超期关闭账号</button>
      <p v-if="closurePreview" role="status">{{ closurePreview.cutoffUtc
        ? `超期关闭账号 ${closurePreview.expiredAccounts} 个`
        : "恢复期限尚未设置" }}</p>
      <div v-for="user in users" :key="user.id" class="platform-tools">
        <span>{{ user.nickname }} · {{ user.username }} · {{ user.closed ? "已关闭" : user.status === "active" ? "正常" : "冻结" }}</span>
        <button v-if="user.closed" :disabled="busy" @click="restoreTarget = user; restoreCode = ''">恢复账号</button>
        <button v-else-if="user.role === 'user'" :disabled="busy || !reason.trim()" @click="work(() => setStatus(user))">{{ user.status === 'active' ? "冻结" : "解冻" }}</button>
        <button v-if="!user.closed" :disabled="busy || !Number.isInteger(grantCount) || grantCount < 1 || grantCount > 1000" @click="work(() => grantQuota(user))">发放重绘额度</button>
      </div>
      <form v-if="restoreTarget" class="platform-tools" @submit.prevent="work(() => restoreClosedAccount(restoreTarget!))">
        <label>{{ restoreTarget.username }} 的邮箱验证码
          <input v-model="restoreCode" type="password" autocomplete="off" required minlength="43" maxlength="43" />
        </label>
        <button :disabled="busy || !reason.trim()">确认恢复</button>
        <button type="button" :disabled="busy" @click="restoreTarget = undefined; restoreCode = ''">取消</button>
      </form>
    </div>
    <template v-if="tab === 'audit'">
      <div v-for="entry in audit" :key="entry.id" class="platform-tools">{{ entry.createdAt }} · {{ entry.action }} · {{ entry.summary }}</div>
    </template>
    <template v-if="tab === 'review'">
      <div class="platform-tools">
        <select v-model="moderationStatus" aria-label="审核状态" @change="work(loadQueue)"><option value="pending">待审核</option><option value="published">已发布</option></select>
        <label>处理理由 <input v-model="reason" maxlength="300" /></label>
      </div>
      <details v-for="row in queue" :key="row.id">
        <summary>{{ row.title }} · {{ row.author }}</summary>
        <PatternPreview :pattern="row.pattern" />
        <div class="platform-tools">
          <template v-if="moderationStatus === 'pending'">
            <button :disabled="busy || !reason.trim()" @click="work(() => moderate(row.id, 'approve'))">通过</button>
            <button :disabled="busy || !reason.trim()" @click="work(() => moderate(row.id, 'reject'))">驳回</button>
          </template>
          <button v-else :disabled="busy || !reason.trim()" @click="work(() => moderate(row.id, 'takedown'))">下架</button>
        </div>
      </details>
      <h3>待处理举报</h3>
      <div v-for="row in reports" :key="row.id" class="platform-tools">
        <strong>{{ row.title }}</strong><span>{{ row.reason }}</span>
        <button :disabled="busy || !reason.trim()" @click="work(() => resolveReport(row.id))">标记已处理</button>
      </div>
    </template>
    <template v-if="tab === 'overview' && overview">
      <p>近 7 天（UTC）{{ overview.since }} 至 {{ overview.until }}</p>
      <dl>
        <dt>正常账号</dt><dd>{{ overview.activeAccounts }}</dd>
        <dt>未回收项目</dt><dd>{{ overview.savedProjects }}</dd>
        <dt>待审核作品</dt><dd>{{ overview.pendingPublications }}</dd>
        <dt>待处理作品举报</dt><dd>{{ overview.pendingReports }}</dd>
        <dt>近 7 天新增账号</dt><dd>{{ overview.newAccounts }}</dd>
        <dt>近 7 天发布且仍公开</dt><dd>{{ overview.recentPublished }}</dd>
        <dt>近 7 天库存流水</dt><dd>{{ overview.recentInventoryMovements }}</dd>
      </dl>
    </template>
    <template v-if="tab === 'social' || tab === 'ai'">
      <label>核对记录 <input v-model="reason" maxlength="180" /></label>
    </template>
    <template v-if="tab === 'social'">
      <p v-if="!socialReports.length">暂无待处理举报</p>
      <div v-for="row in socialReports" :key="row.id" class="platform-tools">
        <strong>{{ row.kind === "comment" ? "评论" : "私信" }}举报</strong><span>{{ row.text ?? "内容已移除" }} · {{ row.reason }}</span>
        <button :disabled="busy || !reason.trim()" @click="work(() => resolveSocial(row.id, 'resolve'))">处理完成</button>
        <button v-if="row.kind === 'comment'" :disabled="busy || !reason.trim()" @click="work(() => resolveSocial(row.id, 'remove_comment'))">移除评论</button>
      </div>
    </template>
    <template v-if="tab === 'ai'">
      <p v-if="!unknownJobs.length">暂无待核对任务</p>
      <div v-for="row in unknownJobs" :key="row.id" class="platform-tools">
        <span>{{ row.provider }} · {{ row.createdAt }} · {{ row.error }}</span>
        <button :disabled="busy || !reason.trim()" @click="work(() => reconcile(row.id, true))">确认已计费</button>
        <button :disabled="busy || !reason.trim()" @click="work(() => reconcile(row.id, false))">未计费，释放额度</button>
      </div>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>
