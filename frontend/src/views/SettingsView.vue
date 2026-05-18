<template>
  <div class="settings-view">
    <h2>角色设置</h2>
    <div class="model-preview">
      <div class="preview-placeholder">模型预览区域</div>
    </div>
    <div class="settings-form">
      <el-form :model="character" label-width="100px">
        <el-form-item label="角色名称">
          <el-input v-model="character.name" />
        </el-form-item>
        <el-form-item label="角色描述">
          <el-input v-model="character.description" type="textarea" />
        </el-form-item>
        <el-form-item label="AI人设">
          <el-input
            v-model="character.personality.prompt"
            type="textarea"
            :rows="4"
          />
        </el-form-item>
      </el-form>
      <div class="actions">
        <el-button type="primary" @click="saveSettings">保存设置</el-button>
      </div>
    </div>
  </div>
</template>

<script>
import api from '../api'

export default {
  name: 'SettingsView',
  data() {
    return {
      character: {
        name: '',
        description: '',
        personality: {
          prompt: ''
        }
      }
    }
  },
  async mounted() {
    await this.loadCurrentCharacter()
  },
  methods: {
    async loadCurrentCharacter() {
      const data = await api.getCurrentCharacter()
      this.character = data
    },
    async saveSettings() {
      try {
        await api.saveCharacter(this.character)
        this.$message.success('设置保存成功')
      } catch (error) {
        this.$message.error('保存失败')
      }
    }
  }
}
</script>

<style scoped>
.settings-view {
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
}

h2 {
  margin-bottom: 24px;
}

.model-preview {
  background: #f5f5f5;
  border-radius: 8px;
  padding: 40px;
  text-align: center;
  margin-bottom: 24px;
}

.preview-placeholder {
  color: #999;
}

.settings-form {
  background: white;
  padding: 24px;
  border-radius: 8px;
}

.actions {
  margin-top: 24px;
  text-align: right;
}
</style>
