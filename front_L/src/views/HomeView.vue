<template>
  <div class="studio-page">
    <header class="page-heading">
      <div><h1>{{ t('studio.desk') }}</h1><p>{{ t('studio.intro') }}</p></div>
      <time class="desk-date" :datetime="dateKey"><SvgIcon name="calendar" :size="15" />{{ dateLabel }}</time>
    </header>

    <section class="composer" aria-labelledby="composer-title">
      <div class="compose-form">
        <div class="compose-label"><SvgIcon name="edit" :size="15" />{{ t('studio.newDraft') }}</div>
        <h2 id="composer-title">{{ t('studio.prompt') }}</h2>
        <form ref="composerForm" class="input-box" @submit.prevent="start" @invalid.capture="briefOpen = true">
          <textarea ref="input" v-model="topic" rows="2" maxlength="512" :aria-label="t('studio.topic')" :placeholder="t('studio.placeholder')" :disabled="creating" @keydown.ctrl.enter.prevent="composerForm?.requestSubmit()" @keydown.meta.enter.prevent="composerForm?.requestSubmit()"></textarea>
          <details class="composer-brief" :open="briefOpen" @toggle="briefOpen = $event.target.open">
            <summary><strong>{{ w('brief') }}</strong><span>{{ w(brief.level) }} · {{ w('wordUnit', {count: brief.word_count}) }}</span></summary>
            <div class="brief-fields">
              <label class="brief-wide">{{ w('purpose') }}<input v-model.trim="brief.purpose" maxlength="512" :placeholder="w('purposeHint')" :disabled="creating" /></label>
              <label>{{ w('audience') }}<select v-model="brief.level" :disabled="creating"><option v-for="level in levels" :key="level" :value="level">{{ w(level) }}</option></select></label>
              <label>{{ w('target') }}<input v-model.number="brief.word_count" type="number" min="100" max="10000" required step="1" :disabled="creating" /></label>
              <label>{{ w('style') }}<select v-model="brief.article_style" :disabled="creating"><option value="">{{ w('auto') }}</option><option v-for="style in styles" :key="style" :value="style">{{ w(style) }}</option></select></label>
              <label v-if="brief.article_style === 'custom'" class="brief-wide">{{ w('customStyle') }}<input v-model.trim="brief.article_style_custom" required maxlength="200" :disabled="creating" /></label>
            </div>
          </details>
          <div class="input-actions"><span class="count">{{ topic.length }} / 512</span>
            <button class="primary-action" :disabled="creating || quota.insufficient('title')">
              {{ t(creating ? 'studio.creating' : 'studio.start') }}<SvgIcon :name="creating ? 'loading' : 'right'" :class="{ 'animate-spin': creating }" :size="16" />
            </button>
          </div>
        </form>
        <GenerationAllowance v-if="auth.isLoggedIn" class="compose-quota" stage="title" />
        <p v-if="quota.rejection && quota.rejection.taskId === null" class="compose-error" role="alert">{{ quota.rejection.message }}</p>
      </div>
      <div class="press-art" aria-hidden="true"><img :src="press" alt="" fetchpriority="high" /></div>
    </section>

    <section class="desk-section" aria-labelledby="flow-heading">
      <div class="section-line"><h2 id="flow-heading">{{ t('studio.pipeline') }}</h2></div>
      <ol class="stage-strip">
        <li v-for="(icon, i) in stageIcons" :key="icon">
          <span class="stage-icon"><SvgIcon :name="icon" :size="20" /></span>
          <div><strong>{{ t('studio.stages[' + i + '][0]') }}</strong><p>{{ t('studio.stages[' + i + '][1]') }}</p></div>
          <SvgIcon v-if="i < 3" class="stage-arrow" name="right" :size="14" />
        </li>
      </ol>
    </section>

    <section v-if="auth.isLoggedIn && (recent.length || recentError)" class="desk-section">
      <div class="section-line"><h2>{{ t('studio.recent') }}</h2><router-link to="/my-articles">{{ t('studio.moreDrafts') }} <SvgIcon name="right" :size="14" /></router-link></div>
      <div v-if="recentError" class="recent-error">{{ t('studio.listFail') }} <button class="link-action" @click="loadRecent">{{ t('studio.retry') }}</button></div>
      <div v-else class="recent-list">
        <router-link v-for="a in recent" :key="a.task_id" :to="taskPath(a)"><SvgIcon name="document" :size="17" /><strong>{{ a.title || a.topic }}</strong><small>{{ t(a.job_status === 'queued' ? 'studio.queued' : 'studio.status.' + a.status) }}</small><SvgIcon name="right" :size="15" /></router-link>
      </div>
    </section>

    <section class="desk-section" aria-labelledby="ideas-heading">
      <div class="section-line"><h2 id="ideas-heading">{{ t('studio.ideas') }}</h2><span>{{ t('studio.ideaHint') }}</span></div>
      <div class="idea-grid">
        <button v-for="i in [0,1,2]" :key="i" class="idea-card" :aria-label="t('studio.useIdea') + ' · ' + idea(i,1)" @click="useIdea(i)">
          <span class="idea-image" :style="{ backgroundPosition: (i * 50) + '% center' }"></span>
          <span class="idea-text"><small>{{ idea(i,0) }}</small><strong>{{ idea(i,1) }}</strong></span>
          <span class="idea-go"><SvgIcon name="right" :size="16" /></span>
        </button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import SvgIcon from '@/components/SvgIcon.vue'
import GenerationAllowance from '@/components/GenerationAllowance.vue'
import { useQuotaStore } from '@/stores/quota'
import { createTask, generateTitles } from '@/api/task'
import { getMyArticles } from '@/api/article'
import { useAuthStore } from '@/stores/auth'
import { useWorkflowText } from '@/i18n/workflow'
import { taskPath } from '@/utils/taskWorkflow'
import press from '@/assets/press.webp'

const router = useRouter()
const auth = useAuthStore()
const quota = useQuotaStore()
const { t, locale } = useI18n()
const { t: w } = useWorkflowText()
const levels = ['general', 'medium', 'advanced', 'professional']
const styles = ['popular_science', 'technical', 'essay', 'prose', 'note', 'custom']
const defaultBrief = () => ({purpose:'', level:'medium', word_count:800, article_style:'', article_style_custom:''})
const brief = ref(defaultBrief())
const briefOpen = ref(false)
const topic = ref('')
const composerForm = ref(null)
const input = ref(null)
const creating = ref(false)
const stageIcons = ['search','outline','pen','document']
const today = new Date()
const dateKey = [today.getFullYear(), String(today.getMonth()+1).padStart(2,'0'), String(today.getDate()).padStart(2,'0')].join('-')
const dateLabel = computed(() => new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en', {month:'long',day:'numeric',weekday:'short'}).format(today))
const recent = ref([])
const recentError = ref(false)
let listVersion = 0
const draftKey = computed(() => 'blog-agent-brief:' + (auth.user?.id ?? 'guest'))
watch(draftKey, key => {
  let saved = {}
  try {
    const guestKey = 'blog-agent-brief:guest'
    const transferGuest = key !== guestKey && sessionStorage.getItem(guestKey + ':login')
    saved = JSON.parse(sessionStorage.getItem(transferGuest ? guestKey : key)) || {}
    if (transferGuest) {
      sessionStorage.removeItem(guestKey)
      sessionStorage.removeItem(guestKey + ':login')
    }
  } catch { /* A draft can still be composed with storage disabled. */ }
  topic.value = typeof saved.topic === 'string' ? saved.topic : ''
  brief.value = { ...defaultBrief(), ...saved.brief }
}, { immediate: true })
watch([topic, brief, draftKey], () => {
  try {
    if (topic.value || JSON.stringify(brief.value) !== JSON.stringify(defaultBrief())) {
      sessionStorage.setItem(draftKey.value, JSON.stringify({ topic: topic.value, brief: brief.value }))
    } else sessionStorage.removeItem(draftKey.value)
  } catch { /* Storage is optional. */ }
}, { deep: true })
watch(() => auth.user?.id, loadRecent, { immediate:true })
async function loadRecent() {
  const version = ++listVersion
  recent.value = []
  recentError.value = false
  if (!auth.isLoggedIn) return
  try {
    const res = await getMyArticles('created', { limit:3 })
    if (version === listVersion) recent.value = res.items.slice(0,3)
  } catch { if (version === listVersion) recentError.value = true }
}
function idea(i, part) { return t('studio.ideasList[' + i + '][' + part + ']') }
function useIdea(i) { topic.value = idea(i,1); input.value?.focus(); input.value?.scrollIntoView({block:'nearest'}) }
async function start() {
  if (creating.value || quota.insufficient('title')) return
  if (!topic.value.trim()) { input.value?.focus(); ElMessage.info(t('studio.required')); return }
  if (!auth.isLoggedIn) {
    try { sessionStorage.setItem(draftKey.value + ':login', '1') } catch { /* Storage is optional. */ }
    ElMessage.info(t('studio.draftSaved'))
    await router.push({path:'/login',query:{redirect:'/'}})
    return
  }
  creating.value = true
  quota.rejection = null
  try {
    const task = await createTask({
      topic: topic.value.trim(), purpose: brief.value.purpose || null,
      level: brief.value.level, word_count: brief.value.word_count,
      article_style: brief.value.article_style || null,
      article_style_custom: brief.value.article_style === 'custom' ? brief.value.article_style_custom : null
    })
    topic.value = ''
    brief.value = defaultBrief()
    briefOpen.value = false
    try { await generateTitles(task) } catch { /* The title page can resume the saved task. */ }
    if (router.currentRoute.value.name === 'Home') await router.push('/task/' + task.id + '/titles')
  } catch (e) { quota.recordAdmissionError(null, e) }
  finally { creating.value = false }
}
</script>

<style scoped>
.composer-brief {border-top:1px solid var(--line);margin:7px 0 10px;padding-top:9px;color:var(--ink);font-size:12px}
.composer-brief summary {cursor:pointer}.composer-brief summary strong{font-weight:650}.composer-brief summary span{margin-left:9px;color:var(--muted)}
.brief-fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:12px 0}.brief-wide{grid-column:1/-1}
.brief-fields label{display:grid;gap:4px;color:var(--muted);font-size:12px}.brief-fields :is(input,select){width:100%;min-width:0;min-height:36px;padding:5px 8px;color:var(--ink);border:1px solid var(--line);border-radius:4px;background:var(--surface)}
@media(max-width:480px){.brief-fields{grid-template-columns:repeat(2,minmax(0,1fr))}}
.compose-quota {margin-top:13px}.compose-error{color:var(--danger);font-size:13px;margin:8px 0 0}
.desk-date {display:flex;align-items:center;gap:7px;color:var(--muted);font-size:12px;white-space:nowrap;margin-bottom:4px}
.composer {display:grid;grid-template-columns:minmax(0,1.36fr) minmax(0,1fr);position:relative;isolation:isolate;overflow:hidden;border:1px solid #ded8c9;border-radius:10px;background:#f6f1e7}
.compose-form {position:relative;z-index:1;padding:26px 0 26px 30px}
.compose-label {display:flex;align-items:center;gap:7px;font-size:12px;font-weight:650;color:#9f402d}.compose-form h2 {font:700 clamp(25px,2.3vw,34px)/1.35 var(--serif);letter-spacing:-.025em;color:#302c26;margin:8px 0 16px}
.input-box {padding:13px 14px 11px;background:var(--surface);border:1px solid #cec9bd;border-radius:7px;box-shadow:0 2px 3px #46301b08}.input-box:focus-within {border-color:var(--accent);box-shadow:0 0 0 2px var(--tint)}
.input-box textarea {display:block;width:100%;resize:vertical;min-height:45px;max-height:220px;line-height:1.6;font-size:14px;background:transparent;border:0;outline:0;color:var(--ink)}.input-box textarea::placeholder {color:var(--muted)}
.input-actions {display:flex;align-items:center;justify-content:space-between;margin-top:4px}.count {font:11px var(--mono);color:var(--muted)}
.press-art {display:flex;align-items:center;justify-content:center;padding:12px 4% 8px 6%;background-image:radial-gradient(#ab97753d .7px,transparent .9px);background-size:6px 6px;mask-image:linear-gradient(to right,transparent,#000 13%);}
.press-art img {width:100%;height:clamp(180px,18vw,258px);object-fit:contain;mix-blend-mode:multiply}
.desk-section {margin-top:26px}.section-line {display:flex;align-items:center;justify-content:space-between;gap:15px;margin-bottom:13px}
.section-line h2 {font:700 22px/1.4 var(--serif);letter-spacing:-.025em}.section-line>span,.section-line>a {color:var(--muted);font-size:12px}.section-line>a:hover{color:var(--accent)}
.stage-strip {display:grid;grid-template-columns:repeat(4,minmax(0,1fr));list-style:none;margin:0;padding:0;border:1px solid var(--line);background:var(--surface);border-radius:8px}
.stage-strip li {position:relative;display:flex;align-items:center;gap:11px;padding:17px 15px;min-width:0}.stage-strip strong{font-size:14px;font-weight:650}.stage-strip p {font-size:12px;color:var(--muted);line-height:1.45;margin-top:3px}
.stage-icon {color:var(--accent);display:grid;place-items:center;width:35px;height:35px;border-radius:7px;background:var(--tint);flex-shrink:0}.stage-arrow{color:var(--muted);opacity:.62;position:absolute;right:-5px}
.idea-grid {display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px}
.idea-card {position:relative;display:flex;flex-direction:column;overflow:hidden;padding:0;text-align:left;border:1px solid var(--line);border-radius:8px;background:var(--surface);color:var(--ink);transition:transform .18s,border-color .18s}.idea-card:hover {transform:translateY(-2px);border-color:var(--accent)}
.idea-image {width:100%;height:clamp(84px,7.7vw,137px);background-image:url('../assets/subjects.webp');background-size:300% auto}
.idea-text {display:grid;gap:4px;padding:13px 38px 16px 16px}.idea-text small{font-size:11px;color:var(--muted);font-weight:550}.idea-text strong {font:650 clamp(15px,1.17vw,19px)/1.5 var(--serif)}
.idea-go {position:absolute;bottom:19px;right:15px;color:var(--muted);transform:rotate(-40deg)}
.recent-list,.recent-error {border:1px solid var(--line);border-radius:8px;background:var(--surface)}.recent-list a,.recent-error{padding:12px 16px}.recent-list a{display:flex;align-items:center;gap:11px}.recent-list a+a{border-top:1px solid var(--line)}.recent-list strong{font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-list small{margin-left:auto;color:var(--accent);white-space:nowrap}
@media(min-width:1550px){.compose-form{padding:34px 0 34px 38px}}
@media(max-width:1160px){.stage-strip li{gap:7px;padding:14px 10px}.stage-icon{width:28px;height:31px}.stage-strip p{font-size:11px}.stage-strip strong{font-size:13px}}
@media(max-width:950px){.stage-strip{grid-template-columns:repeat(2,minmax(0,1fr))}.stage-strip li:nth-child(-n+2){border-bottom:1px solid var(--line)}.stage-arrow{display:none}.compose-form{padding:20px 0 20px 20px}}
@media(max-width:600px){.desk-date{display:none}.composer{grid-template-columns:1fr}.compose-form{padding:20px 16px 16px}.compose-form h2{font-size:clamp(20px,5.6vw,25px);max-width:calc(100% - 68px);margin:8px 0 18px}.press-art{position:absolute;top:2px;right:0;width:min(25%,95px);height:74px;padding:0;z-index:-1}.press-art img{height:78px}.input-box{padding:10px}.desk-section{margin-top:22px}.section-line{gap:8px}.section-line h2{font-size:20px}.section-line>span{font-size:11px}.idea-grid{grid-template-columns:1fr;gap:9px}.idea-card{display:grid;grid-template-columns:85px 1fr;align-items:center}.idea-image{height:81px}.idea-text{padding:8px 35px 8px 13px}.idea-go{bottom:30px}.stage-strip li{padding:11px 8px}.stage-strip p{font-size:10.5px}}
</style>
