import { createRouter, createWebHistory } from 'vue-router'
import ChatView from '@/views/ChatView.vue'
import AuthView from '@/views/AuthView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'chat', component: ChatView },
    { path: '/login', name: 'login', component: AuthView },
  ],
})

// 全局前置导航守卫，保护多租户核心聊天控制台
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('token')
  if (to.name !== 'login' && !token) {
    // 未登录用户强行访问聊天台，直接重定向拦截！
    next({ name: 'login' })
  } else if (to.name === 'login' && token) {
    // 已登录用户试图返回登录页，直接重定向去聊天台！
    next({ name: 'chat' })
  } else {
    next()
  }
})

export default router
