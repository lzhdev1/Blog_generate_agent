<template>
  <AccountSheet :title="t('registerTitle')" :description="t('registerIntro')">
    <form class="account-form" @submit.prevent="submit">
      <label for="register-username">{{ t('username') }}
        <input id="register-username" v-model.trim="form.username" required minlength="3" maxlength="32" pattern="[A-Za-z0-9]{3,32}" :title="t('usernameHint')" autocomplete="username" />
        <span class="account-help">{{ t('usernameHint') }}</span>
      </label>
      <label for="register-nickname">{{ t('nickname') }}
        <input id="register-nickname" v-model.trim="form.nickname" required minlength="2" maxlength="32" pattern="[一-龥A-Za-z0-9_ ]{2,32}" :title="t('nicknameHint')" autocomplete="nickname" />
      </label>
      <div class="account-field">
        <label for="register-email">{{ t('email') }}</label>
        <div class="account-inline">
          <input ref="emailField" id="register-email" v-model.trim="form.email" type="email" required autocomplete="email" :aria-describedby="testCode ? 'register-test-code' : undefined" />
          <button v-if="config?.registration_mode === 'smtp'" type="button" class="quiet-action" :disabled="sending || busy" @click="getCode">{{ t('getCode') }}</button>
        </div>
        <span v-if="testCode" id="register-test-code" class="account-code">{{ t('testCode', { code: testCode }) }}</span>
        <span v-else-if="config?.registration_mode === 'closed'" class="account-help" role="status">{{ t('registrationClosed') }}</span>
        <span v-else-if="configError" class="account-help" role="alert">{{ t('configError') }} <button type="button" class="link-action" @click="loadConfig">{{ t('retry') }}</button></span>
      </div>
      <label for="register-code">{{ t('code') }}
        <input id="register-code" v-model.trim="form.email_code" minlength="6" maxlength="6" autocomplete="one-time-code" inputmode="numeric" required />
      </label>
      <label for="register-password">{{ t('password') }}
        <el-input id="register-password" v-model="form.password" type="password" show-password required maxlength="32" autocomplete="new-password" />
        <span class="account-help">{{ t('passwordHint') }} {{ t('symbols') }} <code>_ ! @ # $ % ^ &amp; * + - =</code></span>
      </label>
      <label for="register-confirm">{{ t('confirm') }}
        <el-input id="register-confirm" v-model="form.confirm_password" type="password" show-password required maxlength="32" autocomplete="new-password" />
      </label>
      <p v-if="error" class="account-errors" role="alert">{{ error }}</p>
      <button class="primary-action" type="submit" :disabled="busy || sending || !canRegister" :aria-busy="busy">{{ t('create') }} <SvgIcon name="right" :size="16" /></button>
    </form>
    <template #footer>{{ t('existing') }} <RouterLink :to="switchPage('/login')">{{ t('loginLink') }}</RouterLink></template>
  </AccountSheet>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import AccountSheet from '@/components/AccountSheet.vue'
import SvgIcon from '@/components/SvgIcon.vue'
import request from '@/utils/request'
import { accountError, useAccountCopy, useAccountNavigation, validPassword } from '@/i18n/account'
import { useAuthStore } from '@/stores/auth'

const { t } = useAccountCopy()
const { finish, switchPage } = useAccountNavigation()
const auth = useAuthStore()
const emailField = ref(null)
const config = ref(null)
const configError = ref(false)
const testCode = computed(() => config.value?.registration_mode === 'test' ? config.value.test_code : null)
const canRegister = computed(() => ['test', 'smtp'].includes(config.value?.registration_mode))
const busy = ref(false)
const sending = ref(false)
const error = ref('')
const form = reactive({
  username: '', nickname: 'Blog_' + Math.floor(10000 + Math.random() * 90000),
  email: '', email_code: '', password: '', confirm_password: '',
})
watch(() => form.email, () => { form.email_code = '' })
async function loadConfig() {
  configError.value = false
  try { config.value = await request.get('/auth/config') }
  catch { configError.value = true }
}
onMounted(loadConfig)

async function getCode() {
  if (sending.value || !emailField.value.reportValidity()) return
  const email = form.email
  error.value = ''
  sending.value = true
  try {
    await request.post('/auth/send-code', { email })
    if (email !== form.email) return
    ElMessage.success(t('codeSent'))
  } catch (e) {
    error.value = accountError(e, t)
  } finally {
    sending.value = false
  }
}

async function submit() {
  if (busy.value || sending.value || !canRegister.value) return
  if (!validPassword.test(form.password)) { error.value = t('passwordHint'); return }
  if (form.password !== form.confirm_password) { error.value = t('mismatch'); return }
  error.value = ''
  busy.value = true
  try {
    await auth.register({ ...form })
    ElMessage.success(t('created'))
    await finish()
  } catch (e) {
    error.value = accountError(e, t)
  } finally {
    busy.value = false
  }
}
</script>
