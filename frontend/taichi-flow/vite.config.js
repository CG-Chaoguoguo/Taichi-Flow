import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'url';
var __filename = fileURLToPath(import.meta.url);
var __dirname = __filename.slice(0, __filename.lastIndexOf('/'));
export default defineConfig({
    plugins: [react()],
    base: './',
    resolve: {
        alias: {
            '@': new URL('./src', import.meta.url).pathname,
        },
    },
    server: {
        port: 5173,
        strictPort: true,
        host: '127.0.0.1',
        proxy: {
            '/api': { target: process.env.TAICHI_FLOW_API_URL || 'http://127.0.0.1:8000', changeOrigin: true },
            '/ws': { target: process.env.TAICHI_FLOW_API_URL || 'http://127.0.0.1:8000', ws: true, changeOrigin: true },
        },
    },
});
