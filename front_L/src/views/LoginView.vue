<template>
  <AccountSheet :title="t('loginTitle')" :description="t('loginIntro')">
    <form class="account-form" @submit.prevent="submit">
      <label for="login-account">{{ t('account') }}
        <input id="login-account" v-model.trim="account" required maxlength="128" autocomplete="username" />
      </label>
      <label for="login-password">{{ t('password') }}
        <el-input id="login-password" v-model="password" type="password" show-password required maxlength="64" autocomplete="current-password" />
      </label>
      <p v-if="error" class="account-errors" role="alert">{{ error }}</p>
      <button class="primary-action" type="submit" :disabled="busy" :aria-busy="busy">
        {{ t('signIn') }} <SvgIcon name="right" :size="16" />
      </button>
    </form>
    <template #footer>{{ t('newUser') }} <RouterLink :to="switchPage('/register')">{{ t('registerLink') }}</RouterLink></template>
  </AccountSheet>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import AccountSheet from '@/components/AccountSheet.vue'
import SvgIcon from '@/components/SvgIcon.vue'
import { accountError, useAccountCopy, useAccountNavigation } from '@/i18n/account'
import { useAuthStore } from '@/stores/auth'

const { t } = useAccountCopy()
const { finish, switchPage } = useAccountNavigation()
const auth = useAuthStore()
const account = ref('')
const password = ref('')
const busy = ref(false)
const error = ref('')

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await auth.login(account.value, password.value)
    ElMessage.success(t('signedIn'))
    await finish()
  } catch (e) {
    error.value = accountError(e, t)
  } finally {
    busy.value = false
  }
}
</script>
