import { parseTarget } from './target.js';

const MENU = 'share-to-beads';
const MAX_BYTES = 10 * 1024 * 1024;
let importing = false;

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    if (!chrome.runtime.lastError) chrome.contextMenus.create({ id: MENU, title: '导入豆影', contexts: ['image'] });
  });
});

// Invoked only for the explicitly selected image. Runs in the source frame
// with normal page CORS and without sending browser credentials.
async function readSelectedImage(source, origin, limit) {
  if (location.origin !== origin) throw new Error('图片页面已变化');
  const url = new URL(source, location.href);
  if (!['https:', 'http:', 'blob:', 'data:'].includes(url.protocol) || url.username || url.password) {
    throw new Error('图片地址不受支持');
  }
  if (source.length > limit * 2) throw new Error('图片超过大小限制');
  const response = await fetch(url, { credentials: 'omit', redirect: 'error', referrerPolicy: 'no-referrer',
    signal: AbortSignal.timeout(12000) });
  if (!response.ok || !response.body) throw new Error('无法读取图片');
  const type = (response.headers.get('content-type') || '').split(';')[0].toLowerCase();
  if (!['image/png', 'image/jpeg'].includes(type) || Number(response.headers.get('content-length')) > limit) {
    throw new Error('仅支持 10MB 以内的 PNG/JPG');
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  for (;;) {
    const part = await reader.read();
    if (part.done) break;
    size += part.value.byteLength;
    if (size > limit) {
      await reader.cancel();
      throw new Error('图片超过大小限制');
    }
    chunks.push(part.value);
  }
  if (!size) throw new Error('图片为空');
  const dataUrl = await new Promise((resolve, reject) => {
    const file = new FileReader();
    file.onload = () => resolve(file.result);
    file.onerror = reject;
    file.readAsDataURL(new Blob(chunks, { type }));
  });
  return { dataUrl, type };
}

async function shareIntoWorkspace(origin, image, sourceOrigin, requestId) {
  if (location.origin !== origin || !['/', '/index.html'].includes(location.pathname)) return false;
  const fileBlob = await (await fetch(image.dataUrl)).blob();
  const file = new File([fileBlob], image.type === 'image/png' ? 'image.png' : 'image.jpg', { type: image.type });
  return new Promise(resolve => {
    let sent = false;
    const finish = accepted => {
      clearInterval(interval);
      clearTimeout(timeout);
      window.removeEventListener('message', receive);
      resolve(accepted);
    };
    const receive = event => {
      if (event.origin !== origin || event.source !== window || event.data?.version !== 1 || event.data?.requestId !== requestId) return;
      if (event.data.type === 'bead-extension:ready' && !sent) {
        sent = true;
        window.postMessage({ type: 'bead-extension:import', version: 1, requestId, file, sourceOrigin }, origin);
      } else if (event.data.type === 'bead-extension:received' && sent) {
        finish(true);
      }
    };
    const probe = () => {
      if (!sent) window.postMessage({ type: 'bead-extension:probe', version: 1, requestId }, origin);
    };
    const interval = setInterval(probe, 350);
    const timeout = setTimeout(() => finish(false), 8000);
    window.addEventListener('message', receive);
    probe();
  });
}

function waitForPage(id) {
  return new Promise((resolve, reject) => {
    const finish = error => {
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(update);
      chrome.tabs.onRemoved.removeListener(remove);
      if (error) reject(error); else resolve();
    };
    const update = (tabId, change) => {
      if (id === tabId && change.status === 'complete') finish();
    };
    const remove = tabId => {
      if (id === tabId) finish(new Error('目标页面已关闭'));
    };
    const timer = setTimeout(() => finish(new Error('目标页面等待超时')), 12000);
    chrome.tabs.onUpdated.addListener(update);
    chrome.tabs.onRemoved.addListener(remove);
    chrome.tabs.get(id).then(tab => { if (tab.status === 'complete') finish(); }, finish);
  });
}

async function report(message, error = false) {
  await chrome.storage.session.set({ message });
  await chrome.action.setBadgeText({ text: error ? '!' : '' });
  if (error) await chrome.runtime.openOptionsPage();
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (info.menuItemId !== MENU || importing || !info.srcUrl || tab?.id === undefined) return;
  importing = true;
  try {
    const { target } = await chrome.storage.local.get('target');
    if (!target) { await report('请先保存豆影服务地址，再选择图片。', true); return; }
    const { origin, permission } = parseTarget(target);
    if (!await chrome.permissions.contains({ origins: [permission] })) {
      await report('请在设置中重新授权豆影服务地址。', true);
      return;
    }
    const frame = new URL(info.frameUrl || info.pageUrl);
    if (!['https:', 'http:'].includes(frame.protocol)) throw new Error('页面不受支持');
    const [entry] = await chrome.scripting.executeScript({ target: { tabId: tab.id, frameIds: [info.frameId ?? 0] },
      func: readSelectedImage, args: [info.srcUrl, frame.origin, MAX_BYTES] });
    if (!entry?.result?.dataUrl) throw new Error('图片未读取');
    const targetTab = await chrome.tabs.create({ url: origin + '/' });
    await waitForPage(targetTab.id);
    const [delivery] = await chrome.scripting.executeScript({ target: { tabId: targetTab.id }, func: shareIntoWorkspace,
      args: [origin, entry.result, frame.origin, crypto.randomUUID()] });
    if (!delivery?.result) throw new Error('目标未确认接收');
    await report('已交给豆影，请在豆影页面确认导入。');
  } catch {
    await report('无法直接导入。请检查豆影地址和图片权限，或在豆影中选择本机 PNG/JPG 文件。', true);
  } finally {
    importing = false;
  }
});
