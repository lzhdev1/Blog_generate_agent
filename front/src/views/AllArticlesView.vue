<template>
  <div class="articles-page">
    <div class="page-header">
      <h1>全部文章</h1>
      <p class="page-sub">演示文章 + 用户公开的文章</p>
    </div>

    <div v-if="loading && !items.length" class="empty-state">
      <el-skeleton :rows="4" animated />
    </div>

    <el-empty v-else-if="!items.length" description="暂无公开文章" />

    <div v-else class="article-grid">
      <div v-for="a in items" :key="a.task_id" class="article-card" @click="goDetail(a.task_id)">
        <div class="card-top">
          <span class="card-type" :class="a.is_demo ? 'is-demo' : 'is-user'">
            {{ a.is_demo ? '演示' : '用户' }}
          </span>
          <span class="card-price" :class="a.download_price > 0 ? 'is-paid' : 'is-free'">
            <SvgIcon name="download" :size="12" />
            {{ a.download_price > 0 ? `¥${a.download_price}` : '免费' }}
          </span>
        </div>
        <h3 class="card-title">{{ a.title }}</h3>
        <p class="card-topic">{{ a.topic }}</p>
        <div class="card-bottom">
          <span class="card-author">
            <SvgIcon name="user" :size="13" /> {{ a.nickname || '匿名' }}
          </span>
          <span class="card-stats">
            <span class="stat">
              <SvgIcon name="like" :size="13" /> {{ a.like_count }}
            </span>
            <span class="stat">
              <SvgIcon name="star" :size="13" /> {{ a.favorite_count }}
            </span>
            <span v-if="a.allow_download || a.is_demo" class="stat">
              <SvgIcon name="download" :size="13" />
            </span>
          </span>
        </div>
      </div>
    </div>

    <div v-if="items.length && hasMore" class="load-more">
      <el-button :loading="loadingMore" @click="loadMore">加载更多</el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import SvgIcon from '@/components/SvgIcon.vue'
import { getArticles } from '@/api/article'

const router = useRouter()
const items = ref([])
const total = ref(0)
const loading = ref(false)
const loadingMore = ref(false)
const offset = ref(0)
const LIMIT = 8

const hasMore = ref(false)

async function fetchArticles(reset = false) {
  if (reset) {
    offset.value = 0
    loading.value = true
  } else {
    loadingMore.value = true
  }
  try {
    const res = await getArticles({ limit: LIMIT, offset: offset.value, random: true })
    if (reset) {
      items.value = res.items || []
    } else {
      items.value = [...items.value, ...(res.items || [])]
    }
    total.value = res.total
    offset.value += LIMIT
    hasMore.value = items.value.length < total.value
  } finally {
    loading.value = false
    loadingMore.value = false
  }
}

function loadMore() {
  fetchArticles(false)
}

function goDetail(taskId) {
  router.push(`/blog/${taskId}`)
}

onMounted(() => fetchArticles(true))
</script>

<style scoped>
.articles-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 16px 0 40px;
}

.page-header {
  margin-bottom: 24px;
}

.page-header h1 {
  margin: 0 0 6px;
  font-size: 26px;
  color: var(--text-primary);
}

.page-sub {
  margin: 0;
  color: var(--text-muted);
  font-size: 14px;
}

.article-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 18px;
}

.article-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px;
  cursor: pointer;
  transition: all 0.25s ease;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.article-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
  border-color: var(--primary-light);
}

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-type {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  font-weight: 600;
}

.card-type.is-demo {
  background: var(--bg-soft);
  color: var(--text-muted);
}

.card-type.is-user {
  background: rgba(99, 102, 241, 0.12);
  color: var(--primary);
}

.card-price {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
}

.card-price.is-free {
  background: #ecfdf5;
  color: #059669;
}

.card-price.is-paid {
  background: #fff7ed;
  color: #ea580c;
}

.card-price.is-paid svg {
  stroke: #ea580c;
}

.card-title {
  margin: 0;
  font-size: 16px;
  line-height: 1.5;
  color: var(--text-primary);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 48px;
}

.card-topic {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}

.card-author {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-secondary);
}

.card-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--text-muted);
}

.stat {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  color: var(--text-secondary);
}

.empty-state {
  padding: 20px 0;
}

.load-more {
  text-align: center;
  margin-top: 28px;
}
</style>
