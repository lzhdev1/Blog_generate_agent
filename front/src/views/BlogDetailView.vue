<template>
  <div class="blog-detail-view">
    <div class="blog-card animate-fade-in-up" v-loading="loading">
      <!-- 顶部操作栏 -->
      <div class="blog-toolbar">
        <button class="toolbar-btn" @click="$router.push('/')">
          <SvgIcon name="back" :size="18" />
          <span>返回列表</span>
        </button>
        <div class="toolbar-actions">
          <button class="toolbar-btn" @click="copyContent">
            <SvgIcon name="copy" :size="16" />
            <span>复制全文</span>
          </button>
          <button class="toolbar-btn primary" @click="regenerate">
            <SvgIcon name="refresh" :size="16" />
            <span>重新生成</span>
          </button>
        </div>
      </div>

      <article v-if="blog" class="blog-article">
        <header class="blog-header">
          <div class="blog-badge">
            <SvgIcon name="spark" :size="14" />
            <span>AI 生成</span>
          </div>
          <h1 class="blog-title">{{ blog.title }}</h1>
          <div class="blog-meta">
            <div class="meta-item">
              <SvgIcon name="clock" :size="14" />
              <span>{{ formatTime(blog.created_at) }}</span>
            </div>
            <div class="meta-item">
              <SvgIcon name="document" :size="14" />
              <span>约 {{ wordCount }} 字</span>
            </div>
            <div v-if="blog.image_urls?.length" class="meta-item">
              <SvgIcon name="image" :size="14" />
              <span>{{ blog.image_urls.length }} 张配图</span>
            </div>
          </div>
        </header>

        <div class="blog-divider"></div>

        <div class="blog-content">
          <MarkdownRender :content="blog.formatted_content || blog.content" />
        </div>

        <div class="blog-divider"></div>

        <footer class="blog-footer">
          <el-collapse>
            <el-collapse-item title="查看审稿记录" name="review">
              <div v-if="blog.review_feedback" class="review-content">
                <pre>{{ blog.review_feedback }}</pre>
              </div>
              <div v-else class="empty-review">无审稿记录</div>
            </el-collapse-item>
          </el-collapse>
        </footer>
      </article>

      <el-empty v-else description="文章不存在" />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import MarkdownRender from '@/components/MarkdownRender.vue'
import { getBlogDetail, generateContent } from '@/api/task'

const route = useRoute()
const router = useRouter()
const blogId = route.params.id

const loading = ref(false)
const blog = ref(null)

const wordCount = computed(() => {
  if (!blog.value?.content) return 0
  return blog.value.content.replace(/\s/g, '').length
})

async function fetchBlog() {
  loading.value = true
  try {
    blog.value = await getBlogDetail(blogId)
  } finally {
    loading.value = false
  }
}

function formatTime(timeStr) {
  if (!timeStr) return ''
  return new Date(timeStr).toLocaleString('zh-CN')
}

function copyContent() {
  const content = blog.value?.formatted_content || blog.value?.content || ''
  navigator.clipboard.writeText(content).then(() => {
    ElMessage.success('已复制到剪贴板')
  }).catch(() => {
    ElMessage.error('复制失败')
  })
}

async function regenerate() {
  try {
    await ElMessageBox.confirm('确定要重新生成文章吗？当前内容将被覆盖。', '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消'
    })
    await generateContent(blogId)
    ElMessage.success('重新生成任务已提交')
    router.push(`/task/${blogId}/generating`)
  } catch (e) {
    if (e !== 'cancel') console.error(e)
  }
}

onMounted(() => {
  fetchBlog()
})
</script>

<style scoped>
.blog-detail-view {
  max-width: 820px;
  margin: 0 auto;
}

.blog-card {
  background: white;
  border-radius: 20px;
  box-shadow: var(--shadow-md);
  overflow: hidden;
}

.blog-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 24px;
  border-bottom: 1px solid var(--border);
  background: #f8fafc;
}

.toolbar-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid var(--border);
  background: white;
  border-radius: 10px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  color: var(--text-secondary);
}

.toolbar-btn:hover {
  border-color: var(--primary);
  color: var(--primary);
}

.toolbar-btn.primary {
  background: var(--primary-gradient);
  border: none;
  color: white;
}

.toolbar-btn.primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.toolbar-actions {
  display: flex;
  gap: 8px;
}

.blog-article {
  padding: 40px 48px;
}

.blog-header {
  text-align: center;
  margin-bottom: 32px;
}

.blog-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  color: #92400e;
  border-radius: 20px;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 20px;
}

.blog-title {
  font-size: 32px;
  font-weight: 800;
  line-height: 1.4;
  margin: 0 0 20px;
  background: var(--primary-gradient);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.blog-meta {
  display: flex;
  justify-content: center;
  gap: 24px;
  flex-wrap: wrap;
}

.meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-muted);
}

.blog-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, var(--border), transparent);
  margin: 32px 0;
}

.blog-content {
  min-height: 300px;
}

.blog-footer {
  margin-top: 32px;
}

.review-content pre {
  background: #f8fafc;
  padding: 16px;
  border-radius: 10px;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-secondary);
}

.empty-review {
  text-align: center;
  color: var(--text-muted);
  padding: 20px;
}

@media (max-width: 768px) {
  .blog-article {
    padding: 24px 20px;
  }
  .blog-title {
    font-size: 24px;
  }
}
</style>
