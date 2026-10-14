<template>
  <div class="my-articles-page">
    <div class="page-header">
      <h1>我的文章</h1>
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="我创建的" name="created" />
        <el-tab-pane label="点赞" name="liked" />
        <el-tab-pane label="收藏" name="favorited" />
        <el-tab-pane label="付费" name="purchased" />
        <el-tab-pane label="已下载" name="downloaded" />
      </el-tabs>
    </div>

    <div v-if="loading" class="empty-state">
      <el-skeleton :rows="4" animated />
    </div>

    <el-empty v-else-if="!items.length" :description="emptyText" />

    <div v-else class="article-list">
      <div v-for="a in items" :key="a.task_id" class="article-row" @click="goDetail(a.task_id)">
        <div class="row-main">
          <h3 class="row-title">{{ a.title }}</h3>
          <p class="row-topic">{{ a.topic }}</p>
        </div>
        <div class="row-meta">
          <span v-if="a.status === 'completed'" class="tag-ok">已完成</span>
          <span v-else class="tag-pending">{{ statusText(a.status) }}</span>
          <span v-if="a.purchased_price !== undefined && a.purchased_price !== null" class="tag-price">
            ¥{{ a.purchased_price }}
          </span>
          <span class="row-like"><SvgIcon name="like" :size="13" /> {{ a.like_count }}</span>
          <span class="row-time">{{ formatTime(a.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import SvgIcon from '@/components/SvgIcon.vue'
import { getMyArticles } from '@/api/article'

const router = useRouter()
const activeTab = ref('created')
const items = ref([])
const loading = ref(false)

const emptyText = computed(() => {
  const map = {
    created: '你还没有创建过文章，去创建一篇吧',
    liked: '你还没有点赞过文章',
    favorited: '你还没有收藏过文章',
    purchased: '你还没有购买过文章',
    downloaded: '你还没有下载过文章'
  }
  return map[activeTab.value] || '暂无内容'
})

async function fetchList() {
  loading.value = true
  try {
    const res = await getMyArticles(activeTab.value)
    items.value = res.items || []
  } finally {
    loading.value = false
  }
}

function handleTabChange() {
  fetchList()
}

function goDetail(taskId) {
  router.push(`/blog/${taskId}`)
}

function statusText(s) {
  const map = {
    pending: '待开始', title_generated: '已生成标题', outline_generated: '待确认大纲',
    researching_content: '调研中', generating_content: '写作中', reviewing: '审稿中',
    generating_images: '配图中', formatting: '排版中', failed: '失败'
  }
  return map[s] || s
}

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

fetchList()
</script>

<style scoped>
.my-articles-page {
  max-width: 900px;
  margin: 0 auto;
  padding: 16px 0 40px;
}

.page-header h1 {
  margin: 0 0 6px;
  font-size: 26px;
  color: var(--text-primary);
}

.article-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.article-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.article-row:hover {
  border-color: var(--primary-light);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.05);
}

.row-main {
  flex: 1;
  min-width: 0;
}

.row-title {
  margin: 0 0 4px;
  font-size: 15px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-topic {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.tag-ok {
  color: var(--success, #67c23a);
  font-weight: 600;
}

.tag-pending {
  color: var(--warning, #e6a23c);
}

.tag-price {
  color: var(--danger, #f56c6c);
  font-weight: 600;
}

.row-like {
  display: flex;
  align-items: center;
  gap: 3px;
}

.empty-state {
  padding: 20px 0;
}
</style>
