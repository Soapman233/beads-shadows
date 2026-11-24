<script setup lang="ts">
import { onMounted, ref } from "vue";
import { jsonRequest, platformApi, type AccountSession } from "./platformApi";
type Sku = { id: string; title: string; code: string; brand: string; hex: string; piecesPerPack: number; availablePacks: number; priceCents: number; active: boolean };
type Plan = { id: string; title: string; priceCents: number; durationDays: number; benefits: string[] };
type Order = { id: string; status: string; totalCents: number; simulation: boolean; trackingReference?: string; items: { title: string; packs: number }[] };
type Cart = { items: (Sku & { packs: number })[]; totalCents: number };
type Shortage = { code: string; beadsNeeded: number; skuId: string | null; packs: number | null; availablePacks: number; canAdd: boolean };
const props = defineProps<{ session: AccountSession }>();
const call = <T,>(path: string, options?: RequestInit) => platformApi<T>(path, options, props.session);
const busy = ref(false), error = ref(""), simulation = ref(false), tab = ref("shop");
const skus = ref<Sku[]>([]), plans = ref<Plan[]>([]), cart = ref<Cart>({ items: [], totalCents: 0 }), orders = ref<Order[]>([]);
const memberships = ref<{ id: string; active: boolean; expiresAt: string; plan: Plan }[]>([]);
const projects = ref<{ id: string; name: string }[]>([]), projectId = ref(""), reserve = ref(5);
const shortage = ref<Shortage[]>([]), checked = ref<{ projectId: string; revision: number; reservePercent: number }>();
const versions = ref<{ id: string; brand: string; version: string }[]>([]), versionId = ref("");
const colors = ref<{ code: string; stableColorKey: string }[]>([]);
const sku = ref({ stableColorKey: "", title: "", piecesPerPack: 100, priceCents: 100, availablePacks: 10 });
const plan = ref({ title: "", durationDays: 30, priceCents: 100, benefits: "" });
const tracking = ref(""), member = ref(""), selectedPlan = ref("");
const pendingKey = "bead-shop-pending:" + props.session.user?.id;
const states: Record<string, string> = { awaiting_payment: "待模拟支付", paid: "已模拟支付", failed: "未支付", canceled: "已取消",
  expired: "已过期", refund_requested: "退款待处理", refunded: "已模拟退款", shipped: "已登记发货" };
const price = (cents: number) => "¥" + (cents / 100).toFixed(2);
async function work(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); } catch (e) { error.value = (e as Error).message; }
  finally { busy.value = false; }
}
async function refresh() {
  const admin = tab.value === "manage";
  const [status, listing, packages, accountOrders, basket, perks] = await Promise.all([
    call<{ simulationEnabled: boolean }>("/shop/status"),
    call<{ items: Sku[] }>(admin ? "/admin/shop/skus" : "/shop/skus"),
    call<{ items: Plan[] }>("/shop/plans"),
    call<{ items: Order[] }>(admin ? "/admin/shop/orders" : "/shop/orders"),
    call<Cart>("/shop/cart"), call<{ items: typeof memberships.value }>("/shop/memberships"),
  ]);
  simulation.value = status.simulationEnabled; skus.value = listing.items; plans.value = packages.items;
  orders.value = accountOrders.items; cart.value = basket; memberships.value = perks.items;
}
onMounted(() => work(async () => {
  await refresh();
  projects.value = (await call<{ items: typeof projects.value }>("/projects")).items;
  projectId.value = projects.value[0]?.id ?? "";
}));
async function setTab(next: string) {
  tab.value = next;
  await refresh();
  if (next === "manage") versions.value = await call<typeof versions.value>("/palettes");
}
async function loadColors() {
  colors.value = versionId.value ? (await call<{ colors: typeof colors.value }>("/palettes/" + versionId.value)).colors : [];
  sku.value.stableColorKey = "";
}
async function changeQuantity(id: string, packs: number) {
  cart.value = await call<Cart>("/shop/cart/" + id, jsonRequest("PUT", { packs }));
}
async function calculate() {
  const { version } = await call<{ version: { revision: number } }>("/projects/" + projectId.value);
  checked.value = { projectId: projectId.value, revision: version.revision, reservePercent: reserve.value };
  shortage.value = (await call<{ items: Shortage[] }>("/shop/cart/shortages", jsonRequest("POST", checked.value))).items;
}
async function addShortage() {
  if (!checked.value) return;
  const result = await call<{ items: Shortage[]; cart: Cart }>("/shop/cart/shortages",
    jsonRequest("POST", { ...checked.value, apply: true }));
  shortage.value = result.items; cart.value = result.cart;
}
async function checkout(planId?: string) {
  const stored = sessionStorage.getItem(pendingKey);
  const prior = stored ? JSON.parse(stored) as { requestId: string; planId?: string } : undefined;
  if (prior && prior.planId !== planId) throw Error("请先核对之前的订单提交");
  const request = prior ?? { requestId: crypto.randomUUID(), planId };
  sessionStorage.setItem(pendingKey, JSON.stringify(request));
  try { await call("/shop/orders", jsonRequest("POST", request)); }
  catch (e) {
    if ([400, 401, 403, 404, 409, 422].includes((e as { status?: number }).status ?? 0)) sessionStorage.removeItem(pendingKey);
    throw e;
  }
  sessionStorage.removeItem(pendingKey);
  await refresh();
}
async function orderAction(order: Order, action: string, admin = false, body?: unknown) {
  await call((admin ? "/admin" : "") + "/shop/orders/" + order.id + "/" + action, body ? jsonRequest("POST", body) : { method: "POST" });
  await refresh();
}
async function grantMembership() {
  const user = await call<{ id: string }>("/people/" + encodeURIComponent(member.value));
  await call("/admin/shop/memberships", jsonRequest("POST", { userId: user.id, planId: selectedPlan.value }));
  error.value = "权益已发放";
}
async function createPlan() {
  const benefits = plan.value.benefits.split(/[,，\n]/).map(label => label.trim()).filter(Boolean);
  await call("/admin/shop/plans", jsonRequest("POST", { ...plan.value, benefits }));
  await refresh();
}
</script>
<template>
  <section class="platform-panel panel">
    <h2>材料商城</h2>
    <p>{{ simulation ? "模拟交易环境 · 不产生扣款" : "商品目录 · 交易暂未启用" }}</p>
    <div class="platform-tools">
      <button :disabled="busy" @click="work(() => setTab('shop'))">商品与购物车</button>
      <button :disabled="busy" @click="work(() => setTab('orders'))">订单与会员</button>
      <button v-if="session.user?.role === 'admin'" :disabled="busy" @click="work(() => setTab('manage'))">商城管理</button>
    </div>
    <template v-if="tab === 'shop'">
      <div v-for="row in skus" :key="row.id" class="platform-tools">
        <span :style="{background:row.hex,width:'1rem',height:'1rem',border:'1px solid #99a99e'}"></span>
        <strong>{{ row.title }}</strong><span>{{ row.brand }} {{ row.code }} · {{ row.piecesPerPack }} 颗/包 · {{ price(row.priceCents) }} · 余 {{ row.availablePacks }} 包</span>
        <button :disabled="busy || !row.availablePacks" @click="work(() => changeQuantity(row.id, (cart.items.find(item => item.id === row.id)?.packs ?? 0) + 1))">加一包</button>
      </div>
      <h3>缺料转购物车</h3>
      <form class="platform-tools" @submit.prevent="work(calculate)">
        <label>项目 <select v-model="projectId" @change="checked = undefined; shortage = []"><option v-for="row in projects" :key="row.id" :value="row.id">{{ row.name }}</option></select></label>
        <label>余量 % <input v-model.number="reserve" type="number" min="0" max="100" @input="checked = undefined; shortage = []" /></label>
        <button :disabled="busy || !projectId">预览</button>
      </form>
      <p v-for="row in shortage" :key="row.code">{{ row.code }} 缺 {{ row.beadsNeeded }} 颗 · {{ row.packs ? row.packs + " 包" : "无同色商品" }}{{ row.skuId && !row.canAdd ? " · 库存不足" : "" }}</p>
      <button v-if="checked && shortage.some(row => row.canAdd)" :disabled="busy" @click="work(addShortage)">加入可备料商品</button>
      <h3>购物车</h3>
      <div v-for="row in cart.items" :key="row.id" class="platform-tools">
        <span>{{ row.title }} × {{ row.packs }}</span>
        <button :disabled="busy" @click="work(() => changeQuantity(row.id, row.packs - 1))">减一包</button>
        <button :disabled="busy" @click="work(() => changeQuantity(row.id, 0))">移除</button>
      </div>
      <p>合计 {{ price(cart.totalCents) }}</p>
      <button v-if="simulation" class="primary" :disabled="busy || !cart.items.length" @click="work(() => checkout())">创建模拟订单</button>
    </template>
    <template v-if="tab === 'manage'">
      <form class="platform-form" @submit.prevent="work(async () => { await call('/admin/shop/skus', jsonRequest('POST', sku)); await refresh(); })">
        <h3>新建商品</h3>
        <label>色卡 <select v-model="versionId" @change="work(loadColors)"><option value="">选择色卡</option><option v-for="v in versions" :key="v.id" :value="v.id">{{ v.brand }} · {{ v.version }}</option></select></label>
        <label>颜色 <select v-model="sku.stableColorKey" required><option v-for="c in colors" :key="c.code" :value="c.stableColorKey">{{ c.code }}</option></select></label>
        <label>商品名 <input v-model="sku.title" required /></label>
        <label>每包颗数 <input v-model.number="sku.piecesPerPack" type="number" min="1" required /></label>
        <label>每包价格（分） <input v-model.number="sku.priceCents" type="number" min="1" required /></label>
        <label>可售包数 <input v-model.number="sku.availablePacks" type="number" min="0" required /></label>
        <button :disabled="busy">保存商品</button>
      </form>
      <div v-for="row in skus" :key="row.id" class="platform-tools">
        <span>{{ row.title }}</span>
        <label>可售包数 <input v-model.number="row.availablePacks" type="number" min="0" /></label>
        <label>单价（分） <input v-model.number="row.priceCents" type="number" min="1" /></label>
        <button :disabled="busy" @click="work(async () => { await call('/admin/shop/skus/' + row.id, jsonRequest('PATCH', { availablePacks: row.availablePacks, priceCents: row.priceCents })); await refresh(); })">更新</button>
        <button :disabled="busy" @click="work(async () => { await call('/admin/shop/skus/' + row.id, jsonRequest('PATCH', { active: !row.active })); await refresh(); })">{{ row.active ? "下架" : "上架" }}</button>
      </div>
      <form class="platform-form" @submit.prevent="work(createPlan)">
        <h3>新建会员套餐</h3>
        <label>名称 <input v-model="plan.title" required /></label><label>权益 <input v-model="plan.benefits" required /></label>
        <label>天数 <input v-model.number="plan.durationDays" type="number" min="1" required /></label>
        <label>价格（分） <input v-model.number="plan.priceCents" type="number" min="1" required /></label>
        <button :disabled="busy">创建套餐</button>
      </form>
      <form class="platform-tools" @submit.prevent="work(grantMembership)">
        <input v-model="member" aria-label="受益人账号" placeholder="账号" required />
        <select v-model="selectedPlan" aria-label="会员套餐" required><option v-for="p in plans" :key="p.id" :value="p.id">{{ p.title }}</option></select>
        <button :disabled="busy">发放权益</button>
      </form>
      <label>模拟物流单号 <input v-model="tracking" maxlength="80" /></label>
    </template>
    <template v-if="tab === 'orders' || tab === 'manage'">
      <h3>订单</h3>
      <p v-if="!orders.length">暂无订单</p>
      <div v-for="row in orders" :key="row.id" class="platform-tools">
        <strong>{{ price(row.totalCents) }} · {{ states[row.status] ?? row.status }}</strong>
        <span v-for="item in row.items" :key="item.title">{{ item.title }} × {{ item.packs }}</span>
        <span v-if="row.trackingReference">{{ row.trackingReference }}</span>
        <template v-if="tab === 'orders' && row.status === 'awaiting_payment'">
          <button v-if="simulation && row.simulation" :disabled="busy" @click="work(() => orderAction(row, 'simulate-payment', false, {scenario:'paid'}))">模拟支付</button>
          <button :disabled="busy" @click="work(() => orderAction(row, 'cancel'))">取消</button>
        </template>
        <button v-if="tab === 'orders' && row.status === 'paid'" :disabled="busy" @click="work(() => orderAction(row, 'refund'))">申请退款</button>
        <button v-if="tab === 'manage' && row.status === 'refund_requested' && simulation" :disabled="busy" @click="work(() => orderAction(row, 'refund', true))">确认模拟退款</button>
        <button v-if="tab === 'manage' && row.status === 'paid' && row.items.length" :disabled="busy || !tracking.trim()" @click="work(() => orderAction(row, 'ship', true, {trackingReference:tracking}))">登记模拟发货</button>
      </div>
    </template>
    <template v-if="tab === 'orders'">
      <h3>会员权益</h3>
      <p v-for="row in memberships" :key="row.id">{{ row.plan.title }} · {{ row.active ? "有效" : "失效" }} · {{ row.expiresAt }}</p>
      <div v-for="row in plans" :key="row.id" class="platform-tools">
        <strong>{{ row.title }} · {{ row.durationDays }} 天 · {{ price(row.priceCents) }}</strong><span>{{ row.benefits.join("、") }}</span>
        <button v-if="simulation" :disabled="busy" @click="work(() => checkout(row.id))">创建会员模拟订单</button>
      </div>
    </template>
    <p v-if="error" role="status">{{ error }}</p>
  </section>
</template>
