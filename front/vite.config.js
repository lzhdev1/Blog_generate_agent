import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: {
      // Docker Desktop 的 bind mount 不传递 inotify 事件，需轮询监听才能热更新
      usePolling: true,
      interval: 300
    },
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true
      },
      // 持久化配图：/images/xxx.png → 后端静态文件服务
      '/images': {
        target: 'http://backend:8000',
        changeOrigin: true
      }
    }
  }
})
