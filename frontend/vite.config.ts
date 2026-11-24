import { readFileSync } from 'node:fs';
import { defineConfig, type Plugin } from 'vite';
import vue from '@vitejs/plugin-vue';

function offlineAssets(buildId: string): Plugin {
  return {
    name: 'beads-offline-assets',
    apply: 'build',
    enforce: 'post',
    generateBundle(_, bundle) {
      const paths = ['/manifest.webmanifest', '/beads-192.png', '/beads-512.png'];
      for (const name of Object.keys(bundle)) {
        if (/^assets\/[a-zA-Z0-9_.-]+\.(?:js|css)$/.test(name)) paths.push('/' + name);
      }
      const worker = readFileSync(new URL('./src/offline-worker.js', import.meta.url), 'utf8');
      this.emitFile({ type: 'asset', fileName: 'service-worker.js',
        source: `const BUILD_ID = ${JSON.stringify(buildId)};\nconst STATIC_PATHS = ${JSON.stringify(paths)};\n${worker}` });
    },
  };
}

export default defineConfig(({ command }) => {
  const builtAt = new Date().toISOString();
  const info = { appId: 'beads-shadows', buildId: command === 'serve' ? 'development' : `build-${builtAt}`, builtAt };
  return {
    plugins: [vue(), offlineAssets(info.buildId), {
      name: 'beads-build-info',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify(info, null, 2) });
      },
    }],
    define: { __BEADS_BUILD_INFO__: JSON.stringify(info) },
    server: { proxy: { '/api': {
      target: process.env.BEADS_API_TARGET || 'http://127.0.0.1:8765',
      ws: true,
      rewrite: (path) => path.replace(/^\/api/, ''),
    } } },
  };
});
