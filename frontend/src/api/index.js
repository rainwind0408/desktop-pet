/**
 * API 统一配置
 */
import axios from 'axios'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

apiClient.interceptors.response.use(
  response => response.data,
  error => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export default {
  // 角色管理
  getCharacters() {
    return apiClient.get('/characters')
  },
  getCurrentCharacter() {
    return apiClient.get('/character/current')
  },
  switchCharacter(characterId) {
    return apiClient.post('/character/switch', { characterId })
  },
  saveCharacter(characterData) {
    return apiClient.post('/character/save', characterData)
  },
  chat(message) {
    return apiClient.post('/character/chat', { message })
  },

  // 环境感知
  getEnvironment() {
    return apiClient.get('/environment')
  },
  refreshWeather() {
    return apiClient.post('/environment/weather/refresh')
  },

  // 媒体感知
  getMediaState() {
    return apiClient.get('/media/state')
  },
  getMediaSummary() {
    return apiClient.get('/media/summary')
  },

  // 交互决策
  getInteractionDecision() {
    return apiClient.get('/interaction/decide')
  },
  notifyUserInput() {
    return apiClient.post('/interaction/input')
  },
  getInteractionStatus() {
    return apiClient.get('/interaction/status')
  },

  // 记忆系统
  getMemoryStats() {
    return apiClient.get('/memory/stats')
  },

  // LLM 配置
  getLLMConfig() {
    return apiClient.get('/config/llm')
  },
  getLLMProviders() {
    return apiClient.get('/config/llm/providers')
  },
  updateLLMConfig(config) {
    return apiClient.post('/config/llm', config)
  },

  // 健康检查
  getHealth() {
    return apiClient.get('/health')
  }
}
