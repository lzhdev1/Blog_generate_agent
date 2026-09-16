import { createI18n } from 'vue-i18n'
import zh from './locales/zh'
import en from './locales/en'

const LANG_KEY = 'blog-agent-lang'

function getInitialLocale() {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === 'zh' || saved === 'en') return saved
  } catch (e) {}
  const nav = navigator.language || 'zh-CN'
  return nav.toLowerCase().startsWith('en') ? 'en' : 'zh'
}

const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: getInitialLocale(),
  fallbackLocale: 'zh',
  messages: { zh, en }
})

export function setLocale(lang) {
  i18n.global.locale.value = lang
  try {
    localStorage.setItem(LANG_KEY, lang)
  } catch (e) {}
}

export default i18n
