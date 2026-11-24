<script setup lang="ts">
import { onMounted, ref } from "vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";

type Card = { id: string; title: string; category: string; brand?: string; author: string; width: number; height: number; beadCount: number; colorCount: number; favoriteCount: number; };
type Detail = Card & { previewUrl: string; favorited: boolean; allowDownload: boolean; allowRemix: boolean };
type Comment = { id: string; author: string; authorId: string; text: string; replyTo?: string };
type MyPublication = { id: string; title: string; status: string; reason?: string };
const categories = { portrait: "人像", animal: "动物", object: "物品", scenery: "风景", other: "其他" };
const props = defineProps<{ session: AccountSession }>();
const emit = defineEmits<{ template: [] }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);
const cards = ref<Card[]>([]), detail = ref<Detail>(), busy = ref(false), message = ref("");
const query = ref(""), sort = ref("newest"), category = ref(""), brand = ref(""), page = ref(1), more = ref(false);
const maxWidth = ref(128), maxColors = ref(512), maxBeads = ref(8192), mode = ref("browse");
const projects = ref<{ id: string; name: string }[]>([]), mine = ref<MyPublication[]>([]);
const projectId = ref(""), title = ref(""), releaseCategory = ref("other"), allowDownload = ref(false), allowRemix = ref(false),
  rights = ref(false), reason = ref("");
const comments = ref<Comment[]>([]), commentText = ref(""), replyTo = ref<Comment>();
const difficulty = ref<{ isolatedCount: number }>(), related = ref<Card[]>([]);
const remixRequests = new Map<string, string>();
const states: Record<string, string> = { pending: "待审核", published: "已发布", rejected: "已驳回", taken_down: "已下架", withdrawn: "已撤回" };
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; message.value = "";
  try { await action(); } catch (e) { message.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function refresh() {
  detail.value = undefined;
  if (mode.value === "mine") {
    const [projectRows, publicationRows] = await Promise.all([
      call<{ items: typeof projects.value }>("/projects"),
      call<{ items: MyPublication[] }>("/my-publications?page=" + page.value),
    ]);
    projects.value = projectRows.items;
    if (!projectId.value) projectId.value = projects.value[0]?.id ?? "";
    mine.value = publicationRows.items;
    more.value = (publicationRows as { hasMore?: boolean }).hasMore ?? false;
    return;
  }
  const suffix = new URLSearchParams({ query: query.value, category: category.value, brand: brand.value, sort: sort.value,
    page: String(page.value), maxWidth: String(maxWidth.value), maxColors: String(maxColors.value), maxBeads: String(maxBeads.value) });
  const rows = await call<{ items: Card[]; hasMore: boolean }>(mode.value === "favorites" ? "/favorites?page=" + page.value : "/publications?" + suffix);
  cards.value = rows.items; more.value = rows.hasMore;
}
onMounted(() => work(refresh));
async function setMode(next: string) { mode.value = next; page.value = 1; await refresh(); }
async function open(card: Card) {
  const base = "/publications/" + card.id;
  const [item, score, suggestions, entries] = await Promise.all([
    call<Detail>(base), call<{ isolatedCount: number }>(base + "/difficulty"),
    call<{ items: Card[] }>(base + "/related"), call<{ items: Comment[] }>(base + "/comments"),
  ]);
  detail.value = item; difficulty.value = score; related.value = suggestions.items; comments.value = entries.items;
  reason.value = ""; replyTo.value = undefined;
}
async function remix(row: Detail) {
  const requestId = remixRequests.get(row.id) ?? crypto.randomUUID();
  remixRequests.set(row.id, requestId);
  await call("/publications/" + row.id + "/remix", jsonRequest("POST", { requestId }));
  message.value = "已复制到我的项目";
}
async function comment() {
  if (!detail.value) return;
  await call("/publications/" + detail.value.id + "/comments", jsonRequest("POST",
    { text: commentText.value, replyTo: replyTo.value?.id }));
  commentText.value = "";
  await open(detail.value);
}
async function submit() {
  const { version } = await call<{ version: { id: string } }>("/projects/" + projectId.value);
  await call("/publications", jsonRequest("POST", { projectId: projectId.value, versionId: version.id, title: title.value,
    category: releaseCategory.value, allowDownload: allowDownload.value, allowRemix: allowRemix.value, rightsConfirmed: rights.value }));
  rights.value = false; title.value = "";
  await refresh();
  message.value = "已提交审核";
}
async function favorite(row: Detail) {
  await call("/publications/" + row.id + "/favorite", { method: row.favorited ? "DELETE" : "PUT" });
  await open(row);
}
async function report(row: Detail) {
  await call("/publications/" + row.id + "/report", jsonRequest("POST", { reason: reason.value }));
  reason.value = "";
  message.value = "已提交举报";
}
</script>
<template>
  <section class="platform-panel panel">
    <h2>图纸库</h2>
    <div class="platform-tools">
      <button :disabled="busy" @click="work(() => setMode('browse'))">浏览</button>
      <button :disabled="busy" @click="emit('template')">打开几何模板</button>
      <button v-if="session.user" :disabled="busy" @click="work(() => setMode('favorites'))">收藏</button>
      <button v-if="session.user" :disabled="busy" @click="work(() => setMode('mine'))">我的发布</button>
    </div>
    <form v-if="mode === 'browse'" class="platform-tools" @submit.prevent="work(async () => { page = 1; await refresh(); })">
      <input v-model="query" placeholder="标题" aria-label="搜索图纸" maxlength="80" />
      <input v-model="brand" placeholder="品牌" aria-label="品牌筛选" maxlength="60" />
      <select v-model="category" aria-label="分类筛选"><option value="">全部分类</option><option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option></select>
      <select v-model="sort" aria-label="排序"><option value="newest">最新</option><option value="popular">热门</option></select>
      <details><summary>尺寸与用量</summary>
        <label>最大宽度 <input v-model.number="maxWidth" type="number" min="1" max="128" required /></label>
        <label>最多颜色 <input v-model.number="maxColors" type="number" min="1" max="512" required /></label>
        <label>最多颗数 <input v-model.number="maxBeads" type="number" min="1" max="8192" required /></label>
      </details>
      <button :disabled="busy">筛选</button>
    </form>
    <template v-if="mode !== 'mine'">
      <p v-if="!cards.length && !busy">暂无作品</p>
      <div v-for="card in cards" :key="card.id" class="platform-tools">
        <strong>{{ card.title }}</strong><span>{{ card.author }} · {{ card.width }} × {{ card.height }} 格 · {{ card.beadCount }} 颗 · {{ card.colorCount }} 色</span>
        <button :disabled="busy" @click="work(() => open(card))">查看</button>
      </div>
      <template v-if="detail">
        <h3>{{ detail.title }}</h3>
        <img class="public-preview" :src="detail.previewUrl" alt="公开图纸预览" />
        <p v-if="difficulty">{{ detail.beadCount }} 颗 · {{ detail.colorCount }} 色 · {{ difficulty.isolatedCount }} 个孤立色格</p>
        <div class="platform-tools">
          <a v-if="detail.allowDownload" :href="'/api/publications/' + detail.id + '/download'" download>下载 JSON 图纸</a>
          <button v-if="session.user" :disabled="busy" @click="work(() => favorite(detail!))">{{ detail.favorited ? "取消收藏" : "收藏" }}</button>
          <button v-if="session.user && detail.allowRemix" :disabled="busy" @click="work(() => remix(detail!))">复制编辑</button>
        </div>
        <form v-if="session.user" class="platform-tools" @submit.prevent="work(() => report(detail!))">
          <input v-model="reason" aria-label="举报理由" placeholder="举报理由" maxlength="300" required />
          <button :disabled="busy">举报</button>
        </form>
        <div v-if="related.length" class="platform-tools">
          <span>同类作品</span>
          <button v-for="row in related" :key="row.id" :disabled="busy" @click="work(() => open(row))">{{ row.title }}</button>
        </div>
        <h3>评论</h3>
        <div v-for="row in comments" :key="row.id" class="platform-tools">
          <strong>{{ row.author }}</strong><span>{{ row.text }}</span>
          <button v-if="session.user" :disabled="busy" @click="replyTo = row">回复</button>
          <button v-if="session.user?.id === row.authorId" :disabled="busy"
            @click="work(async () => { await call('/comments/' + row.id, { method: 'DELETE' }); await open(detail!); })">删除</button>
          <button v-if="session.user && session.user.id !== row.authorId" :disabled="busy || !reason.trim()"
            @click="work(async () => { await call('/comments/' + row.id + '/report', jsonRequest('POST', { reason })); message = '评论举报已提交'; reason = ''; })">举报评论</button>
        </div>
        <form v-if="session.user" class="platform-tools" @submit.prevent="work(comment)">
          <span v-if="replyTo">回复 {{ replyTo.author }} <button type="button" @click="replyTo = undefined">取消</button></span>
          <input v-model="commentText" aria-label="评论" placeholder="写评论" maxlength="1000" required />
          <button :disabled="busy">发送</button>
        </form>
      </template>
    </template>
    <template v-else>
      <form class="platform-form" @submit.prevent="work(submit)">
        <label>账号项目 <select v-model="projectId" required><option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option></select></label>
        <label>作品标题 <input v-model="title" required maxlength="80" /></label>
        <label>分类 <select v-model="releaseCategory"><option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option></select></label>
        <div class="platform-tools">
          <span><input id="works-download" v-model="allowDownload" type="checkbox" /> <label class="inline-label" for="works-download">允许下载</label></span>
          <span><input id="works-remix" v-model="allowRemix" type="checkbox" /> <label class="inline-label" for="works-remix">允许二创</label></span>
        </div>
        <span><input id="works-consent" v-model="rights" type="checkbox" required /> <label class="inline-label" for="works-consent">确认有权公开图纸。原图与掩码保持私有</label></span>
        <button class="primary" :disabled="busy || !projectId || !rights">提交审核</button>
      </form>
      <div v-for="row in mine" :key="row.id" class="platform-tools">
        <strong>{{ row.title }}</strong><span>{{ states[row.status] ?? row.status }}{{ row.reason ? ' · ' + row.reason : '' }}</span>
        <button v-if="['pending','published'].includes(row.status)" :disabled="busy"
          @click="work(async () => { await call('/publications/' + row.id + '/withdraw', {method:'POST'}); await refresh(); })">撤回</button>
      </div>
    </template>
    <div class="platform-tools" v-if="page > 1 || more">
      <button :disabled="busy || page < 2" @click="work(async () => { page--; await refresh(); })">上一页</button>
      <span>第 {{ page }} 页</span>
      <button :disabled="busy || !more" @click="work(async () => { page++; await refresh(); })">下一页</button>
    </div>
    <p v-if="message" role="status">{{ message }}</p>
  </section>
</template>
<style scoped>
.platform-form .inline-label{display:inline}
.public-preview{display:block;width:min(100%,360px);max-height:55vh;object-fit:contain;image-rendering:pixelated;background:#e9efeb;border-radius:8px}
</style>
