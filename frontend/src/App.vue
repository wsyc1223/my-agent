<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import ChatSidebar from '@/components/ChatSidebar.vue'

const router = useRouter()
const currentPath = computed(() => {
  return router.currentRoute.value ? router.currentRoute.value.path : '/'
})
const chat = useChatStore()
const isDark = ref(localStorage.getItem('theme') === 'dark')

// 切换全局主题的核心函数
function toggleTheme() {
  isDark.value = !isDark.value
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

onMounted(() => {
  chat.fetchConversations()
  
  // 初始化全局主题状态
  if (isDark.value) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }

  // 挂载到全局 window 属性，实现跨组件解耦通信
  ;(window as any).__isDark = isDark
  ;(window as any).__toggleTheme = toggleTheme
})
</script>

<template>
  <div class="app-container" :class="{ 'theme-dark': isDark, 'theme-light': !isDark }">
    <!-- 液态背景流动球：在暗黑模式下动态映射极光折射 -->
    <div class="liquid-bg">
      <div class="blob blob-mint"></div>
      <div class="blob blob-sage"></div>
      <div class="blob blob-sand"></div>
    </div>
    
    <!-- 毛玻璃覆盖层 -->
    <div class="app-glass-wrapper">
      <div class="app">
        <ChatSidebar v-if="currentPath === '/'" />
        <router-view />
      </div>
    </div>
  </div>
</template>

<style>
/* 引入现代前沿科技字体 */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Fira+Code:wght@400;500;600&display=swap');

html:not(.dark) {
  /* HSL 调色盘 - 亮色模式 (优雅茶绿与高通透温润奶白底座) */
  --bg-app: rgba(247, 247, 245, 0.75);         /* 极通透浅磨砂底色，玉石折光感 */
  --bg-sidebar: hsla(142, 20%, 95%, 0.92);    /* 通透淡奶绿侧边栏 */
  --bg-card: rgba(255, 255, 255, 0.9);        /* 极浅白色磨砂卡片底色 */
  --bg-card-hover: rgba(255, 255, 255, 0.98); /* 悬浮白卡片 */
  --bg-user-msg: hsla(142, 30%, 90%, 0.98);   /* 用户温和鼠尾草浅绿气泡 */
  
  --border-color: rgba(0, 0, 0, 0.05);        /* 极精细浅色分割线 */
  --border-glow: hsla(142, 45%, 35%, 0.1);

  /* 品牌前沿色 */
  --primary: hsl(142, 45%, 35%);        /* 典雅深茶绿 */
  --primary-glow: hsla(142, 45%, 35%, 0.2);
  --success: hsl(142, 60%, 35%);       /* 柔和绿 */
  --warning: hsl(38, 85%, 45%);        /* 警告橙 */
  
  /* 浅色模式文字颜色 */
  --text-primary: #1f1f21;             /* Claude 经典深炭灰 */
  --text-secondary: #5d5d61;           /* 优雅深灰 */
  --text-muted: #8e8e93;               /* 浅灰 */
  /* 柔和的浅色微凸起阴影 */
  --shadow-lift: 0 4px 18px rgba(0, 0, 0, 0.03), 
                 inset 0 1px 0 rgba(255, 255, 255, 0.8);
  /* 柔和的凹槽阴影 (Neumorphic Inset) */
  --shadow-inset: inset 0 2px 4px rgba(0, 0, 0, 0.04),
                  0 1px 1px rgba(255, 255, 255, 0.9);
  /* 极致立体卡片光影 */
  --shadow-card: 0 10px 30px rgba(0, 0, 0, 0.04),
                 inset 0 1px 0 rgba(255, 255, 255, 0.9);
}

:root {
  /* 全局共有边距与圆角 */
  --radius-sm: 6px;
  --radius-md: 12px;
  --radius-lg: 18px;
  --transition-smooth: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

/* 2026 前沿极客暗黑主题 (Obsidian Dark Mode) */
html.dark {
  --bg-app: rgba(10, 10, 11, 0.65);             /* 极富晶莹感的碳黑磨砂底色 */
  --bg-sidebar: rgba(15, 15, 17, 0.6);          /* 幽邃半透侧边栏 */
  --bg-card: rgba(22, 22, 24, 0.4);             /* 薄款极客暗卡片底色 */
  --bg-card-hover: rgba(30, 30, 35, 0.85);      /* 悬浮发亮卡片 */
  --bg-user-msg: rgba(139, 92, 246, 0.15);      /* 用户优雅的极光紫半透明气泡 */
  
  --border-color: rgba(255, 255, 255, 0.05);    /* 极细微高透分割线 */
  --border-glow: rgba(139, 92, 246, 0.15);      /* 极光紫微光 */

  /* 品牌前沿色 - 极客紫 */
  --primary: hsl(265, 85%, 66%);        /* 极富张力的极光紫 */
  --primary-glow: rgba(139, 92, 246, 0.3);
  --success: hsl(142, 60%, 42%);       /* 柔绿 */
  --warning: hsl(20, 85%, 50%);        /* 晶莹警示红 */
  
  /* 深色模式文字颜色 */
  --text-primary: #f4f4f5;             /* 纯净亮白 */
  --text-secondary: #a1a1aa;           /* 优雅锌灰 */
  --text-muted: #52525b;               /* 隐藏暗灰 */

  /* 暗黑模式高对比立体光影 */
  --shadow-lift: 0 4px 20px rgba(0, 0, 0, 0.3), 
                 inset 0 1px 0 rgba(255, 255, 255, 0.05);
  --shadow-inset: inset 0 2px 4px rgba(0, 0, 0, 0.45),
                  0 1px 1px rgba(255, 255, 255, 0.05);
  --shadow-card: 0 12px 35px rgba(0, 0, 0, 0.45),
                 inset 0 1px 0 rgba(255, 255, 255, 0.08);
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: #f7f7f5; 
  color: var(--text-primary); 
  height: 100vh; 
  overflow: hidden;
  font-size: 15px; 
  -webkit-font-smoothing: antialiased;
  transition: background 0.5s ease;
}

body.dark {
  background: #09090b;
}

/* 液态玻璃流动底座 */
.app-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  display: flex;
}

.liquid-bg {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  z-index: 1;
  background: #f7f7f5;
  transition: background 0.5s ease;
}

html.dark .liquid-bg {
  background: #09090b;
}

.blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.65;
  transition: background 0.8s ease, filter 0.8s ease;
}

/* 亮色流动球 */
.blob-mint {
  width: 750px; height: 750px;
  background: radial-gradient(circle, hsla(142, 60%, 82%, 0.65) 0%, transparent 80%);
  top: -150px; left: -150px;
  animation: float-blob-1 25s infinite alternate ease-in-out;
}

.blob-sage {
  width: 800px; height: 800px;
  background: radial-gradient(circle, hsla(120, 45%, 85%, 0.6) 0%, transparent 80%);
  bottom: -200px; right: -200px;
  animation: float-blob-2 30s infinite alternate ease-in-out;
}

.blob-sand {
  width: 650px; height: 650px;
  background: radial-gradient(circle, hsla(45, 70%, 88%, 0.5) 0%, transparent 80%);
  top: 35%; left: 45%;
  animation: float-blob-3 28s infinite alternate ease-in-out;
}

/* 暗色流动球映射 (极光紫/深海蓝/暗金) */
html.dark .blob-mint {
  background: radial-gradient(circle, rgba(139, 92, 246, 0.25) 0%, transparent 80%);
  filter: blur(120px);
}

html.dark .blob-sage {
  background: radial-gradient(circle, rgba(59, 130, 246, 0.18) 0%, transparent 80%);
  filter: blur(120px);
}

html.dark .blob-sand {
  background: radial-gradient(circle, rgba(234, 179, 8, 0.08) 0%, transparent 80%);
  filter: blur(100px);
}

@keyframes float-blob-1 {
  0% { transform: translate(0, 0) scale(1); }
  100% { transform: translate(200px, 150px) scale(1.2); }
}

@keyframes float-blob-2 {
  0% { transform: translate(0, 0) scale(1.1); }
  100% { transform: translate(-180px, -200px) scale(0.9); }
}

@keyframes float-blob-3 {
  0% { transform: translate(0, 0) scale(0.95); }
  100% { transform: translate(150px, -150px) scale(1.15); }
}

/* 毛玻璃外壳 */
.app-glass-wrapper {
  position: relative;
  z-index: 2;
  width: 100%; height: 100%;
  backdrop-filter: blur(35px) saturate(140%);
  background: var(--bg-app);
  border: 1px solid rgba(255, 255, 255, 0.7); /* 晶莹亮白色玻璃亮边 */
  transition: var(--transition-smooth);
}

html.dark .app-glass-wrapper {
  border: 1px solid rgba(255, 255, 255, 0.05); /* 暗黑色玻璃暗边 */
}

.app {
  display: flex; 
  width: 100%;
  height: 100vh;
  background: transparent;
}

/* 完美自定义科技感滚动条 */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { 
  background: rgba(0, 0, 0, 0.18); /* 提升亮色模式默认可见度 */
  border-radius: 4px; 
  border: 1px solid rgba(255, 255, 255, 0.4);
  transition: var(--transition-smooth);
}

html.dark ::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.22); /* 提升暗色模式默认可见度 */
  border: 1px solid rgba(0, 0, 0, 0.2);
}

::-webkit-scrollbar-thumb:hover { 
  background: var(--primary); /* 悬浮时呈现茶绿色 (Light) 或 极光紫色 (Dark) 系统品牌色 */
}

html.dark ::-webkit-scrollbar-thumb:hover {
  background: var(--primary); 
}
</style>
