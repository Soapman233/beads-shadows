import { DEFAULT_TARGET, parseTarget } from './target.js';

const target = document.querySelector('#target');
const status = document.querySelector('[role=status]');
const form = document.querySelector('form');
const button = form.querySelector('button');
const saved = await chrome.storage.local.get('target');
target.value = saved.target || DEFAULT_TARGET;
const previous = await chrome.storage.session.get('message');
status.textContent = previous.message ?? '';

form.addEventListener('submit', async event => {
  event.preventDefault();
  button.disabled = true;
  try {
    const next = parseTarget(target.value);
    if (!await chrome.permissions.request({ origins: [next.permission] })) throw new Error('未授权访问此地址。');
    const old = await chrome.storage.local.get('target');
    await chrome.storage.local.set({ target: next.origin });
    if (old.target) {
      const last = parseTarget(old.target);
      if (last.permission !== next.permission) await chrome.permissions.remove({ origins: [last.permission] });
    }
    target.value = next.origin;
    await chrome.storage.session.remove('message');
    await chrome.action.setBadgeText({ text: '' });
    status.textContent = '地址已保存。';
  } catch (error) {
    status.textContent = error instanceof Error ? error.message : '无法保存地址。';
  } finally {
    button.disabled = false;
  }
});
