import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

const messages = {
  zh: {
    signIn: '登录', create: '创建账号', loginTitle: '登录创作台', registerTitle: '创建写作账号',
    loginIntro: '继续上次的稿件，查看收藏和已下载的文章。', registerIntro: '保存你的选题和草稿，选择何时公开作品。',
    newUser: '还没有账号？', existing: '已经有账号？', registerLink: '去注册', loginLink: '去登录',
    account: '用户名或邮箱', password: '密码', username: '用户名', nickname: '笔名', email: '邮箱',
    code: '验证码', getCode: '获取验证码', testCode: '测试验证码为 {code}', codeSent: '请查看邮箱中的验证码。',
    registrationClosed: '当前未开放注册。已有账号可以直接登录。', configError: '暂时无法读取注册方式。',
    confirm: '确认密码', passwordHint: '8–32 位，须含字母和数字。', symbols: '支持的符号',
    usernameHint: '3–32 位英文字母或数字', nicknameHint: '2–32 位中文、英文字母、数字、空格或下划线',
    nicknamePlaceholder: '用于文章署名', badEmail: '请输入有效邮箱', badCode: '请输入 6 位验证码',
    fill: '请填写此项', mismatch: '两次输入的密码不一致', submitError: '请求未完成，请重试。',
    signedIn: '已登录', created: '账号已创建', profile: '账户设置', profileIntro: '查看作者资料，管理余额和登录密码。',
    details: '作者资料', balance: '模拟账户余额', topup: '模拟充值', topupHelp: '余额可用于购买文章的下载权限。',
    amount: '充值金额（元）', amountHint: '每次可充值 0.01 至 10,000 元。', paymentCode: '模拟支付确认码',
    demoHelp: '此操作仅增加站内模拟余额。', cancel: '取消', add: '确认充值', added: '余额已更新',
    security: '修改密码', current: '当前密码', newPassword: '新密码', repeat: '确认新密码', update: '保存新密码',
    changed: '密码已修改，请重新登录', session: '账户管理', logout: '退出登录', deactivate: '注销账号',
    deleteHelp: '注销会永久删除你的账号和创作的文章。其他用户已购买或下载的副本仍会保留。',
    confirmDelete: '永久注销账号', deleted: '账号已注销', loading: '正在读取账户资料…', retry: '重新加载',
  },
  en: {
    signIn: 'Sign in', create: 'Create account', loginTitle: 'Return to your desk', registerTitle: 'Create your account',
    loginIntro: 'Pick up your drafts and revisit your saved and downloaded articles.', registerIntro: 'Save your ideas and drafts, and choose when to share your work.',
    newUser: 'New to Folio?', existing: 'Already have an account?', registerLink: 'Create an account', loginLink: 'Sign in',
    account: 'Username or email', password: 'Password', username: 'Username', nickname: 'Pen name', email: 'Email',
    code: 'Verification code', getCode: 'Get code', testCode: 'The test verification code is {code}', codeSent: 'Check your email for the verification code.',
    registrationClosed: 'Registration is currently closed. Existing users can still sign in.', configError: 'Registration options are temporarily unavailable.',
    confirm: 'Confirm password', passwordHint: 'Use 8–32 characters with a letter and a number.', symbols: 'Allowed symbols',
    usernameHint: '3–32 letters or numbers', nicknameHint: '2–32 Chinese characters, letters, numbers, spaces or underscores',
    nicknamePlaceholder: 'Your article byline', badEmail: 'Enter a valid email address', badCode: 'Enter the six-character code',
    fill: 'Complete this field', mismatch: 'The passwords do not match', submitError: 'The request did not finish. Please try again.',
    signedIn: 'Signed in', created: 'Account created', profile: 'Account settings', profileIntro: 'Manage your author details, balance and password.',
    details: 'Author details', balance: 'Demo balance', topup: 'Add demo funds', topupHelp: 'Use your balance to purchase article downloads.',
    amount: 'Amount (CNY)', amountHint: 'Add ¥0.01 to ¥10,000 at a time.', paymentCode: 'Demo payment code',
    demoHelp: 'This adds simulated funds to your account.', cancel: 'Cancel', add: 'Add funds', added: 'Balance updated',
    security: 'Change password', current: 'Current password', newPassword: 'New password', repeat: 'Confirm new password', update: 'Save new password',
    changed: 'Password changed. Please sign in again.', session: 'Manage account', logout: 'Sign out', deactivate: 'Delete account',
    deleteHelp: 'This permanently deletes your account and articles. Other readers keep their purchased or downloaded copies.',
    confirmDelete: 'Permanently delete account', deleted: 'Account deleted', loading: 'Loading account details…', retry: 'Try again',
  },
}

export function useAccountCopy() {
  return useI18n({ useScope: 'local', messages })
}

export function useAccountNavigation() {
  const route = useRoute()
  const router = useRouter()
  const destination = computed(() => {
    const path = route.query.redirect
    if (typeof path !== 'string' || !path.startsWith('/') || path.startsWith('//') || path.includes('\\')) return '/'
    const target = router.resolve(path)
    return target.matched.length && !['Login', 'Register'].includes(target.name) ? target.fullPath : '/'
  })
  function switchPage(path) {
    return { path, query: destination.value === '/' ? {} : { redirect: destination.value } }
  }
  return { switchPage, finish: () => router.replace(destination.value) }
}

export const validPassword = /^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_!@#$%^&*+=-]{8,32}$/

export function accountError(error, t) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (typeof detail?.message === 'string') return detail.message
  if (Array.isArray(detail)) return detail.map(item => item.msg).filter(Boolean).join(' · ')
  return t('submitError')
}
