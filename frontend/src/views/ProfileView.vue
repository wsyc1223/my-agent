<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

const userName = ref(localStorage.getItem('userName') || 'yc')
const userId = ref(localStorage.getItem('userId') || 'NODE-2026-X')
const userAvatar = ref(userName.value.slice(0, 2).toUpperCase())

function handleBack() {
  router.back()
}
</script>

<template>
  <div class="profile-container">
    <div class="profile-card glass-card">
      <div class="profile-header">
        <button class="back-btn" @click="handleBack">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="19" y1="12" x2="5" y2="12"></line>
            <polyline points="12 19 5 12 12 5"></polyline>
          </svg>
          返回
        </button>
        <h2>节点安全控制台</h2>
      </div>

      <div class="profile-body">
        <div class="avatar-section">
          <div class="big-avatar">{{ userAvatar }}</div>
          <div class="user-meta">
            <h3>{{ userName }}</h3>
            <span class="status-badge">
              <span class="pulse-dot"></span>
              Secure Node Connected
            </span>
          </div>
        </div>

        <div class="details-grid">
          <div class="detail-item">
            <span class="label">节点 ID</span>
            <span class="value">{{ userId }}</span>
          </div>
          <div class="detail-item">
            <span class="label">角色权限</span>
            <span class="value highlighted">Node Operator / Developer</span>
          </div>
          <div class="detail-item">
            <span class="label">加密等级</span>
            <span class="value">AES-256 GCM</span>
          </div>
          <div class="detail-item">
            <span class="label">当前环境</span>
            <span class="value">WSL Ubuntu Core</span>
          </div>
        </div>

        <div class="stats-section">
          <h4>节点运行指标</h4>
          <div class="stats-grid">
            <div class="stat-card">
              <span class="stat-num">99.9%</span>
              <span class="stat-lbl">解析率</span>
            </div>
            <div class="stat-card">
              <span class="stat-num">< 2.4s</span>
              <span class="stat-lbl">平均响应</span>
            </div>
            <div class="stat-card">
              <span class="stat-num">HTTP 2.0</span>
              <span class="stat-lbl">流传输</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.profile-container {
  display: flex;
  justify-content: center;
  align-items: center;
  width: 100%;
  height: 100vh;
  padding: 24px;
  box-sizing: border-box;
}

.profile-card {
  width: 100%;
  max-width: 560px;
  background: var(--bg-glass);
  backdrop-filter: blur(20px);
  border: 1px solid var(--border-glass);
  border-radius: var(--radius-lg);
  padding: 32px;
  box-shadow: var(--shadow-glass);
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 16px;
  border-bottom: 1px solid var(--border-glass);
  padding-bottom: 16px;
  margin-bottom: 24px;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid var(--border-glass);
  color: var(--text-secondary);
  padding: 8px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s ease;
}

.back-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
  border-color: rgba(255, 255, 255, 0.2);
  transform: translateX(-2px);
}

.profile-header h2 {
  font-size: 18px;
  font-weight: 700;
  margin: 0;
  color: var(--accent-primary);
}

.avatar-section {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-bottom: 32px;
}

.big-avatar {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
  color: #fff;
  font-size: 24px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 20px rgba(16, 185, 129, 0.2);
}

.user-meta h3 {
  font-size: 20px;
  font-weight: 700;
  margin: 0 0 6px 0;
  color: var(--text-primary);
}

.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--accent-primary);
  background: rgba(16, 185, 129, 0.08);
  padding: 4px 10px;
  border-radius: 12px;
  border: 1px solid rgba(16, 185, 129, 0.2);
}

.pulse-dot {
  width: 6px;
  height: 6px;
  background: var(--accent-primary);
  border-radius: 50%;
  animation: pulse 1.8s infinite;
}

@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5); }
  70% { box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}

.details-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 32px;
}

.detail-item {
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
  padding: 12px 16px;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.detail-item .label {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.detail-item .value {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
}

.detail-item .value.highlighted {
  color: var(--accent-secondary);
}

.stats-section h4 {
  font-size: 13px;
  font-weight: 700;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 1px;
  margin: 0 0 12px 0;
}

.stats-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
}

.stat-card {
  background: rgba(0, 0, 0, 0.2);
  border: 1px solid var(--border-glass);
  padding: 16px;
  border-radius: 12px;
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.stat-num {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
}

.stat-lbl {
  font-size: 11px;
  color: var(--text-muted);
}
</style>
