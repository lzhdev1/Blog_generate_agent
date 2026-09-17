import request from '@/utils/request'

// 全部文章（公开+演示）
export function getArticles(params = {}) {
  return request.get('/articles', { params })
}

// 搜索公开文章（标题/主题模糊匹配）
export function searchArticles(q, limit = 8) {
  return request.get('/articles/search', { params: { q, limit } })
}

// 公开文章详情
export function getArticle(taskId) {
  return request.get(`/articles/${taskId}`)
}

// 点赞/取消
export function toggleLike(taskId) {
  return request.post(`/articles/${taskId}/like`)
}

// 收藏/取消
export function toggleFavorite(taskId) {
  return request.post(`/articles/${taskId}/favorite`)
}

// 付费购买（余额扣款）
export function purchaseArticle(taskId) {
  return request.post(`/articles/${taskId}/purchase`)
}

// 下载文章
export function downloadArticle(taskId) {
  return request.post(`/articles/${taskId}/download`)
}

// 我的文章（created/liked/favorited/purchased/downloaded）
export function getMyArticles(tab = 'created') {
  return request.get('/my/articles', { params: { tab } })
}

// 配置文章可见性（公开/下载/价格）
export function updateVisibility(taskId, data) {
  return request.put(`/task/${taskId}/visibility`, data)
}

// 作者本人查看完整博客（含调研/思路/审稿）
export function getBlogDetail(taskId) {
  return request.get(`/blog/${taskId}`)
}
