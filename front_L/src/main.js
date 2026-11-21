import { computed, createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElButton, ElDialog, ElDropdown, ElForm, ElInput, ElInputNumber,
  ElMessage, ElMessageBox, ElSwitch, provideGlobalConfig
} from 'element-plus'
import 'element-plus/es/components/dialog/style/css'
import 'element-plus/es/components/dropdown/style/css'
import 'element-plus/es/components/dropdown-menu/style/css'
import 'element-plus/es/components/dropdown-item/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/input-number/style/css'
import 'element-plus/es/components/message/style/css'
import 'element-plus/es/components/message-box/style/css'
import 'element-plus/es/components/switch/style/css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import en from 'element-plus/es/locale/lang/en'
import App from './App.vue'
import router from './router'
import i18n from './i18n'
import './assets/styles/main.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(i18n)

// Dropdown and Form also register their menu, item and field components.
for (const plugin of [ElButton, ElDialog, ElDropdown, ElForm, ElInput, ElInputNumber, ElMessage, ElMessageBox, ElSwitch]) {
  app.use(plugin)
}
provideGlobalConfig(computed(() => ({ locale: i18n.global.locale.value === 'en' ? en : zhCn })), app, true)

app.mount('#app')
