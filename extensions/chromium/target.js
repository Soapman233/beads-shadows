export const DEFAULT_TARGET = 'http://127.0.0.1:8765';

export function parseTarget(input) {
  let url;
  try { url = new URL(input.trim()); }
  catch { throw new Error('请输入完整服务地址，例如 ' + DEFAULT_TARGET); }
  const isLocal = url.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(url.hostname);
  if ((!isLocal && url.protocol !== 'https:') || url.username || url.password
      || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('请输入本机 HTTP 或 HTTPS 服务的根地址。');
  }
  return { origin: url.origin, permission: `${url.protocol}//${url.hostname}/*` };
}
