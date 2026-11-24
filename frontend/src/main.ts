import {createApp} from 'vue';
import App from './PlatformShell.vue';
import './style.css';
import './mobile.css';
createApp(App).mount('#app');

if (import.meta.env.PROD && 'serviceWorker' in navigator && window.isSecureContext) {
  window.addEventListener('load', () => {
    void navigator.serviceWorker.register('/service-worker.js', { updateViaCache: 'none' }).catch(() => {
      // Regular use remains available when a browser disallows offline storage.
    });
  }, { once: true });
}
