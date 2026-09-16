import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '任务列表' }
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录' }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/RegisterView.vue'),
    meta: { title: '注册' }
  },
  {
    path: '/create',
    name: 'Create',
    component: () => import('@/views/CreateView.vue'),
    meta: { title: '创建任务', requiresAuth: true }
  },
  {
    path: '/task/:id/titles',
    name: 'Titles',
    component: () => import('@/views/TitlesView.vue'),
    meta: { title: '选择标题', requiresAuth: true }
  },
  {
    path: '/task/:id/outline',
    name: 'Outline',
    component: () => import('@/views/OutlineView.vue'),
    meta: { title: '确认大纲', requiresAuth: true }
  },
  {
    path: '/task/:id/generating',
    name: 'Generating',
    component: () => import('@/views/GeneratingView.vue'),
    meta: { title: '生成中', requiresAuth: true }
  },
  {
    path: '/blog/:id',
    name: 'BlogDetail',
    component: () => import('@/views/BlogDetailView.vue'),
    meta: { title: '文章详情' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  document.title = `${to.meta.title || '博客生成 Agent'} - 博客生成 Agent`

  // 需要登录的页面：未登录 → 跳登录页（记录原路径，登录后跳回）
  if (to.meta.requiresAuth && !localStorage.getItem('blog-agent-token')) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // 已登录访问登录/注册页 → 回首页
  if ((to.path === '/login' || to.path === '/register') && localStorage.getItem('blog-agent-token')) {
    next({ path: '/' })
    return
  }

  next()
})

export default router
