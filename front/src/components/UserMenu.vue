<template>
  <div class="user-menu">
    <!-- 未登录 -->
    <template v-if="!authStore.isLoggedIn">
      <router-link to="/login" class="login-link">登录</router-link>
      <router-link to="/register" class="register-link">注册</router-link>
    </template>

    <!-- 已登录 -->
    <el-dropdown v-else trigger="click" @command="handleCommand">
      <div class="user-trigger">
        <span class="user-name">{{ authStore.user?.nickname || authStore.user?.username }}</span>
        <span class="menu-icon"><SvgIcon name="menu" :size="18" /></span>
      </div>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="profile">
            <SvgIcon name="user" :size="16" /> 个人信息
          </el-dropdown-item>
          <el-dropdown-item command="my-articles">
            <SvgIcon name="document" :size="16" /> 我的文章
          </el-dropdown-item>
          <el-dropdown-item command="logout" divided>
            <SvgIcon name="logout" :size="16" /> 退出登录
          </el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

function handleCommand(command) {
  if (command === 'profile') {
    router.push('/profile')
  } else if (command === 'my-articles') {
    router.push('/my-articles')
  } else if (command === 'logout') {
    authStore.logout()
    ElMessage.success('已退出登录')
    router.push('/')
  }
}
</script>

<style scoped>
.user-menu {
  display: flex;
  align-items: center;
  gap: 10px;
}

.login-link,
.register-link {
  padding: 8px 16px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: all 0.2s ease;
}

.login-link {
  color: var(--text-secondary);
}

.login-link:hover {
  color: var(--text-primary);
  background: var(--bg-soft);
}

.register-link {
  background: var(--primary-gradient);
  color: white;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.register-link:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4);
}

.user-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-card);
  cursor: pointer;
  transition: all 0.2s ease;
  outline: none;
}

.user-trigger:hover {
  background: var(--bg-soft);
}

.user-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-icon {
  display: flex;
  align-items: center;
  color: var(--text-secondary);
}
</style>
