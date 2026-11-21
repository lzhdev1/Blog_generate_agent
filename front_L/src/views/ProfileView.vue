<template>
  <section class="profile-space">
    <header class="page-heading"><div><h1>{{ t('profile') }}</h1><p>{{ t('profileIntro') }}</p></div></header>
    <div v-if="loadError" class="profile-load-error" role="alert">{{ loadError }} <button class="link-action" @click="load">{{ t('retry') }}</button></div>
    <p v-if="!auth.user && loading" role="status">{{ t('loading') }}</p>
    <div v-if="auth.user" class="profile-layout">
      <div class="profile-column">
        <section class="profile-panel">
          <h2>{{ t('details') }}</h2>
          <div class="profile-name"><span aria-hidden="true">{{ auth.user.nickname?.slice(0, 1) }}</span><strong>{{ auth.user.nickname }}</strong></div>
          <dl><dt>{{ t('username') }}</dt><dd>{{ auth.user.username }}</dd><dt>{{ t('email') }}</dt><dd>{{ auth.user.email }}</dd></dl>
        </section>
        <section class="profile-panel profile-wallet">
          <h2>{{ t('balance') }}</h2><strong class="profile-amount">{{ money }}</strong>
          <p>{{ t('topupHelp') }}</p><button v-if="demoRecharge" class="quiet-action" @click="openTopup">{{ t('topup') }}</button>
        </section>
        <GenerationAllowance class="profile-panel" />
      </div>
      <div class="profile-column">
        <section class="profile-panel">
          <h2>{{ t('security') }}</h2>
          <form class="account-form" @submit.prevent="changePassword">
            <label for="old-password">{{ t('current') }}
              <el-input id="old-password" v-model="passwords.old_password" type="password" required maxlength="64" autocomplete="current-password" show-password />
            </label>
            <label for="new-password">{{ t('newPassword') }}
              <el-input id="new-password" v-model="passwords.new_password" type="password" required maxlength="32" autocomplete="new-password" show-password />
              <span class="account-help">{{ t('passwordHint') }} {{ t('symbols') }} <code>_ ! @ # $ % ^ &amp; * + - =</code></span>
            </label>
            <label for="repeat-password">{{ t('repeat') }}
              <el-input id="repeat-password" v-model="passwords.confirm_new_password" type="password" required maxlength="32" autocomplete="new-password" show-password />
            </label>
            <p v-if="passwordError" class="account-errors" role="alert">{{ passwordError }}</p>
            <div><button class="primary-action" :disabled="busy" type="submit">{{ t('update') }}</button></div>
          </form>
        </section>
        <section class="profile-panel profile-session">
          <h2>{{ t('session') }}</h2><div class="profile-actions">
            <button class="quiet-action" :disabled="busy" @click="logout">{{ t('logout') }}</button>
            <button class="link-action" :disabled="busy" @click="openDelete">{{ t('deactivate') }}</button>
          </div>
        </section>
      </div>
    </div>

    <el-dialog v-model="topupOpen" :title="t('topup')" width="420px" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" append-to-body>
      <form class="account-form" @submit.prevent="topup">
        <p class="account-help">{{ t('demoHelp') }}</p>
        <label for="amount">{{ t('amount') }}<input id="amount" v-model="amount" required type="number" inputmode="decimal" min="0.01" max="10000" step="0.01" />
          <span class="account-help">{{ t('amountHint') }}</span>
        </label>
        <label for="payment-code">{{ t('paymentCode') }}<input id="payment-code" v-model="paymentCode" maxlength="6" required autocomplete="off" /></label>
        <p v-if="dialogError" class="account-errors" role="alert">{{ dialogError }}</p>
        <div class="profile-dialog-actions"><button class="quiet-action" type="button" :disabled="busy" @click="topupOpen = false">{{ t('cancel') }}</button>
          <button class="primary-action" type="submit" :disabled="busy">{{ t('add') }}</button></div>
      </form>
    </el-dialog>
    <el-dialog v-model="deleteOpen" :title="t('deactivate')" width="420px" :close-on-click-modal="!busy" :close-on-press-escape="!busy" :show-close="!busy" append-to-body>
      <p>{{ t('deleteHelp') }}</p><p v-if="dialogError" class="account-errors" role="alert">{{ dialogError }}</p>
      <template #footer><div class="profile-dialog-actions">
        <button class="quiet-action" :disabled="busy" @click="deleteOpen = false">{{ t('cancel') }}</button>
        <button class="primary-action" :disabled="busy" @click="deactivate">{{ t('confirmDelete') }}</button>
      </div></template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { accountError, useAccountCopy, validPassword } from '@/i18n/account'
import { useAuthStore } from '@/stores/auth'
import request from '@/utils/request'
import GenerationAllowance from '@/components/GenerationAllowance.vue'
import '@/assets/styles/account.css'

const { t, locale } = useAccountCopy()
const router = useRouter()
const auth = useAuthStore()
const demoRecharge = ref(false)
onMounted(async () => {
  try { demoRecharge.value = (await request.get('/auth/config')).demo_recharge_enabled === true }
  catch { demoRecharge.value = false }
})
const money = computed(() => new Intl.NumberFormat(locale.value, { style: 'currency', currency: 'CNY' }).format(Number(auth.user?.balance) || 0))
const loading = ref(false)
const loadError = ref('')
const busy = ref(false)
const topupOpen = ref(false)
const deleteOpen = ref(false)
const amount = ref(100)
const paymentCode = ref('888888')
const passwords = reactive({ old_password: '', new_password: '', confirm_new_password: '' })
const passwordError = ref('')
const dialogError = ref('')

async function load() {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  try { await auth.fetchMe() }
  catch (e) { loadError.value = accountError(e, t) }
  finally { loading.value = false }
}
onMounted(load)

function openTopup() {
  amount.value = 100
  dialogError.value = ''
  topupOpen.value = true
}
function openDelete() {
  dialogError.value = ''
  deleteOpen.value = true
}
async function topup() {
  if (busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await auth.recharge(Number(amount.value), paymentCode.value)
    topupOpen.value = false
    ElMessage.success(t('added'))
  } catch (e) { dialogError.value = accountError(e, t) }
  finally { busy.value = false }
}
async function changePassword() {
  if (busy.value) return
  if (!validPassword.test(passwords.new_password)) { passwordError.value = t('passwordHint'); return }
  if (passwords.new_password !== passwords.confirm_new_password) { passwordError.value = t('mismatch'); return }
  busy.value = true
  passwordError.value = ''
  try {
    await request.put('/auth/password', { ...passwords })
    ElMessage.success(t('changed'))
    auth.logout()
    await router.replace({ path: '/login', query: { redirect: '/profile' } })
  } catch (e) { passwordError.value = accountError(e, t) }
  finally { busy.value = false }
}
async function deactivate() {
  if (busy.value) return
  busy.value = true
  dialogError.value = ''
  try {
    await request.delete('/auth/account')
    ElMessage.success(t('deleted'))
    deleteOpen.value = false
    logout()
  } catch (e) { dialogError.value = accountError(e, t) }
  finally { busy.value = false }
}
function logout() {
  auth.logout()
  router.replace('/')
}
</script>

<style scoped>
.profile-space {max-width:1060px;margin:0 auto}
.profile-layout {display:grid;grid-template-columns:minmax(230px,.9fr) minmax(290px,1.1fr);gap:20px;align-items:start}
.profile-column {display:grid;gap:18px;min-width:0}
.profile-panel {background:var(--surface);border:1px solid var(--line);border-radius:9px;padding:clamp(19px,2.3vw,30px);min-width:0}
.profile-panel h2 {font:600 22px/1.3 var(--serif);margin:0 0 20px}
.profile-name {display:flex;align-items:center;gap:14px;margin-bottom:22px;overflow-wrap:anywhere}
.profile-name span {width:46px;height:46px;flex:none;border-radius:50%;background:var(--tint);color:var(--accent);display:grid;place-items:center;font:600 24px var(--serif)}
.profile-name strong {font:600 23px var(--serif)}
.profile-panel dl {margin:0;display:grid;grid-template-columns:auto 1fr;gap:14px 24px;border-top:1px solid var(--line);padding-top:17px;font-size:14px}
.profile-panel dt,.profile-wallet p {color:var(--muted)}.profile-panel dd {margin:0;text-align:right;overflow-wrap:anywhere}
.profile-wallet {background:var(--tint);border-color:color-mix(in srgb,var(--accent) 18%,var(--line))}
.profile-wallet h2 {margin-bottom:7px}
.profile-amount {display:block;font:500 clamp(31px,3.4vw,45px) var(--serif);font-variant-numeric:tabular-nums}
.profile-wallet p {font-size:13px;margin:5px 0 17px}
.profile-actions,.profile-dialog-actions {display:flex;align-items:center;gap:15px;flex-wrap:wrap}
.profile-dialog-actions {justify-content:flex-end}.profile-session .link-action {color:var(--danger)}
.profile-load-error {margin:0 0 18px;color:var(--danger)}
@media(max-width:790px){.profile-layout{gap:14px}}
@media(max-width:640px){.profile-layout{grid-template-columns:1fr}.profile-panel{padding:20px}.profile-name{margin-bottom:14px}}
</style>
