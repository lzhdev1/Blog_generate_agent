<template>
  <div id="app">
    <header class="app-header">
      <div class="header-inner">
        <router-link to="/" class="logo">
          <div class="logo-icon">
            <SvgIcon name="magic" :size="24" />
          </div>
          <div class="logo-text">
            <span class="logo-title">BlogAgent</span>
            <span class="logo-subtitle">AI 博客生成器</span>
          </div>
        </router-link>
        <div class="header-actions">
          <a href="#" class="nav-link" @click.prevent="scrollToArticles">
            <SvgIcon name="document" :size="18" />
            <span>我的文章</span>
          </a>
          <router-link to="/create" class="create-btn">
            <SvgIcon name="plus" :size="18" />
            <span>创建新文章</span>
          </router-link>
        </div>
      </div>
    </header>
    <main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { useRouter, useRoute } from 'vue-router'
import SvgIcon from '@/components/SvgIcon.vue'

const router = useRouter()
const route = useRoute()

function scrollToArticles() {
  if (route.path === '/') {
    // 已经在首页，滚动到文章列表
    const el = document.getElementById('articles-section')
    if (el) {
      el.scrollIntoView({ behavior: 'smooth' })
    }
  } else {
    // 不在首页，先跳转到首页，然后滚动
    router.push('/')
    setTimeout(() => {
      const el = document.getElementById('articles-section')
      if (el) {
        el.scrollIntoView({ behavior: 'smooth' })
      }
    }, 300)
  }
}
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--border);
}

.header-inner {
  max-width: 1200px;
  margin: 0 auto;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
}

.logo-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--primary-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.logo-text {
  display: flex;
  flex-direction: column;
}

.logo-title {
  font-size: 18px;
  font-weight: 700;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  line-height: 1.2;
}

.logo-subtitle {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.2;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.nav-link {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s ease;
}

.nav-link:hover {
  background: #f1f5f9;
  color: var(--text-primary);
}

.create-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 20px;
  border-radius: 10px;
  background: var(--primary-gradient);
  color: white;
  font-size: 14px;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
  transition: all 0.3s ease;
}

.create-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}

.app-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
  min-height: calc(100vh - 68px);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fade-enter-from {
  opacity: 0;
  transform: translateY(10px);
}

.fade-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
