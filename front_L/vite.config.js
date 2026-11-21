import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// Docker resolves the service name. Local development can point to a host backend.
const apiTarget = process.env.BLOG_AGENT_API_TARGET || 'http://127.0.0.1:8001'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    host: '127.0.0.1',
    port: 5174,
    // Docker 容器网络内（服务名访问）也放行，便于容器内联调
    allowedHosts: ['frontendl'],
    watch: {
      // Docker Desktop 的 bind mount 不传递 inotify 事件，需轮询监听才能热更新
      usePolling: true,
      interval: 300
    },
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true
      },
      // 持久化配图：/images/xxx.png → 后端静态文件服务
      '/images': {
        target: apiTarget,
        changeOrigin: true
      }
    }
  }
})
