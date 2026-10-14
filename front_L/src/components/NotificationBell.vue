<template>
  <div v-if="authStore.isLoggedIn" ref="wrapRef" class="notify-wrap">
    <button class="notify-btn" :title="$t('notify.title')" @click="togglePanel">
      <SvgIcon name="bell" :size="19" />
      <span v-if="unread > 0" class="notify-badge">{{ unread > 99 ? '99+' : unread }}</span>
    </button>

    <transition name="fade">
      <div v-if="showPanel" class="notify-panel" @click.stop>
        <div class="notify-header">
          <span class="notify-header-title">{{ $t('notify.title') }}</span>
          <button v-if="unread > 0" class="notify-read-all" @click="readAll">
            {{ $t('notify.readAll') }}
          </button>
        </div>
        <div v-if="loading" class="notify-empty">{{ $t('notify.loading') }}</div>
        <div v-else-if="items.length === 0" class="notify-empty">{{ $t('notify.empty') }}</div>
        <div v-else class="notify-list">
          <div
            v-for="n in items"
            :key="n.id"
            class="notify-item"
            :class="{ unread: !n.is_read }"
            @click="openItem(n)"
          >
            <span class="notify-icon" :class="n.type">
              <SvgIcon :name="iconName(n.type)" :size="15" />
            </span>
            <div class="notify-body">
              <div class="notify-content">{{ n.content }}</div>
              <div class="notify-time">{{ n.created_at }}</div>
            </div>
            <span v-if="!n.is_read" class="notify-dot"></span>
          </div>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRouter } from 'vue-router'
import SvgIcon from '@/components/SvgIcon.vue'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'

const router = useRouter()
const authStore = useAuthStore()

const wrapRef = ref(null)
const showPanel = ref(false)
const loading = ref(false)
const unread = ref(0)
const items = ref([])
let timer = null

function iconName(type) {
  if (type === 'like') return 'like'
  if (type === 'favorite') return 'star'
  if (type === 'purchase') return 'coin'
  return 'spark'
}

async function fetchUnread() {
  if (!authStore.isLoggedIn) return
  try {
    const data = await request.get('/notifications/unread-count')
    unread.value = data.unread || 0
  } catch (e) {}
}

async function fetchList() {
  if (!authStore.isLoggedIn) return
  loading.value = true
  try {
    const data = await request.get('/notifications?limit=30')
    items.value = data.items || []
    unread.value = data.unread || 0
  } catch (e) {
  } finally {
    loading.value = false
  }
}

function togglePanel() {
  showPanel.value = !showPanel.value
  if (showPanel.value) fetchList()
}

async function readAll() {
  try {
    await request.post('/notifications/read', {})
    unread.value = 0
    items.value = items.value.map((n) => ({ ...n, is_read: true }))
  } catch (e) {}
}

async function openItem(n) {
  if (!n.is_read) {
    try {
      await request.post('/notifications/read', { ids: [n.id] })
      n.is_read = true
      unread.value = Math.max(0, unread.value - 1)
    } catch (e) {}
  }
  showPanel.value = false
  if (n.task_id) router.push(`/blog/${n.task_id}`)
}

function onDocClick(e) {
  if (wrapRef.value && !wrapRef.value.contains(e.target)) {
    showPanel.value = false
  }
}

watch(() => authStore.isLoggedIn, (v) => {
  if (v) {
    fetchUnread()
  } else {
    unread.value = 0
    items.value = []
    showPanel.value = false
  }
})

onMounted(() => {
  fetchUnread()
  timer = setInterval(fetchUnread, 30000)
  document.addEventListener('click', onDocClick)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  document.removeEventListener('click', onDocClick)
})
</script>

<style scoped>
.notify-wrap {
  position: relative;
  display: flex;
  align-items: center;
}

.notify-btn {
  position: relative;
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

.notify-btn:hover {
  color: var(--text-primary);
  background: var(--bg-soft);
}

.notify-badge {
  position: absolute;
  top: 2px;
  right: 0;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #ef4444;
  color: #fff;
  font-size: 10px;
  font-weight: 600;
  line-height: 16px;
  text-align: center;
}

.notify-panel {
  position: absolute;
  top: 46px;
  right: 0;
  width: 340px;
  max-height: 420px;
  display: flex;
  flex-direction: column;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-xl);
  z-index: 200;
  overflow: hidden;
}

.notify-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid var(--border);
}

.notify-header-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-primary);
}

.notify-read-all {
  border: none;
  background: transparent;
  color: var(--primary);
  font-size: 13px;
  cursor: pointer;
}

.notify-read-all:hover {
  text-decoration: underline;
}

.notify-list {
  overflow-y: auto;
  flex: 1;
}

.notify-item {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.15s ease;
}

.notify-item:hover {
  background: var(--bg-soft);
}

.notify-item.unread {
  background: rgba(99, 102, 241, 0.06);
}

.notify-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  flex-shrink: 0;
}

.notify-icon.like {
  background: rgba(239, 68, 68, 0.12);
  color: #ef4444;
}

.notify-icon.favorite {
  background: rgba(245, 158, 11, 0.12);
  color: #f59e0b;
}

.notify-icon.purchase {
  background: rgba(99, 102, 241, 0.12);
  color: #6366f1;
}

.notify-icon.system {
  background: rgba(16, 185, 129, 0.12);
  color: #10b981;
}

.notify-body {
  flex: 1;
  min-width: 0;
}

.notify-content {
  font-size: 13.5px;
  color: var(--text-primary);
  line-height: 1.5;
  word-break: break-all;
}

.notify-time {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-muted);
}

.notify-dot {
  position: absolute;
  top: 18px;
  right: 14px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--primary);
}

.notify-empty {
  padding: 40px 16px;
  text-align: center;
  font-size: 13.5px;
  color: var(--text-muted);
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ===== 移动端适配（<640px）===== */
@media (max-width: 640px) {
  .notify-btn {
    width: 30px;
    height: 30px;
  }

  .notify-panel {
    width: min(340px, calc(100vw - 24px));
    right: -40px;
  }
}
</style>
