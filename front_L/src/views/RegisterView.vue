<template>
  <div class="auth-page">
    <div class="auth-card">
      <div class="auth-header">
        <div class="auth-icon">
          <SvgIcon name="magic" :size="26" />
        </div>
        <h2>注册 BlogAgent</h2>
        <p class="auth-sub">创建账号，开启你的 AI 写作之旅</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="昵称" prop="nickname">
          <el-input v-model="form.nickname" placeholder="用于展示，默认随机生成" size="large" clearable />
        </el-form-item>

        <el-form-item label="邮箱" prop="email">
          <div class="email-row">
            <el-input v-model="form.email" placeholder="用于登录，需验证码验证" size="large" clearable />
            <el-button :disabled="sendingCode" @click="handleSendCode">
              {{ sendingCode ? `${countdown}s` : '获取验证码' }}
            </el-button>
          </div>
        </el-form-item>

        <el-form-item label="邮箱验证码" prop="email_code">
          <el-input v-model="form.email_code" placeholder="开发阶段默认验证码：888888" size="large" maxlength="6" />
        </el-form-item>

        <el-form-item label="用户名" prop="username">
          <el-input v-model="form.username" placeholder="仅数字和大小写字母，3-32位" size="large" clearable />
        </el-form-item>

        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" placeholder="8-32位，含字母和数字" size="large" show-password />
          <div class="field-tip">允许：大小写字母、数字、下划线 _ 及符号 ! @ # $ % ^ &amp; * + - =</div>
        </el-form-item>

        <el-form-item label="确认密码" prop="confirm_password">
          <el-input v-model="form.confirm_password" type="password" placeholder="再次输入密码" size="large" show-password
            @keyup.enter="handleRegister" />
        </el-form-item>

        <el-button type="primary" size="large" class="auth-btn" :loading="loading" @click="handleRegister">
          注册
        </el-button>
      </el-form>

      <div class="auth-footer">
        已有账号？
        <router-link to="/login" class="auth-link">去登录</router-link>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import request from '@/utils/request'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const loading = ref(false)
const sendingCode = ref(false)
const countdown = ref(0)
let timer = null

const form = reactive({
  nickname: '',
  email: '',
  email_code: '',
  username: '',
  password: '',
  confirm_password: ''
})

// 默认昵称：Blog_ + 随机5位数字
const randomNickname = () => 'Blog_' + String(Math.floor(10000 + Math.random() * 90000))
form.nickname = randomNickname()

const rules = {
  nickname: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { min: 2, max: 32, message: '昵称 2-32 位', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  email_code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { len: 6, message: '验证码为 6 位数字', trigger: 'blur' }
  ],
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9]{3,32}$/, message: '仅数字和大小写字母，3-32位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_!@#$%^&*+\-=]{8,32}$/, message: '8-32位，仅限字母、数字、_ 及 !@#$%^&*+-=', trigger: 'blur' },
    { validator: (r, v, cb) => { if (v && !(/\d/.test(v) && /[A-Za-z]/.test(v))) cb(new Error('密码必须同时包含字母和数字')); else cb(); }, trigger: 'blur' }
  ],
  confirm_password: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    { validator: (r, v, cb) => { if (v !== form.password) cb(new Error('两次输入的密码不一致')); else cb(); }, trigger: 'blur' }
  ]
}

async function handleSendCode() {
  if (!form.email || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email)) {
    ElMessage.warning('请先输入正确的邮箱')
    return
  }
  sendingCode.value = true
  try {
    const res = await request.post('/auth/send-code', { email: form.email })
    ElMessage.success(`验证码已发送${res.code ? `：${res.code}` : ''}（开发阶段固定验证码）`)
    countdown.value = 60
    timer = setInterval(() => {
      countdown.value -= 1
      if (countdown.value <= 0) {
        clearInterval(timer)
        sendingCode.value = false
      }
    }, 1000)
  } catch (e) {
    sendingCode.value = false
  }
}

async function handleRegister() {
  await formRef.value.validate()
  loading.value = true
  try {
    await authStore.register({
      nickname: form.nickname.trim(),
      email: form.email.trim(),
      email_code: form.email_code.trim(),
      username: form.username.trim(),
      password: form.password,
      confirm_password: form.confirm_password
    })
    ElMessage.success('注册成功')
    router.push('/')
  } catch (e) {
    // 错误提示已由拦截器处理
  } finally {
    loading.value = false
  }
}

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.auth-page {
  min-height: calc(100vh - 68px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px 24px;
  background: radial-gradient(ellipse at top, var(--bg-soft), transparent 60%);
}

.auth-card {
  width: 100%;
  max-width: 460px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 40px 36px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.06);
}

.auth-header {
  text-align: center;
  margin-bottom: 28px;
}

.auth-icon {
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--primary-gradient);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 16px;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.3);
}

.auth-header h2 {
  margin: 0 0 8px;
  font-size: 22px;
  color: var(--text-primary);
}

.auth-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-muted);
}

.email-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.email-row .el-input {
  flex: 1;
}

.field-tip {
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 4px;
}

.auth-btn {
  width: 100%;
  margin-top: 4px;
}

.auth-footer {
  margin-top: 20px;
  text-align: center;
  font-size: 14px;
  color: var(--text-secondary);
}

.auth-link {
  color: var(--primary);
  font-weight: 600;
  text-decoration: none;
}
</style>
