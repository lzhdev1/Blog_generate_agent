<template>
  <div id="app">
    <header class="app-header">
      <div class="header-inner">
        <router-link to="/" class="logo">
          <div class="logo-icon">
            <img src="@/assets/logo.png" alt="BlogAgent" />
          </div>
        </router-link>
        <SearchBox />
        <div class="header-actions">
          <button
            class="theme-toggle"
            :title="isDark ? '切换到亮色主题' : '切换到暗色主题'"
            @click="toggleTheme"
          >
            <SvgIcon :name="isDark ? 'sun' : 'moon'" :size="18" />
          </button>
          <router-link to="/articles" class="nav-link">
            <SvgIcon name="document" :size="18" />
            <span>{{ $t('nav.allArticles') }}</span>
          </router-link>
          <button
            class="lang-toggle"
            :title="$t('nav.switchLang')"
            @click="toggleLang"
          >
            <span>{{ lang === 'zh' ? '中' : 'EN' }}</span>
          </button>
          <NotificationBell />
          <UserMenu />
        </div>
      </div>
    </header>
    <main class="app-main" :class="{ 'app-main--full': isFullWidthPage }">
      <router-view v-slot="{ Component }">
        <transition name="fade">
          <component :is="Component" />
        </transition>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import SvgIcon from '@/components/SvgIcon.vue'
import UserMenu from '@/components/UserMenu.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import SearchBox from '@/components/SearchBox.vue'
import { useAuthStore } from '@/stores/auth'
import { setLocale } from '@/i18n'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const { locale } = useI18n()
const lang = computed(() => locale.value)

function toggleLang() {
  const next = locale.value === 'zh' ? 'en' : 'zh'
  locale.value = next
  setLocale(next)
}

// ===== 明暗主题切换 =====
const THEME_KEY = 'blog-agent-theme'
const isDark = ref(false)

function applyTheme(dark) {
  const root = document.documentElement
  if (dark) {
    root.classList.add('dark') // Element Plus 暗色变量
    root.setAttribute('data-theme', 'dark') // 自定义 CSS 变量
  } else {
    root.classList.remove('dark')
    root.setAttribute('data-theme', 'light')
  }
  localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light')
}

function toggleTheme() {
  isDark.value = !isDark.value
  applyTheme(isDark.value)
}

onMounted(() => {
  // 优先读取用户选择；无记录时默认亮色（白色背景）
  const saved = localStorage.getItem(THEME_KEY)
  isDark.value = saved ? saved === 'dark' : false
  applyTheme(isDark.value)
})

// 文章详情页和大纲确认页需要全宽三栏布局，突破 app-main 的 1200px 限制
const isFullWidthPage = computed(() => {
  return route.path.startsWith('/blog/') || /\/task\/\d+\/outline/.test(route.path)
})
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  background: var(--header-bg);
  backdrop-filter: blur(20px) saturate(160%);
  -webkit-backdrop-filter: blur(20px) saturate(160%);
  border-bottom: 1px solid var(--border);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
}

.header-inner {
  position: relative;
  width: 100%;
  max-width: none;
  margin: 0;
  height: 68px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
}

.header-inner > .search-box {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
  width: min(460px, 42vw);
  margin: 0;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
}

.logo-icon {
  height: 44px;
  flex-shrink: 0;
}

.logo-icon img {
  height: 100%;
  width: auto;
  display: block;
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
  background: var(--bg-soft);
  color: var(--text-primary);
}

/* 主题切换按钮 */
.theme-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.theme-toggle:hover {
  color: var(--text-primary);
  background: var(--bg-soft);
  transform: translateY(-1px);
}

.lang-toggle {
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 38px;
  height: 38px;
  padding: 0 8px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
}

.lang-toggle:hover {
  color: var(--text-primary);
  background: var(--bg-soft);
}

.app-main {
  max-width: 1200px;
  margin: 0 auto;
  padding: 32px 24px;
  min-height: calc(100vh - 68px);
}

/* 文章详情页：全宽三栏布局 */
.app-main--full {
  max-width: none;
  padding: 24px 0 40px;
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

/* ===== 移动端适配（<640px）===== */
@media (max-width: 640px) {
      .header-inner {
    display: flex;
    justify-content: space-between;
    align-items: center;
    height: 56px;
    padding: 0 12px;
    gap: 6px;
  }
  .logo-icon {
    height: 28px;
  }

  .header-actions {
    gap: 2px;
    flex-shrink: 1;
    min-width: 0;
  }

  /* 窄屏隐藏"全部文章"文字，只留图标 */
  .nav-link span {
    display: none;
  }

  .nav-link {
    padding: 6px 6px;
    font-size: 13px;
  }

  .theme-toggle,
  .lang-toggle {
    width: 30px;
    height: 30px;
    min-width: 30px;
  }

  .app-main {
    padding: 20px 16px;
  }

  .app-main--full {
    padding: 16px 0 32px;
  }
}
</style>
