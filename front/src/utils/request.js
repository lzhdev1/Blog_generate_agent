import axios from 'axios'
import { ElMessage } from 'element-plus'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 300000  // 5分钟，生成正文可能比较慢
})

/**
 * 判断是否为"网关超时/连接超时"类错误。
 * 这类错误通常是长任务请求（调研/生成）超过网关等待时间（如 Nginx 默认 60s）被断开，
 * 但后端任务可能仍在后台正常执行，前端应继续轮询等待结果，而不是立刻判失败。
 */
export function isTimeoutError(error) {
  return error?.response?.status === 504 ||
    error?.code === 'ECONNABORTED' ||
    /timeout|timed\s?out|gateway/i.test(error?.message || '')
}

// 请求拦截器
request.interceptors.request.use(
  config => {
    return config
  },
  error => {
    return Promise.reject(error)
  }
)

// 响应拦截器
request.interceptors.response.use(
  response => {
    return response.data
  },
  error => {
    // 超时类错误不弹全局提示：任务可能仍在后台运行，交给页面轮询兜底，避免误报失败
    if (isTimeoutError(error)) {
      return Promise.reject(error)
    }
    const message = error.response?.data?.detail || error.message || '请求失败'
    ElMessage.error(message)
    return Promise.reject(error)
  }
)

export default request
