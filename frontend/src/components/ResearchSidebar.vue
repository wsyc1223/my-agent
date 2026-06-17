<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useResearchStore } from '@/stores/research'
import { useRouter } from 'vue-router'

const research = useResearchStore()
const router = useRouter()

const userName = ref(localStorage.getItem('userName') || 'yc')
const userAvatar = ref(userName.value.slice(0, 2).toUpperCase())
const isDark = ref(localStorage.getItem('theme') === 'dark')

function handleToggleTheme() {
  if ((window as any).__toggleTheme) {
    ;(window as any).__toggleTheme()
    isDark.value = (window as any).__isDark.value
  } else {
    isDark.value = !isDark.value
    localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
    if (isDark.value) {
      document.documentElement.classList.add('dark')
    } else {
      document.documentElement.classList.remove('dark')
    }
  }
}

onMounted(async () => {
  await research.fetchSessions()
  if ((window as any).__isDark) {
    isDark.value = (window as any).__isDark.value
  }
})

function handleNewResearch() {
  research.newSession()
}

function handleSelectSession(id: string) {
  research.fetchSessionDetails(id)
}

function goToProfile() {
  router.push('/profile')
}
</script>

<template>
  <aside class="research-sidebar">
    <div class="sidebar-header">
      <div class="logo-area">
        <span class="logo-dot"></span>
        <span class="logo-text">研究工坊</span>
      </div>
      <div class="header-actions" style="display: flex; gap: 8px; align-items: center;">
        <!-- 主题切换按钮 -->
        <button 
          class="theme-toggle-btn" 
          :class="{ 'is-dark-mode': isDark }" 
          @click="handleToggleTheme" 
          :title="isDark ? '切换至明亮模式' : '切换至暗黑模式'"
        >
          <svg v-if="isDark" class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
          </svg>
          <svg v-else class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
          </svg>
        </button>
        <!-- 新建会话按钮 -->
        <button class="new-session-btn" @click="handleNewResearch" title="新建深度研究">
          <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="12" y1="5" x2="12" y2="19"></line>
            <line x1="5" y1="12" x2="19" y2="12"></line>
          </svg>
        </button>
      </div>
    </div>

    <!-- 列表容器 -->
    <div class="sessions-list-container">
      <div class="section-title">Research Sessions</div>
      <div class="sessions-list">
        <div
          v-for="s in research.sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === research.currentId }"
          @click="handleSelectSession(s.id)"
        >
          <span class="item-icon">🔬</span>
          <span class="item-title" :title="s.title">{{ s.title }}</span>
        </div>
        <div v-if="research.sessions.length === 0" class="empty-list">
          <div class="empty-icon">📭</div>
          <span>暂无历史研究记录</span>
        </div>
      </div>
    </div>

    <!-- 底部用户信息区 -->
    <div class="sidebar-footer">
      <div class="user-info-card">
        <div class="avatar">{{ userAvatar }}</div>
        <div class="name-wrapper">
          <div class="nickname">{{ userName }}</div>
          <div class="role-badge">Node Dev</div>
        </div>
      </div>
      <!-- 锯齿形状 (齿轮) 的跳转按钮 -->
      <button class="settings-btn" @click="goToProfile" title="用户个人信息">
        <svg class="icon gear-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
      </button>
    </div>
  </aside>
</template>

<style scoped>
.research-sidebar {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: transparent;
  color: var(--research-text);
}

.sidebar-header {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--research-border);
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-dot {
  width: 8px;
  height: 8px;
  background: var(--research-accent);
  border-radius: 50%;
}

.logo-text {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.5px;
  color: var(--research-text);
}

.new-session-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--research-border);
  background: transparent;
  color: var(--research-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.new-session-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--research-text);
  border-color: var(--research-text-muted);
}



.sessions-list-container {
  flex: 1;
  overflow-y: auto;
  padding: 16px 8px;
  display: flex;
  flex-direction: column;
}

.section-title {
  font-size: 10px;
  font-weight: 700;
  color: var(--research-text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin-bottom: 8px;
  padding-left: 8px;
}

.sessions-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: 6px;
  cursor: pointer;
  color: var(--research-text-muted);
  border: 1px solid transparent;
  transition: all 0.2s ease;
}

.session-item:hover {
  background: rgba(0, 0, 0, 0.03);
  color: var(--research-text);
}



.session-item.active {
  background: rgba(16, 185, 129, 0.08);
  color: var(--research-accent);
  font-weight: 600;
}

.item-icon {
  font-size: 13px;
}

.item-title {
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.empty-list {
  padding: 32px 8px;
  text-align: center;
  color: var(--research-text-muted);
  font-size: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-icon {
  font-size: 20px;
  opacity: 0.5;
}

/* 底部区域 */
.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--research-border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
}

.user-info-card {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--research-accent);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.name-wrapper {
  display: flex;
  flex-direction: column;
}

.nickname {
  font-size: 13px;
  font-weight: 600;
  color: var(--research-text);
}

.role-badge {
  font-size: 10px;
  color: var(--research-text-muted);
}

.settings-btn {
  background: transparent;
  border: none;
  color: var(--research-text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.3s ease;
}

.settings-btn:hover {
  color: var(--research-accent);
  background: rgba(0, 0, 0, 0.03);
  transform: rotate(45deg);
}



.settings-btn:active {
  transform: scale(0.95) rotate(45deg);
}

.theme-toggle-btn {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: 1px solid var(--research-border);
  background: transparent;
  color: var(--research-text-muted);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s ease;
}

.theme-toggle-btn:hover {
  background: rgba(0, 0, 0, 0.05);
  color: var(--research-text);
  border-color: var(--research-text-muted);
}



.theme-toggle-btn .icon {
  transition: transform 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.theme-toggle-btn:hover .icon {
  transform: rotate(30deg);
}

.theme-toggle-btn.is-dark-mode {
  color: var(--research-accent);
}
</style>

<style>
/* 深度研究侧边栏 - 暗黑模式全局 hover 状态覆盖 */
html.dark .new-session-btn:hover {
  background: rgba(255, 255, 255, 0.05) !important;
}
html.dark .session-item:hover {
  background: rgba(255, 255, 255, 0.03) !important;
}
html.dark .settings-btn:hover {
  background: rgba(255, 255, 255, 0.03) !important;
}
html.dark .theme-toggle-btn:hover {
  background: rgba(255, 255, 255, 0.05) !important;
}
</style>
