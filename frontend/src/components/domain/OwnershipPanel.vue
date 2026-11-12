<template>
  <div class="panel ownership">
    <div class="panel__title">
      <h2>归属时间线</h2>
      <span class="mono ownership__tag">ownership · {{ signal.code }}</span>
    </div>

    <p class="ownership__rule">
      归属按采集时间生效：切换时刻之前的样本仍归原设备，之后的新样本归新设备；历史数据不回填、旧运行仍按原设备回看导出。
    </p>

    <div v-if="timeline" class="ownership__current">
      <span class="eyebrow">当前归属</span>
      <span class="mono ownership__device">{{ timeline.current.device_code }}</span>
      <span class="ownership__device-name">{{ timeline.current.device_name || '—' }}</span>
    </div>

    <table v-if="timeline && timeline.segments.length" class="table table--mono ownership__table">
      <thead>
        <tr>
          <th>归属设备</th>
          <th>生效起</th>
          <th>生效止</th>
          <th>影响样本</th>
          <th>登记</th>
          <th>备注</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="segment in timeline.segments" :key="segment.id">
          <td>
            <span class="ownership__seg-device">{{ segment.device_code }}</span>
            <span class="ownership__kind" :class="`ownership__kind--${segment.kind}`">
              {{ segment.kind === 'baseline' ? '基线' : '切换' }}
            </span>
          </td>
          <td>{{ formatDateTime(segment.effective_from) }}</td>
          <td>{{ segment.effective_to ? formatDateTime(segment.effective_to) : '至今' }}</td>
          <td>{{ segment.sample_count.toLocaleString() }}</td>
          <td>{{ segment.created_by_name ?? '—' }}</td>
          <td class="ownership__note">{{ segment.note || '—' }}</td>
        </tr>
      </tbody>
    </table>
    <p v-else-if="timeline" class="ownership__empty">尚无归属切换登记，全部样本归当前设备。</p>
    <p v-if="loading" class="ownership__empty mono">读取归属时间线…</p>

    <form v-if="auth.canWrite" class="ownership__form" @submit.prevent="submit">
      <div class="ownership__form-title eyebrow">登记归属切换（检修改接）</div>
      <div class="ownership__grid">
        <label>
          <span class="label">新设备编码</span>
          <input v-model="form.device_code" class="input mono" type="text" placeholder="例如：M-12" required />
        </label>
        <label>
          <span class="label">新设备名称（留空沿用设备档案）</span>
          <input v-model="form.device_name" class="input" type="text" placeholder="例如：M-12 注塑机（海天 MA1200）" />
        </label>
        <label>
          <span class="label">生效时刻（采集时间）</span>
          <input v-model="form.effective_from" class="input mono" type="datetime-local" step="1" required />
        </label>
        <label>
          <span class="label">备注</span>
          <input v-model="form.note" class="input" type="text" placeholder="例如：检修后 M-10 液压压力标签改接 M-12" />
        </label>
      </div>
      <div class="ownership__actions">
        <button class="btn btn-ochre" type="submit" :disabled="submitting">
          {{ submitting ? '登记中…' : '登记切换' }}
        </button>
        <span v-if="successLine" class="mono ownership__success">{{ successLine }}</span>
      </div>
    </form>
    <p v-else class="ownership__readonly">当前角色只读；归属切换由数据工程师登记。</p>

    <div v-if="conflictLine" class="ownership__conflict">
      <div class="ownership__conflict-tag mono">CONFLICT · 归属重叠已拒绝</div>
      <p>{{ conflictLine }}</p>
    </div>
    <ErrorNotice v-else :error="error" />
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import ErrorNotice from '../common/ErrorNotice.vue'
import { fetchOwnership, reassignSignal } from '../../api/sources'
import { useAuthStore } from '../../stores/authStore'
import type { OwnershipTimeline, Signal } from '../../types/source'
import type { ApiError } from '../../types/api'
import { formatDateTime } from '../../utils/format'

const props = defineProps<{ signal: Signal }>()
const emit = defineEmits<{ changed: [] }>()

const auth = useAuthStore()
const timeline = ref<OwnershipTimeline | null>(null)
const loading = ref(false)
const submitting = ref(false)
const error = ref<ApiError | null>(null)
const conflictLine = ref('')
const successLine = ref('')

const form = reactive({
  device_code: '',
  device_name: '',
  effective_from: '',
  note: '',
})

const signalId = computed(() => props.signal.id)

async function load() {
  loading.value = true
  error.value = null
  try {
    timeline.value = await fetchOwnership(signalId.value)
  } catch (err) {
    error.value = err as ApiError
  } finally {
    loading.value = false
  }
}

function describeConflict(err: ApiError): string {
  const conflict = (err.detail?.conflict ?? null) as {
    device_code?: string
    effective_from?: string
    effective_to?: string | null
  } | null
  if (!conflict) return err.message
  const range = `${formatDateTime(conflict.effective_from)} → ${conflict.effective_to ? formatDateTime(conflict.effective_to) : '至今'}`
  return `${err.message}（既有区间：${conflict.device_code ?? '?'} · ${range}）`
}

async function submit() {
  submitting.value = true
  error.value = null
  conflictLine.value = ''
  successLine.value = ''
  try {
    const result = await reassignSignal(signalId.value, {
      device_code: form.device_code.trim(),
      device_name: form.device_name.trim(),
      effective_from: form.effective_from,
      note: form.note.trim(),
    })
    successLine.value = `已登记：${formatDateTime(result.segment.effective_from)} 起归 ${result.segment.device_code} · 影响样本 ${result.affected_samples.toLocaleString()} 条`
    form.device_code = ''
    form.device_name = ''
    form.effective_from = ''
    form.note = ''
    await load()
    emit('changed')
  } catch (err) {
    const apiError = err as ApiError
    if (apiError.status === 409) {
      conflictLine.value = describeConflict(apiError)
    } else {
      error.value = apiError
    }
  } finally {
    submitting.value = false
  }
}

watch(signalId, () => {
  conflictLine.value = ''
  successLine.value = ''
  error.value = null
  load()
}, { immediate: true })
</script>

<style scoped>
.ownership {
  margin-top: 26px;
}
.ownership__tag {
  font-size: 10px;
  color: var(--ink-faint);
}
.ownership__rule {
  font-size: 11px;
  color: var(--ink-soft);
  margin: 0 0 12px;
  max-width: 72ch;
  line-height: 1.7;
}
.ownership__current {
  display: flex;
  align-items: baseline;
  gap: 12px;
  border-bottom: 1px solid var(--rule);
  padding-bottom: 10px;
  margin-bottom: 4px;
}
.ownership__device {
  font-size: 15px;
  color: var(--ink-green);
  letter-spacing: 0.08em;
}
.ownership__device-name {
  font-size: 11.5px;
  color: var(--ink-soft);
}
.ownership__table {
  margin-top: 6px;
}
.ownership__seg-device {
  letter-spacing: 0.06em;
}
.ownership__kind {
  margin-left: 8px;
  font-size: 9px;
  padding: 1px 5px;
  border: 1px solid var(--rule);
  color: var(--ink-faint);
}
.ownership__kind--reassignment {
  color: var(--ochre-deep);
  border-color: var(--ochre);
}
.ownership__note {
  font-family: var(--font-serif);
  font-size: 10.5px;
  color: var(--ink-soft);
}
.ownership__empty {
  font-size: 11px;
  color: var(--ink-faint);
  padding: 10px 0;
  margin: 0;
}
.ownership__form {
  margin-top: 18px;
  border-top: 1px solid var(--rule-strong);
  padding-top: 14px;
}
.ownership__form-title {
  margin-bottom: 10px;
}
.ownership__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 18px;
}
.ownership__grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ownership__actions {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 14px;
}
.ownership__success {
  font-size: 10.5px;
  color: var(--ok);
}
.ownership__readonly {
  margin: 14px 0 0;
  font-size: 10.5px;
  color: var(--ink-faint);
}
.ownership__conflict {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  gap: 14px;
  margin-top: 14px;
  border-left: 3px solid var(--alert);
  background: oklch(0.955 0.02 40 / 0.55);
  padding: 10px 14px;
  font-size: 11.5px;
}
.ownership__conflict-tag {
  font-size: 9.5px;
  letter-spacing: 0.14em;
  color: var(--alert);
  padding-top: 2px;
}
.ownership__conflict p {
  margin: 0;
  color: var(--ink);
}
@media (max-width: 1080px) {
  .ownership__grid {
    grid-template-columns: 1fr;
  }
}
</style>
