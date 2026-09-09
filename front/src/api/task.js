import request from '@/utils/request'

// 创建任务
export function createTask(data) {
  return request.post('/task', data)
}

// 生成标题
export function generateTitles(taskId) {
  return request.post(`/task/${taskId}/generate-titles`)
}

// 提交标题配置
export function submitTitleConfig(taskId, data) {
  return request.post(`/task/${taskId}/submit-title-config`, data)
}

// 重新生成大纲
export function regenerateOutline(taskId) {
  return request.post(`/task/${taskId}/regenerate-outline`)
}

// 确认大纲（可传入修改后的大纲）
export function confirmOutline(taskId, outline = null) {
  return request.post(`/task/${taskId}/confirm-outline`, { outline })
}

// 生成正文
export function generateContent(taskId) {
  return request.post(`/task/${taskId}/generate-content`)
}

// 获取任务详情
export function getTask(taskId) {
  return request.get(`/task/${taskId}`)
}

// 获取任务列表
export function getTaskList(params) {
  return request.get('/task', { params })
}

// 删除任务
export function deleteTask(taskId) {
  return request.delete(`/task/${taskId}`)
}

// 获取博客详情
export function getBlogDetail(blogId) {
  return request.get(`/blog/${blogId}`)
}
