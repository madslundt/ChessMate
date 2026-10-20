import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

/** Precache only the public app shell. Account and chess data always stay server-side. */
function offlineShell(): Plugin {
  return {
    name: 'chessmate-offline-shell',
    generateBundle(_options, bundle) {
      const assets = Object.keys(bundle)
        .filter((name) => /\.(js|css)$/.test(name))
        .map((name) => '/' + name);
      this.emitFile({
        type: 'asset',
        fileName: 'precache-manifest.json',
        source: JSON.stringify(['/', '/icon.svg', '/manifest.webmanifest', ...assets]),
      });
    },
    writeBundle(options, bundle) {
      const version = createHash('sha256').update(Object.keys(bundle).sort().join('\n')).digest('hex').slice(0, 12);
      const template = readFileSync(new URL('./public/sw.js', import.meta.url), 'utf8');
      writeFileSync(resolve(options.dir || 'dist', 'sw.js'), template.replace('__BUILD_ID__', version));
    },
  };
}
export default defineConfig({
  plugins: [react(), tailwindcss(), offlineShell()],
  server: { proxy: { '/api': { target: process.env.CHESSMATE_API_TARGET || 'http://127.0.0.1:8000', changeOrigin: false } } },
});
