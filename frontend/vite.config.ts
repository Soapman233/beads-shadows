import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ command }) => {
  const builtAt = new Date().toISOString();
  const info = { appId: 'beads-shadows', buildId: command === 'serve' ? 'development' : `build-${builtAt}`, builtAt };
  return {
    plugins: [vue(), {
      name: 'beads-build-info',
      generateBundle() {
        this.emitFile({ type: 'asset', fileName: 'build-info.json', source: JSON.stringify(info, null, 2) });
      },
    }],
    define: { __BEADS_BUILD_INFO__: JSON.stringify(info) },
    server: { proxy: { '/api': {
      target: process.env.BEADS_API_TARGET || 'http://127.0.0.1:8765',
      rewrite: (path) => path.replace(/^\/api/, ''),
    } } },
  };
});
