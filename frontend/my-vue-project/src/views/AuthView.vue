<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useChatStore } from '@/stores/chat'
import { apiUrl } from '@/services/api'

const router = useRouter()
const chatStore = useChatStore()

const isLogin = ref(true)
const email = ref('')
const password = ref('')
const name = ref('')

const loading = ref(false)
const error = ref('')

// 切换登录/注册模式
function toggleMode() {
  isLogin.value = !isLogin.value
  error.value = ''
}

// 提交表单处理
async function handleSubmit() {
  if (!email.value || !password.value) {
    error.value = '请填写邮箱和密码'
    return
  }
  if (!isLogin.value && !name.value) {
    error.value = '请填写昵称'
    return
  }

  loading.value = true
  error.value = ''

  try {
    const endpoint = isLogin.value ? 'login' : 'register'
    const body: Record<string, string> = {
      email: email.value,
      password: password.value,
    }
    if (!isLogin.value) {
      body.name = name.value
    }

    const res = await fetch(apiUrl(`/auth/${endpoint}`), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    })

    const data = await res.json()

    if (!res.ok) {
      throw new Error(data.detail || '请求失败，请稍后重试')
    }

    // 成功后保存凭证至本地
    localStorage.setItem('token', data.access_token)
    localStorage.setItem('userName', data.name)
    localStorage.setItem('userId', data.user_id)

    // 同步 Pinia Store
    chatStore.userId = data.user_id
    if ((window as any).__userName) {
      (window as any).__userName.value = data.name
    }

    // 跳转至聊天主页
    router.push('/')
  } catch (err: any) {
    error.value = err.message || '网络异常，请检查后端连接'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-view">
    <!-- 极客拟物毛玻璃卡片 -->
    <div class="auth-card-3d">
      <div class="auth-header">
        <div class="logo-dot"></div>
        <h1 class="logo-text">Agentic OS</h1>
        <p class="subtitle">2026届多租户安全Agent决策平台</p>
      </div>

      <form @submit.prevent="handleSubmit" class="auth-form">
        <!-- 错误提示组件 -->
        <Transition name="fade">
          <div v-if="error" class="error-banner">
            <span class="error-icon">⚠️</span>
            <span class="error-msg">{{ error }}</span>
          </div>
        </Transition>

        <!-- 输入控件组 -->
        <div class="input-group-3d">
          <div v-if="!isLogin" class="input-wrapper">
            <label class="field-label">昵称 (Nickname)</label>
            <input
              v-model="name"
              type="text"
              class="input-3d"
              placeholder="请输入起航昵称"
              autocomplete="name"
            />
          </div>

          <div class="input-wrapper">
            <label class="field-label">邮箱地址 (Email)</label>
            <input
              v-model="email"
              type="email"
              class="input-3d"
              placeholder="name@example.com"
              autocomplete="email"
              required
            />
          </div>

          <div class="input-wrapper">
            <label class="field-label">安全密码 (Password)</label>
            <input
              v-model="password"
              type="password"
              class="input-3d"
              placeholder="••••••••"
              autocomplete="current-password"
              required
            />
          </div>
        </div>

        <!-- 3D 拟物感提交按钮 -->
        <button type="submit" class="submit-btn-3d" :disabled="loading">
          <span v-if="loading" class="spinner"></span>
          <span v-else>{{ isLogin ? '安全登录 / Sign In' : '快速开户 / Sign Up' }}</span>
        </button>
      </form>

      <!-- 底部切换控制 -->
      <div class="auth-footer">
        <span class="footer-text">
          {{ isLogin ? '还没有安全凭证？' : '已有安全节点凭证？' }}
        </span>
        <button @click="toggleMode" class="switch-mode-btn">
          {{ isLogin ? '立即注册 / Register' : '立即登录 / Login' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-view {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  position: relative;
  z-index: 10;
}

/* 极致 3D 悬浮高毛玻璃质感卡片 */
.auth-card-3d {
  width: 100%;
  max-width: 420px;
  background: var(--bg-card);
  backdrop-filter: blur(40px) saturate(150%);
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: var(--radius-lg);
  padding: 40px 32px;
  box-shadow: var(--shadow-card);
  transform: translateY(-10px);
  animation: float-card 0.8s cubic-bezier(0.16, 1, 0.3, 1) forwards;
  transition: var(--transition-smooth);
}

html.dark .auth-card-3d {
  border: 1px solid rgba(255, 255, 255, 0.05);
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5);
}

@keyframes float-card {
  0% { opacity: 0; transform: translateY(10px) scale(0.98); }
  100% { opacity: 1; transform: translateY(0) scale(1); }
}

.auth-header {
  text-align: center;
  margin-bottom: 30px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.logo-dot {
  width: 12px;
  height: 12px;
  background: var(--primary);
  border-radius: 50%;
  box-shadow: 0 0 15px var(--primary-glow);
  margin-bottom: 12px;
}

.logo-text {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: 1.2px;
  background: linear-gradient(135deg, var(--primary) 0%, hsl(265, 85%, 55%) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: 6px;
}

html.dark .logo-text {
  background: linear-gradient(135deg, var(--primary) 0%, hsl(280, 85%, 65%) 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

.subtitle {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.8px;
  text-transform: uppercase;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 错误提示 */
.error-banner {
  background: hsla(20, 85%, 50%, 0.1);
  border: 1px solid hsla(20, 85%, 50%, 0.25);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}

html.dark .error-banner {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.25);
}

.error-icon {
  font-size: 14px;
}

.error-msg {
  font-size: 13px;
  font-weight: 500;
  color: var(--warning);
}

/* 拟物凹陷输入槽组 */
.input-group-3d {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.input-wrapper {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.field-label {
  font-size: 11px;
  font-weight: 700;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 1px;
  padding-left: 2px;
}

.input-3d {
  width: 100%;
  background: rgba(0, 0, 0, 0.03);
  box-shadow: var(--shadow-inset);
  border: 1px solid rgba(0, 0, 0, 0.03);
  border-radius: var(--radius-md);
  padding: 12px 16px;
  outline: none;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  transition: var(--transition-smooth);
}

html.dark .input-3d {
  background: rgba(0, 0, 0, 0.25);
  border: 1px solid rgba(255, 255, 255, 0.02);
}

.input-3d:focus {
  background: rgba(255, 255, 255, 0.8);
  border-color: var(--primary-glow);
  box-shadow: 0 0 0 3px var(--primary-glow);
}

html.dark .input-3d:focus {
  background: rgba(0, 0, 0, 0.35);
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.15);
}

/* 极具弹性的触觉拟物提交按键 */
.submit-btn-3d {
  width: 100%;
  height: 46px;
  border-radius: var(--radius-md);
  border: 1px solid rgba(0, 0, 0, 0.05);
  background: linear-gradient(145deg, rgba(255, 255, 255, 0.95), rgba(240, 240, 235, 0.95));
  color: var(--primary);
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  box-shadow: var(--shadow-lift);
  transition: var(--transition-smooth);
  display: flex;
  align-items: center;
  justify-content: center;
}

html.dark .submit-btn-3d {
  border: 1px solid rgba(255, 255, 255, 0.04);
  background: linear-gradient(145deg, rgba(30, 30, 35, 0.95), rgba(20, 20, 25, 0.95));
  color: var(--text-primary);
}

.submit-btn-3d:hover:not(:disabled) {
  box-shadow: var(--shadow-card);
  transform: translateY(-1.5px);
  color: var(--primary);
}

html.dark .submit-btn-3d:hover:not(:disabled) {
  box-shadow: 0 8px 24px rgba(139, 92, 246, 0.25);
  border-color: rgba(139, 92, 246, 0.2);
}

.submit-btn-3d:active:not(:disabled) {
  transform: translateY(1px);
  box-shadow: var(--shadow-inset);
}

.submit-btn-3d:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* 加载动画 */
.spinner {
  width: 18px;
  height: 18px;
  border: 2.5px solid var(--text-muted);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.auth-footer {
  margin-top: 24px;
  text-align: center;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.footer-text {
  color: var(--text-secondary);
}

.switch-mode-btn {
  background: transparent;
  border: none;
  color: var(--primary);
  font-weight: 700;
  cursor: pointer;
  transition: var(--transition-smooth);
}

.switch-mode-btn:hover {
  text-decoration: underline;
  opacity: 0.8;
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
