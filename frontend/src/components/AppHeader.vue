<template>
  <header class="topbar">
    <div class="topbar__left">
      <button class="brand" @click="router.push('/')">MiroFish</button>

      <!-- 五个阶段是真实的执行顺序，直接展示整条进度而不是 "Step 4/5" -->
      <ol class="steps" :aria-label="`当前阶段：${STEP_NAMES[currentStep - 1]}`">
        <li
          v-for="(name, i) in STEP_NAMES"
          :key="name"
          class="steps__item"
          :class="{
            'is-current': currentStep === i + 1,
            'is-done': currentStep > i + 1
          }"
          :aria-current="currentStep === i + 1 ? 'step' : undefined"
        >
          <span class="steps__dot" aria-hidden="true"></span>
          <span class="steps__label">{{ name }}</span>
        </li>
      </ol>
    </div>

    <div class="topbar__right">
      <div v-if="showViewSwitcher" class="segmented" role="group" aria-label="视图模式">
        <button
          v-for="mode in VIEW_MODES"
          :key="mode.value"
          class="segmented__btn"
          :class="{ 'is-active': modelValue === mode.value }"
          :aria-pressed="modelValue === mode.value"
          @click="$emit('update:modelValue', mode.value)"
        >
          {{ mode.label }}
        </button>
      </div>

      <span class="status" :class="statusClass">
        <span class="mf-dot" :class="{ 'mf-dot--pulse': statusClass === 'processing' }"></span>
        {{ statusText }}
      </span>

      <slot name="actions" />
    </div>
  </header>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const STEP_NAMES = ['图谱构建', '环境搭建', '开始模拟', '报告生成', '深度互动']

const VIEW_MODES = [
  { value: 'graph', label: '图谱' },
  { value: 'split', label: '双栏' },
  { value: 'workbench', label: '工作台' }
]

defineProps({
  /** 当前阶段，1–5 */
  currentStep: { type: Number, required: true },
  /** 视图模式，配合 v-model 使用 */
  modelValue: { type: String, default: 'split' },
  showViewSwitcher: { type: Boolean, default: true },
  /** '' | 'processing' | 'completed' | 'error' */
  statusClass: { type: String, default: '' },
  statusText: { type: String, default: '' }
})

defineEmits(['update:modelValue'])
</script>

<style scoped>
.topbar {
  flex: none;
  height: var(--mf-header-height);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mf-space-5);
  padding: 0 var(--mf-space-5);
  background: var(--mf-surface);
  border-bottom: 1px solid var(--mf-separator);
  z-index: 10;
}

.topbar__left,
.topbar__right {
  display: flex;
  align-items: center;
  gap: var(--mf-space-5);
  min-width: 0;
}

.brand {
  flex: none;
  border: 0;
  background: transparent;
  padding: 0;
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
  color: var(--mf-ink);
  cursor: pointer;
  transition: color var(--mf-duration-fast) var(--mf-ease);
}
.brand:hover { color: var(--mf-accent); }

/* ---- 阶段进度 ---- */

.steps {
  display: flex;
  align-items: center;
  gap: var(--mf-space-1);
  list-style: none;
  margin: 0;
  padding: 0;
  min-width: 0;
  overflow: hidden;
}

.steps__item {
  display: flex;
  align-items: center;
  gap: var(--mf-space-2);
  padding: var(--mf-space-1) var(--mf-space-3);
  border-radius: var(--mf-radius-full);
  font-size: var(--mf-text-xs);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-faint);
  white-space: nowrap;
  transition:
    background-color var(--mf-duration) var(--mf-ease),
    color var(--mf-duration) var(--mf-ease);
}

.steps__dot {
  width: 5px;
  height: 5px;
  border-radius: var(--mf-radius-full);
  background: currentColor;
  flex: none;
  opacity: 0.45;
}

.steps__item.is-done { color: var(--mf-ink-muted); }
.steps__item.is-done .steps__dot { opacity: 1; }

.steps__item.is-current {
  background: var(--mf-accent-soft);
  color: var(--mf-accent);
  font-weight: var(--mf-weight-semibold);
}
.steps__item.is-current .steps__dot { opacity: 1; }

/* ---- 视图切换 ---- */

.segmented {
  display: flex;
  gap: 2px;
  padding: 2px;
  background: var(--mf-surface-sunken);
  border-radius: var(--mf-radius-md);
}

.segmented__btn {
  border: 0;
  background: transparent;
  padding: var(--mf-space-1) var(--mf-space-4);
  border-radius: var(--mf-radius-sm);
  font-size: var(--mf-text-xs);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-muted);
  cursor: pointer;
  transition:
    background-color var(--mf-duration-fast) var(--mf-ease),
    color var(--mf-duration-fast) var(--mf-ease),
    box-shadow var(--mf-duration-fast) var(--mf-ease);
}

.segmented__btn:hover { color: var(--mf-ink); }

.segmented__btn.is-active {
  background: var(--mf-surface);
  color: var(--mf-ink);
  box-shadow: var(--mf-shadow-xs);
}

/* ---- 运行状态 ---- */

.status {
  display: inline-flex;
  align-items: center;
  gap: var(--mf-space-2);
  font-size: var(--mf-text-xs);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-muted);
  white-space: nowrap;
}

.status.processing { color: var(--mf-accent); }
.status.completed  { color: var(--mf-success); }
.status.error      { color: var(--mf-danger); }

@media (max-width: 1100px) {
  .steps__label { display: none; }
  .steps__item { padding: var(--mf-space-1) var(--mf-space-2); }
  .steps__item.is-current .steps__label { display: inline; }
}

@media (max-width: 720px) {
  .topbar { padding: 0 var(--mf-space-4); gap: var(--mf-space-3); }
  .status { display: none; }
}
</style>
