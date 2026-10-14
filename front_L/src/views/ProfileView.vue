<template>
  <div class="profile-page">
    <div class="profile-card">
      <h2>个人信息</h2>

      <el-form label-position="top" class="info-form">
        <el-form-item label="昵称">
          <el-input :model-value="authStore.user?.nickname" disabled />
        </el-form-item>
        <el-form-item label="用户名">
          <el-input :model-value="authStore.user?.username" disabled />
        </el-form-item>
        <el-form-item label="绑定邮箱">
          <el-input :model-value="authStore.user?.email" disabled />
        </el-form-item>
        <el-form-item label="账户余额">
          <div class="balance-row">
            <span class="balance-num">¥ {{ (authStore.user?.balance || 0).toFixed(2) }}</span>
            <el-button size="small" @click="rechargeDialog = true">充值</el-button>
          </div>
        </el-form-item>
      </el-form>

      <el-divider />

      <h3>修改密码</h3>
      <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-position="top" class="pwd-form">
        <el-form-item label="旧密码" prop="old_password">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入当前密码" />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="8-32位，含字母和数字" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm_new_password">
          <el-input v-model="pwdForm.confirm_new_password" type="password" show-password placeholder="再次输入新密码" />
        </el-form-item>
        <el-button type="primary" :loading="changingPwd" @click="handleChangePwd">修改密码</el-button>
      </el-form>

      <el-divider />

      <h3 class="danger-title">危险操作</h3>
      <el-button type="danger" plain @click="logout">退出登录</el-button>
      <el-button type="danger" @click="deactivateDialog = true">注销账号</el-button>
    </div>

    <!-- 充值弹窗（模拟支付，返回固定验证码 888888） -->
    <el-dialog v-model="rechargeDialog" title="模拟充值" width="400px">
      <p class="dialog-tip">开发阶段为模拟支付：点击"确认充值"后自动按 888888 验证码完成充值，将来可无缝接入真实支付。</p>
      <el-input v-model="rechargeAmount" type="number" placeholder="充值金额（元）" min="1" />
      <template #footer>
        <el-button @click="rechargeDialog = false">取消</el-button>
        <el-button type="primary" :loading="recharging" @click="handleRecharge">确认充值</el-button>
      </template>
    </el-dialog>

    <!-- 注销确认 -->
    <el-dialog v-model="deactivateDialog" title="注销账号" width="400px">
      <p class="dialog-tip">注销后账号不可恢复。已付费/已下载的文章仍保留在对方账号中。</p>
      <template #footer>
        <el-button @click="deactivateDialog = false">取消</el-button>
        <el-button type="danger" :loading="deactivating" @click="handleDeactivate">确认注销</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'

const router = useRouter()
const authStore = useAuthStore()

// ===== 修改密码 =====
const pwdFormRef = ref(null)
const changingPwd = ref(false)
const pwdForm = reactive({ old_password: '', new_password: '', confirm_new_password: '' })
const pwdRules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_!@#$%^&*+\-=]{8,32}$/, message: '8-32位，含字母和数字', trigger: 'blur' }
  ],
  confirm_new_password: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    { validator: (r, v, cb) => { if (v !== pwdForm.new_password) cb(new Error('两次密码不一致')); else cb(); }, trigger: 'blur' }
  ]
}

async function handleChangePwd() {
  await pwdFormRef.value.validate()
  changingPwd.value = true
  try {
    await request.put('/auth/password', {
      old_password: pwdForm.old_password,
      new_password: pwdForm.new_password,
      confirm_new_password: pwdForm.confirm_new_password
    })
    ElMessage.success('密码修改成功，请重新登录')
    authStore.logout()
    router.push('/login')
  } catch (e) {
    // 拦截器已提示
  } finally {
    changingPwd.value = false
  }
}

// ===== 充值 =====
const rechargeDialog = ref(false)
const recharging = ref(false)
const rechargeAmount = ref(100)

async function handleRecharge() {
  const amount = Number(rechargeAmount.value)
  if (!amount || amount <= 0) {
    ElMessage.warning('请输入正确的金额')
    return
  }
  recharging.value = true
  try {
    // 模拟支付：先调模拟支付接口拿确认码（固定 888888），再确认充值
    const res = await request.post('/auth/recharge', { amount, verify_code: '888888' })
    ElMessage.success(res.message || '充值成功')
    rechargeDialog.value = false
  } catch (e) {
    // 拦截器已提示
  } finally {
    recharging.value = false
  }
}

// ===== 注销 =====
const deactivateDialog = ref(false)
const deactivating = ref(false)

async function handleDeactivate() {
  try {
    await ElMessageBox.confirm('注销后账号不可恢复，确定继续？', '警告', { type: 'warning' })
  } catch (e) {
    deactivateDialog.value = false
    return
  }
  deactivating.value = true
  try {
    await request.delete('/auth/account')
    ElMessage.success('账号已注销')
    authStore.logout()
    router.push('/')
  } catch (e) {
    // 拦截器已提示
  } finally {
    deactivating.value = false
    deactivateDialog.value = false
  }
}

function logout() {
  authStore.logout()
  ElMessage.success('已退出登录')
  router.push('/')
}
</script>

<style scoped>
.profile-page {
  max-width: 560px;
  margin: 0 auto;
  padding: 24px 0 40px;
}

.profile-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: 32px;
}

.profile-card h2 {
  margin: 0 0 20px;
  font-size: 22px;
  color: var(--text-primary);
}

.profile-card h3 {
  margin: 0 0 16px;
  font-size: 16px;
  color: var(--text-primary);
}

.balance-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.balance-num {
  font-size: 20px;
  font-weight: 700;
  color: var(--primary);
}

.danger-title {
  color: var(--danger, #f56c6c) !important;
}

.dialog-tip {
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.6;
  margin: 0 0 16px;
}
</style>
