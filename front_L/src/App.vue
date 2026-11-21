<template>
  <div class="workspace-shell">
    <button v-if="navOpen" class="nav-mask" :aria-label="t('studio.close')" @click="closeNavigation"></button>
    <aside id="workspace-navigation" class="workspace-side" :class="{ opened: navOpen }">
      <button ref="closeButton" class="mobile-close" :aria-label="t('studio.close')" @click="closeNavigation"><SvgIcon name="close" :size="18" /></button>
      <router-link to="/" class="brand" aria-label="稿间 Blog Agent">
        <span class="brand-mark"><SvgIcon name="pen" :size="25" /></span>
        <span class="brand-type"><strong>{{ t('studio.brand') }}</strong><small>BLOG AGENT</small></span>
      </router-link>
      <nav class="side-navigation">
        <div v-for="group in nav" :key="group.label" class="nav-group">
          <p>{{ t('studio.' + group.label) }}</p>
          <router-link v-for="item in group.items" :key="item.path" :to="item.path" class="side-link" :class="{ selected: item.section === section }" :aria-current="item.section === section ? 'page' : undefined">
            <SvgIcon :name="item.icon" :size="18" />{{ t('studio.' + item.label) }}
          </router-link>
        </div>
      </nav>
      <div class="side-foot">
        <button @click="toggleTheme"><SvgIcon :name="dark ? 'moon' : 'sun'" :size="17" /><span>{{ t('studio.theme') }}</span><small>{{ t(dark ? 'studio.dark' : 'studio.light') }}</small></button>
        <button :title="t('nav.switchLang')" @click="setLocale(locale === 'zh' ? 'en' : 'zh')"><span class="language-icon">文</span><span>{{ t('studio.lang') }}</span><small>{{ locale === 'zh' ? '简体中文' : 'English' }}</small></button>
      </div>
    </aside>
    <div class="workspace-body" :inert="navOpen">
      <header class="workspace-bar">
        <button ref="menuButton" class="mobile-menu" aria-controls="workspace-navigation" :aria-expanded="navOpen" :aria-label="t('studio.menu')" @click="navOpen = !navOpen"><SvgIcon name="menu" /></button>
        <div class="breadcrumb"><span>{{ t('studio.workspace') }}</span><i>/</i><strong>{{ crumb }}</strong></div>
        <div class="tools"><SearchBox /><NotificationBell /><UserMenu /></div>
      </header>
      <main id="main-content" class="workspace-main">
        <router-view :key="route.path" />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch, watchEffect, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { setLocale } from '@/i18n'
import SvgIcon from '@/components/SvgIcon.vue'
import UserMenu from '@/components/UserMenu.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import SearchBox from '@/components/SearchBox.vue'

const route = useRoute()
const { t, locale } = useI18n()
const navOpen = ref(false)
const menuButton = ref(null), closeButton = ref(null)
const smallScreen = window.matchMedia('(max-width:790px)')
function closeNavigation() {
  navOpen.value = false
  nextTick(() => menuButton.value?.focus())
}
function onResize() { if (!smallScreen.matches) navOpen.value = false }
watch(navOpen, open => {
  document.body.style.overflow = open ? 'hidden' : ''
  if (open) nextTick(() => closeButton.value?.focus())
})
const dark = ref(document.documentElement.dataset.theme === 'dark')
const nav = [
  { label:'workspace', items:[{path:'/', label:'desk', icon:'desk', section:'desk'}, {path:'/my-articles', label:'library', icon:'library', section:'library'}] },
  { label:'discover', items:[{path:'/articles', label:'explore', icon:'compass', section:'explore'}] },
  { label:'personal', items:[{path:'/profile', label:'profile', icon:'user', section:'profile'}] }
]
const names = { Home:'desk', AllArticles:'explore', MyArticles:'library', Profile:'profile', Titles:'titles', Outline:'outline', Generating:'generating', Revision:'revision', BlogDetail:'reading', Snapshot:'snapshot', Login:'login', Register:'register' }
const crumb = computed(() => t('studio.' + (names[route.name] || 'desk')))
const readerSection = ref(null)
watch(() => route.name, (name, previous) => {
  if (name === 'BlogDetail') readerSection.value = previous === 'AllArticles' ? 'explore' : ['MyArticles','Generating','Home'].includes(previous) ? 'library' : null
})
const section = computed(() => route.name === 'BlogDetail' ? readerSection.value : ({Titles:'desk',Outline:'desk',Generating:'desk',Revision:'library',Snapshot:'library'}[route.name] || names[route.name]))
watch(() => route.fullPath, () => { navOpen.value = false })
watchEffect(() => { document.documentElement.lang = locale.value === 'zh' ? 'zh-CN' : 'en'; document.title = crumb.value + ' · ' + t('studio.brand') + ' Blog Agent' })
function toggleTheme() {
  dark.value = !dark.value
  const theme = dark.value ? 'dark' : 'light'
  document.documentElement.dataset.theme = theme
  document.documentElement.classList.toggle('dark',dark.value)
  localStorage.setItem('blog-agent-theme',theme)
}
function onEscape(e) {
  if (e.key === 'Escape' && navOpen.value) closeNavigation()
}
onMounted(() => { document.addEventListener('keydown',onEscape); smallScreen.addEventListener('change',onResize) })
onBeforeUnmount(() => { document.removeEventListener('keydown',onEscape); smallScreen.removeEventListener('change',onResize);document.body.style.overflow='' })
</script>

<style scoped>
.workspace-shell {--rail:212px;min-height:100vh}
.workspace-side {position:fixed;inset:0 auto 0 0;width:var(--rail);padding:0 16px 18px;background:var(--sidebar);border-right:1px solid var(--line);display:flex;flex-direction:column;z-index:35}
.brand {display:flex;align-items:center;gap:11px;height:89px;margin:0 9px 14px}
.brand-mark {width:40px;height:40px;display:grid;place-items:center;border-radius:8px;background:var(--accent);color:var(--on-accent)}
.brand-type {display:grid;gap:4px;line-height:1}.brand-type strong {font:700 25px/1 var(--serif);letter-spacing:.01em}.brand-type small {font:600 9px/1 var(--mono);letter-spacing:.14em;color:var(--muted)}
.nav-group {margin:10px 0 29px}.nav-group p {font-size:11px;color:var(--muted);margin:0 12px 9px;letter-spacing:.055em}
.side-link {display:flex;gap:12px;align-items:center;border-radius:6px;min-height:41px;padding:8px 13px;margin-bottom:3px;font-size:14px;color:var(--ink)}
.side-link:hover,.side-foot button:hover {background:var(--soft)}.side-link.selected {background:var(--tint);color:var(--accent);font-weight:650}
.side-foot {margin-top:auto;padding:14px 1px 0;border-top:1px solid var(--line)}
.side-foot button {display:flex;align-items:center;gap:11px;background:none;border:0;border-radius:5px;color:var(--muted);width:100%;padding:9px 9px;font-size:13px;text-align:left}.side-foot small {margin-left:auto;font-size:11px}.language-icon {width:17px;text-align:center}
.workspace-body {margin-left:var(--rail);min-width:0}.workspace-bar {height:63px;border-bottom:1px solid var(--line);padding:0 clamp(22px,3.4vw,58px);display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--paper);position:relative;z-index:25}
.breadcrumb {display:flex;align-items:center;gap:12px;font-size:12px;color:var(--muted);white-space:nowrap}.breadcrumb i {opacity:.55;font-style:normal}.breadcrumb strong {font-weight:550;color:var(--ink)}
.tools {display:flex;align-items:center;justify-content:flex-end;gap:16px;min-width:0}
.tools :deep(.search-box) {width:clamp(145px,17vw,250px);margin:0;flex:initial}.tools :deep(.search-input-wrap) {border-radius:6px;height:33px;background:var(--surface)}.tools :deep(.search-input) {width:100%;font-size:12px}
.tools :deep(.login-link),.tools :deep(.register-link),.tools :deep(.user-trigger) {font-size:13px;padding:6px 12px;border-radius:5px;box-shadow:none}
.tools :deep(.register-link) {background:var(--ink);color:var(--paper)}.tools :deep(.user-trigger) {background:var(--surface)}
.workspace-main {padding:30px clamp(22px,3.4vw,58px) 55px;max-width:1800px;margin:auto}
.mobile-menu,.mobile-close,.nav-mask {display:none}
@media(min-width:1700px){.workspace-shell{--rail:238px}}
@media(max-width:1090px){.workspace-shell{--rail:178px}.workspace-side{padding-left:10px;padding-right:10px}.tools{gap:9px}.workspace-main{padding:25px 24px 44px}}
@media(max-width:790px){.workspace-shell{--rail:210px}.workspace-side{transform:translateX(-101%);visibility:hidden}.workspace-side.opened{transform:none;visibility:visible}.mobile-close{display:grid;place-items:center;position:absolute;right:14px;top:22px;background:none;border:0;padding:5px;color:var(--muted)}.workspace-body{margin:0}.workspace-bar{height:54px;padding:0 16px}.workspace-main{padding:22px 16px 44px}.brand{height:70px}.mobile-menu{display:grid;place-items:center;border:0;background:none;color:var(--ink);padding:5px}.breadcrumb{margin-right:auto}.breadcrumb span,.breadcrumb i{display:none}.nav-mask{display:block;position:fixed;inset:0;background:#1c1b1959;border:0;z-index:34}.tools{gap:5px}}
@media(max-width:500px){.breadcrumb{display:none}.tools{flex:1;justify-content:space-between}.tools :deep(.search-box){flex:1;max-width:220px;width:auto}.tools :deep(.login-link),.tools :deep(.register-link){padding:6px 8px}.workspace-main{padding:20px 14px 36px}}
</style>
