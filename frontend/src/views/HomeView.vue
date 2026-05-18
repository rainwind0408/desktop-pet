<template>
  <div class="home-view">
    <CharacterSwitcher />

    <!-- 环境状态栏 -->
    <div class="status-bar">
      <div class="status-item" v-if="environment.time">
        <span class="status-icon">&#128197;</span>
        <span>{{ environment.time.date }} {{ environment.time.weekday }} {{ environment.time.period }}</span>
      </div>
      <div class="status-item" v-if="environment.weather && environment.weather.condition !== '未知'">
        <span class="status-icon">&#127780;</span>
        <span>{{ environment.weather.condition }} {{ environment.weather.temperature }}&#8451;</span>
        <span class="status-detail">{{ environment.weather.wind }}</span>
      </div>
      <div class="status-item" v-if="environment.anniversary && environment.anniversary.days_known > 0">
        <span class="status-icon">&#10084;</span>
        <span>相识第 {{ environment.anniversary.days_known }} 天</span>
        <span class="special-day" v-if="environment.anniversary.is_special_day">
          {{ environment.anniversary.description }}
        </span>
      </div>
      <div class="status-item media-status" v-if="media.music_playing || media.video_playing">
        <span v-if="media.music_playing" class="status-icon">&#127925;</span>
        <span v-if="media.music_playing">
          {{ media.music_artist ? media.music_artist + ' - ' : '' }}{{ media.music_title || '正在播放' }}
        </span>
        <span v-if="media.video_playing" class="status-icon">&#127916;</span>
        <span v-if="media.video_playing">{{ media.video_title || '正在观看视频' }}</span>
      </div>
      <div class="status-item mood-tag" v-if="environment.mood">
        <span class="mood-indicator" :class="environment.mood.mood_tag"></span>
        <span>{{ moodText }}</span>
      </div>
    </div>

    <div class="pet-container">
      <div class="pet-display">
        <!-- Live2D 模型渲染区域 -->
        <div class="model-placeholder">宠物模型加载中...</div>
      </div>
      <div class="chat-panel">
        <div class="chat-messages" ref="chatMessages">
          <div
            v-for="(msg, index) in messages"
            :key="index"
            :class="['message', msg.role]"
          >
            <div class="message-content">{{ msg.content }}</div>
          </div>
        </div>
        <div class="chat-input">
          <el-input
            v-model="inputMessage"
            placeholder="输入消息..."
            @keyup.enter="sendMessage"
          />
          <el-button type="primary" @click="sendMessage">发送</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import CharacterSwitcher from '../components/CharacterSwitcher.vue'
import api from '../api'

const MOOD_TEXT_MAP = {
  concern_cold: '天气好冷，注意保暖',
  concern_hot: '天气炎热，注意防暑',
  gentle_rain: '外面在下雨',
  cozy_snow: '外面在下雪',
  neutral: '心情不错'
}

export default {
  name: 'HomeView',
  components: { CharacterSwitcher },
  data() {
    return {
      inputMessage: '',
      messages: [],
      environment: {},
      media: {},
      envTimer: null,
      mediaTimer: null
    }
  },
  computed: {
    moodText() {
      const tag = this.environment.mood?.mood_tag || 'neutral'
      return MOOD_TEXT_MAP[tag] || '心情不错'
    }
  },
  mounted() {
    this.fetchEnvironment()
    this.fetchMediaState()
    // 每 60 秒刷新环境，每 5 秒刷新媒体状态
    this.envTimer = setInterval(this.fetchEnvironment, 60000)
    this.mediaTimer = setInterval(this.fetchMediaState, 5000)
    // 通知后端用户活跃
    this.notifyActivity()
  },
  beforeUnmount() {
    if (this.envTimer) clearInterval(this.envTimer)
    if (this.mediaTimer) clearInterval(this.mediaTimer)
  },
  methods: {
    async fetchEnvironment() {
      try {
        this.environment = await api.getEnvironment()
      } catch (e) {
        console.error('获取环境信息失败:', e)
      }
    },
    async fetchMediaState() {
      try {
        this.media = await api.getMediaState()
      } catch (e) {
        // 媒体感知模块可能未初始化，静默失败
      }
    },
    async sendMessage() {
      if (!this.inputMessage.trim()) return

      const userMessage = this.inputMessage
      this.messages.push({ role: 'user', content: userMessage })
      this.inputMessage = ''

      // 通知后端用户活跃
      this.notifyActivity()

      try {
        const data = await api.chat(userMessage)
        this.messages.push({ role: 'assistant', content: data.response })
        this.$nextTick(() => {
          const el = this.$refs.chatMessages
          if (el) el.scrollTop = el.scrollHeight
        })
      } catch (error) {
        this.$message.error('发送消息失败')
      }
    },
    async notifyActivity() {
      try {
        await api.notifyUserInput()
      } catch (e) {
        // 静默失败
      }
    }
  }
}
</script>

<style scoped>
.home-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

/* 环境状态栏 */
.status-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 8px 20px;
  background: rgba(0, 0, 0, 0.25);
  color: rgba(255, 255, 255, 0.9);
  font-size: 13px;
  flex-wrap: wrap;
  min-height: 36px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 4px;
  white-space: nowrap;
}

.status-icon {
  font-size: 14px;
}

.status-detail {
  opacity: 0.7;
  font-size: 12px;
}

.special-day {
  color: #ffeb3b;
  font-weight: bold;
  margin-left: 4px;
}

.media-status {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.mood-tag {
  margin-left: auto;
}

.mood-indicator {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 4px;
}

.mood-indicator.concern_cold { background: #64b5f6; }
.mood-indicator.concern_hot { background: #ef5350; }
.mood-indicator.gentle_rain { background: #90caf9; }
.mood-indicator.cozy_snow { background: #e0e0e0; }
.mood-indicator.neutral { background: #81c784; }

/* 主容器 */
.pet-container {
  flex: 1;
  display: flex;
  padding: 20px;
  gap: 20px;
  min-height: 0;
}

.pet-display {
  flex: 1;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 16px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.model-placeholder {
  color: white;
  font-size: 18px;
}

/* 聊天面板 */
.chat-panel {
  width: 380px;
  background: white;
  border-radius: 16px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.chat-messages {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.message {
  max-width: 85%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.message.user {
  align-self: flex-end;
  background: #667eea;
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant {
  align-self: flex-start;
  background: #f0f0f0;
  color: #333;
  border-bottom-left-radius: 4px;
}

.chat-input {
  padding: 12px 16px;
  display: flex;
  gap: 8px;
  border-top: 1px solid #eee;
  background: #fafafa;
}
</style>
