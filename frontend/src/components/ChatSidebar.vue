<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useChatStore } from '@/stores/chat'
import { useRouter } from 'vue-router'

const chat = useChatStore()
const router = useRouter()
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

// 退出登录逻辑
function handleLogout() {
  chat.logout()
  router.push('/login')
}

// 与全局 window 属性绑定，方便跨路由视图动态刷新昵称
const userName = ref(chat.userName)
;(window as any).__userName = userName

onMounted(() => {
  if ((window as any).__isDark) {
    isDark.value = (window as any).__isDark.value
  }
  // 补丁：挂载时加载最新的个人昵称
  userName.value = localStorage.getItem('userName') || chat.userName || '未经验证节点'
})
</script>

<template>
  <aside class="sidebar" :class="{ 'collapsed': chat.sidebarCollapsed }">
    <!-- 头部 LOGO 与 主题/新建 动作控制区 -->
    <div class="header">
      <div class="logo-area">
        <span class="logo-dot"></span>
        <span class="logo-text">Agentic OS</span>
      </div>
      <div class="header-actions">
        <!-- 极客模式切换按钮 -->
        <button 
          class="action-btn theme-toggle-btn" 
          :class="{ 'is-dark-mode': isDark }" 
          @click="handleToggleTheme" 
          :title="isDark ? '切换至生机模式 (Light)' : '切换至极客模式 (Dark)'"
        >
          <svg v-if="isDark" class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>
          </svg>
          <svg v-else class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <circle cx="12" cy="12" r="4"/><path d="M12 2v2"/><path d="M12 20v2"/><path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/><path d="M2 12h2"/><path d="M20 12h2"/><path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>
          </svg>
        </button>
        <!-- 新建会话按钮 -->
        <button class="action-btn new-btn" @click="chat.newConversation()" title="新建对话">
          <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
        </button>
        <!-- 侧边栏折叠按钮 -->
        <button class="action-btn collapse-btn" @click="chat.sidebarCollapsed = true" title="隐藏边栏">
          <svg class="icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
            <polyline points="15 18 9 12 15 6"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- 会话列表 -->
    <div class="list-container">
      <div class="list-title">Conversations</div>
      <div class="list">
        <div
          v-for="c in chat.conversations"
          :key="c.id"
          class="item-card-3d"
          :class="{ active: c.id === chat.currentId }"
          @click="chat.fetchMessages(c.id)"
        >
          <span class="item-icon">💬</span>
          <span class="item-title">{{ c.title }}</span>
        </div>
        <div v-if="chat.conversations.length === 0" class="empty-list-3d">
          <div class="empty-icon">📭</div>
          <span>暂无活动线程</span>
        </div>
      </div>
    </div>

    <!-- 底部用户信息与设置面板 -->
    <div class="user-control-panel-bottom">
      <div class="user-info-section">
        <div class="user-avatar-circle">
          {{ userName.slice(0, 2).toUpperCase() }}
        </div>
        <span class="username-label" :title="userName">{{ userName }}</span>
      </div>
      <div class="user-actions-section">
        <!-- 个人信息齿轮按钮 -->
        <button class="icon-btn-settings" @click="router.push('/profile')" title="用户个人信息">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>
        <!-- 退出登录按钮 -->
        <button class="icon-btn-logout" @click="handleLogout" title="退出安全节点">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>
          </svg>
        </button>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 260px; 
  background: var(--bg-sidebar); 
  backdrop-filter: blur(20px);
  border-right: 1px solid var(--border-color);
  display: flex; 
  flex-direction: column; 
  flex-shrink: 0;
  box-shadow: 4px 0 30px rgba(0, 0, 0, 0.02);
  transition: var(--transition-smooth);
}

.header {
  padding: 24px 20px 14px; 
  display: flex; 
  align-items: center;
  justify-content: space-between; 
  min-height: 56px;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 8px;
}

.logo-dot {
  width: 8px; height: 8px;
  background: var(--primary);
  border-radius: 50%;
  box-shadow: 0 0 10px var(--primary-glow);
  transition: var(--transition-smooth);
}

.logo-text { 
  font-size: 16px; 
  font-weight: 700; 
  color: var(--text-primary); 
  letter-spacing: 0.8px;
  background: linear-gradient(135deg, var(--primary) 0%, hsl(265, 85%, 55%) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  transition: var(--transition-smooth);
}

html.dark .logo-text {
  background: linear-gradient(135deg, var(--primary) 0%, hsl(280, 85%, 65%) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.action-btn {
  width: 30px; 
  height: 30px; 
  border-radius: var(--radius-md); 
  border: 1px solid rgba(0, 0, 0, 0.05);
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.85), rgba(240, 240, 235, 0.85));
  color: var(--text-secondary); 
  cursor: pointer;
  display: flex; 
  align-items: center; 
  justify-content: center;
  box-shadow: var(--shadow-lift);
  transition: var(--transition-smooth);
}

html.dark .action-btn {
  border: 1px solid rgba(255, 255, 255, 0.04);
  background: linear-gradient(145deg, rgba(30, 30, 35, 0.85), rgba(20, 20, 25, 0.85));
  color: var(--text-secondary);
}

.action-btn:hover { 
  color: var(--primary);
  border-color: rgba(0, 0, 0, 0.08);
  box-shadow: var(--shadow-card);
  transform: translateY(-1px);
}

html.dark .action-btn:hover {
  border-color: rgba(255, 255, 255, 0.08);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.15);
}

.action-btn:active {
  transform: translateY(1px);
  box-shadow: var(--shadow-inset);
  background: rgba(0, 0, 0, 0.03);
}

html.dark .action-btn:active {
  background: rgba(255, 255, 255, 0.02);
}

.theme-toggle-btn .icon {
  transition: transform 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.theme-toggle-btn:hover .icon {
  transform: rotate(30deg);
}

.theme-toggle-btn.is-dark-mode {
  color: var(--primary);
  box-shadow: 0 0 10px rgba(139, 92, 246, 0.2);
}



.list-container {
  flex: 1; 
  overflow-y: auto; 
  padding: 20px 14px; 
  display: flex;
  flex-direction: column;
}

.list-title {
  font-size: 10px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1.2px;
  margin-bottom: 12px;
  padding-left: 8px;
}

.list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.item-card-3d {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px; 
  border-radius: var(--radius-md); 
  cursor: pointer;
  color: var(--text-secondary);
  border: 1px solid transparent;
  background: transparent;
  transition: var(--transition-smooth);
}

.item-card-3d:hover { 
  background: var(--bg-card-hover); 
  color: var(--text-primary);
  border: 1px solid rgba(255, 255, 255, 0.85);
  box-shadow: var(--shadow-lift);
  transform: translateY(-1.5px);
}

html.dark .item-card-3d:hover {
  border: 1px solid rgba(255, 255, 255, 0.04);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
}

.item-card-3d.active { 
  background: hsla(142, 30%, 88%, 0.85);
  color: var(--primary); 
  border: 1px solid rgba(0, 0, 0, 0.02);
  box-shadow: var(--shadow-inset);
  transform: translateY(0);
  font-weight: 600;
}

html.dark .item-card-3d.active {
  background: rgba(139, 92, 246, 0.1);
  color: var(--primary);
  border: 1px solid rgba(139, 92, 246, 0.15);
  box-shadow: inset 0 2px 4px rgba(0, 0, 0, 0.35);
}

.item-card-3d.active .item-icon {
  filter: drop-shadow(0 0 6px var(--primary-glow));
}

.item-icon {
  font-size: 14px;
}

.item-title { 
  overflow: hidden; 
  text-overflow: ellipsis; 
  white-space: nowrap; 
  display: block; 
  font-size: 14px; 
}

.empty-list-3d { 
  padding: 48px 12px; 
  text-align: center; 
  color: var(--text-muted); 
  font-size: 12.5px; 
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.empty-icon {
  font-size: 24px;
  filter: grayscale(0.5);
}

/* Sidebar Collapse Transition */
.sidebar {
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1), padding 0.3s ease, border-color 0.3s ease, opacity 0.3s ease;
}
.sidebar.collapsed {
  width: 0 !important;
  padding: 0 !important;
  opacity: 0;
  overflow: hidden;
  border-right: none !important;
}

/* User bottom panel styling */
.user-control-panel-bottom {
  padding: 16px;
  border-top: 1px solid var(--border-color);
  background: rgba(0, 0, 0, 0.02);
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: auto;
}

html.dark .user-control-panel-bottom {
  background: rgba(0, 0, 0, 0.2);
}

.user-info-section {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 65%;
  overflow: hidden;
}

.user-avatar-circle {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--primary) 0%, #a855f7 100%);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.15);
}

.username-label {
  font-size: 13.5px;
  color: var(--text-primary);
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-actions-section {
  display: flex;
  align-items: center;
  gap: 4px;
}

.icon-btn-settings, .icon-btn-logout {
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  padding: 6px;
  border-radius: var(--radius-sm);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: var(--transition-smooth);
}

.icon-btn-settings:hover {
  color: var(--primary);
  background: rgba(0, 0, 0, 0.05);
}

html.dark .icon-btn-settings:hover {
  background: rgba(255, 255, 255, 0.05);
}

.icon-btn-logout:hover {
  color: var(--warning);
  background: rgba(239, 68, 68, 0.08);
}
</style>
