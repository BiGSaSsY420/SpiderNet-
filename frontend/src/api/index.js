import axios from 'axios'
import { accessKey } from '../store/accessKey'

// 创建axios实例
const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:5001',
  timeout: 300000, // 5分钟超时（本体生成可能需要较长时间）
  headers: {
    'Content-Type': 'application/json'
  }
})

// Attach the customer's access key to every request. The backend charges
// credits per operation, so an unauthenticated call is rejected with a 401.
service.interceptors.request.use(
  config => {
    if (accessKey.value) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${accessKey.value}`
    }
    return config
  },
  error => {
    console.error('Request error:', error)
    return Promise.reject(error)
  }
)

// Response interceptor
service.interceptors.response.use(
  response => {
    const res = response.data

    // The backend uses one envelope: { success, data } / { success, error }
    if (!res.success && res.success !== undefined) {
      const message = res.error || res.message || '请求失败'
      console.error('API Error:', message)
      return Promise.reject(new Error(message))
    }

    return res
  },
  error => {
    const status = error?.response?.status

    // Turn the two billing failures into messages a person can act on,
    // rather than a bare status code.
    if (status === 401) {
      error.spidernetReason = 'key'
      error.message = 'That access key was not accepted. Check it and try again.'
    } else if (status === 402) {
      error.spidernetReason = 'credits'
      error.message =
        error.response?.data?.error ||
        'You are out of credits. Add more to keep going.'
    }

    console.error('Response error:', error)
    return Promise.reject(error)
  }
)

/**
 * 判断一次失败是否可以安全重试。
 *
 * 这里的调用几乎都是非幂等的 POST（创建项目、创建模拟、启动运行、生成报告）。
 * 只有在能确定请求从未到达服务端时重试才是安全的：
 *
 * - 服务端已经回包（任何状态码）：请求已被处理。4xx 重试必然再次失败，
 *   5xx 则可能已经产生副作用，两者都不应重试。
 * - 超时：请求可能已经送达并正在处理。对创建类接口重试会产生重复资源
 *   （这正是重复模拟的来源），因此不重试。
 * - 既没有回包也不是超时：连接根本没有建立，重试是安全的。
 */
export const isRetryableError = (error) => {
  if (!error) return false
  if (error.response) return false

  const isTimeout =
    error.code === 'ECONNABORTED' ||
    error.code === 'ETIMEDOUT' ||
    /timeout/i.test(error.message || '')
  if (isTimeout) return false

  return error.code === 'ERR_NETWORK' || Boolean(error.request)
}

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms))

/**
 * 带指数退避的请求包装。
 *
 * @param {Function} requestFn  发起请求的函数
 * @param {number}   maxRetries 最多尝试次数（至少为 1）
 * @param {number}   delay      首次退避毫秒数，其后翻倍
 * @param {Object}   options    { isRetryable } 可覆盖重试判定
 */
export const requestWithRetry = async (requestFn, maxRetries = 3, delay = 1000, options = {}) => {
  const { isRetryable = isRetryableError } = options
  const attempts = Math.max(1, maxRetries)
  let lastError

  for (let i = 0; i < attempts; i++) {
    try {
      return await requestFn()
    } catch (error) {
      lastError = error

      if (i === attempts - 1 || !isRetryable(error)) {
        break
      }

      console.warn(`Request failed, retrying (${i + 1}/${attempts - 1})...`)
      await sleep(delay * Math.pow(2, i))
    }
  }

  throw lastError
}

export default service
