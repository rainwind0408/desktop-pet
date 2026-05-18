<template>
  <div class="character-switcher">
    <div class="current-character">
      <h3>当前角色：{{ currentCharacter.name || '未选择' }}</h3>
    </div>
    <div class="character-list">
      <div
        v-for="char in availableCharacters"
        :key="char.id"
        class="character-item"
        @click="handleSwitchCharacter(char.id)"
      >
        {{ char.name }}
      </div>
    </div>
  </div>
</template>

<script>
import api from '../api'

export default {
  name: 'CharacterSwitcher',
  data() {
    return {
      currentCharacter: {},
      availableCharacters: []
    }
  },
  async mounted() {
    await this.loadCharacters()
    await this.loadCurrentCharacter()
  },
  methods: {
    async loadCharacters() {
      const data = await api.getCharacters()
      this.availableCharacters = data
    },
    async loadCurrentCharacter() {
      const data = await api.getCurrentCharacter()
      this.currentCharacter = data
    },
    async handleSwitchCharacter(characterId) {
      try {
        const data = await api.switchCharacter(characterId)
        this.currentCharacter = data
        this.$message.success(`已切换至 ${data.name}`)
      } catch (error) {
        this.$message.error('切换角色失败')
      }
    }
  }
}
</script>

<style scoped>
.character-switcher {
  padding: 16px;
}

.current-character {
  margin-bottom: 16px;
}

.character-list {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.character-item {
  padding: 8px 16px;
  background: #f0f0f0;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}

.character-item:hover {
  background: #e0e0e0;
}
</style>
