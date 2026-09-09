import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue'),
    meta: { title: '任务列表' }
  },
  {
    path: '/create',
    name: 'Create',
    component: () => import('@/views/CreateView.vue'),
    meta: { title: '创建任务' }
  },
  {
    path: '/task/:id/titles',
    name: 'Titles',
    component: () => import('@/views/TitlesView.vue'),
    meta: { title: '选择标题' }
  },
  {
    path: '/task/:id/outline',
    name: 'Outline',
    component: () => import('@/views/OutlineView.vue'),
    meta: { title: '确认大纲' }
  },
  {
    path: '/task/:id/generating',
    name: 'Generating',
    component: () => import('@/views/GeneratingView.vue'),
    meta: { title: '生成中' }
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
  next()
})

export default router
