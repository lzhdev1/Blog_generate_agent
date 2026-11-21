<template>
  <section v-if="store.signedIn" class="generation-allowance" :aria-label="t('label')">
    <template v-if="store.quota">
      <div class="allowance-heading">
        <strong>{{ t('label') }}</strong>
        <span>{{ t('amount', { remaining:store.quota.remaining, limit:store.quota.daily_limit }) }}</span>
      </div>
      <p>{{ costText }} {{ t('renew', { time:resetTime }) }}</p>
      <p v-if="shortfall || (stage && atCapacity)" class="allowance-attention">
        {{ t(shortfall ? 'insufficient' : 'atCapacity', { count:store.quota.active_jobs }) }}
        <button type="button" :disabled="store.loading" @click="store.refresh">{{ t('refresh') }}</button>
      </p>
    </template>
    <p v-else-if="store.unavailable">{{ t('unavailable') }} <button type="button" :disabled="store.loading" @click="store.refresh">{{ t('refresh') }}</button></p>
    <p v-else-if="store.loading" role="status">{{ t('loading') }}</p>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useQuotaStore } from '@/stores/quota'
import { useAuthStore } from '@/stores/auth'

const props = defineProps({ stage: String })
const { t, locale } = useI18n({ useScope:'local', messages:{
  zh:{label:'免费创作额度',amount:'今日剩余 {remaining} / {limit} 点',refresh:'刷新额度',loading:'正在读取额度…',
    revisionCost:'修订稿审核每次 {points} 点。',
    cost:'标题 {title} 点，大纲 {outline} 点，正文 {content} 点。重新生成消耗相同点数。',renew:'{time} 重置。',
    insufficient:'本阶段剩余额度不足。',atCapacity:'已有 {count} 个阶段在排队或执行，请等待任务结束。',unavailable:'暂时无法读取创作额度。'},
  en:{label:'Free writing credits',amount:'{remaining} / {limit} credits left today',refresh:'Refresh credits',loading:'Loading credits…',
    revisionCost:'A revision review costs {points} credit(s).',
    cost:'Titles {title}, outline {outline}, article {content} credits. Regeneration costs the same.',renew:'Resets {time}.',
    insufficient:'Too few credits for this stage.',atCapacity:'{count} stages are queued or running. Wait for one to finish.',unavailable:'Writing credits are temporarily unavailable.'}
}})
const store = useQuotaStore()
const auth = useAuthStore()
const costText = computed(() => {
  const costs=store.quota?.stage_costs
  if (!costs) return ''
  return props.stage === 'revision' ? t('revisionCost',{points:costs.revision}) : t('cost',costs)
})
const shortfall = computed(() => props.stage && store.insufficient(props.stage))
const atCapacity = computed(() => store.quota && store.quota.active_jobs >= store.quota.max_active_jobs)
const resetTime = computed(() => {
  const time = new Date(store.quota?.resets_at)
  return Number.isFinite(+time) ? new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en', { month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit' }).format(time) : '—'
})
let reset
watch(() => store.quota?.resets_at, at => {
  clearTimeout(reset)
  const delay = Date.parse(at) - Date.now()
  if (delay > 0) reset = setTimeout(() => store.refresh(), Math.min(delay + 1000, 2147483647))
}, { immediate:true })
watch(() => auth.token, token => { if (token) void store.refresh() }, { immediate:true })
function onVisible() { if (document.visibilityState === 'visible') void store.refresh() }
onMounted(() => document.addEventListener('visibilitychange',onVisible))
onBeforeUnmount(() => { clearTimeout(reset); document.removeEventListener('visibilitychange',onVisible) })
</script>

<style scoped>
.generation-allowance {color:var(--muted);font-size:12px;line-height:1.65}
.allowance-heading {display:flex;align-items:baseline;flex-wrap:wrap;justify-content:space-between;gap:3px 10px}
.allowance-heading strong {font-size:13px;color:var(--ink)}
.allowance-heading span {color:var(--accent);font-weight:600;font-variant-numeric:tabular-nums}
.generation-allowance p {margin:4px 0 0}
.allowance-attention {color:var(--warning)}
.generation-allowance button {padding:0;border:0;background:none;color:var(--accent);text-decoration:underline;text-underline-offset:2px;font-size:12px;cursor:pointer}
</style>
