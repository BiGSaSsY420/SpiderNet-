<template>
  <div class="home">
    <!-- 顶部导航 -->
    <nav class="nav">
      <div class="mf-container nav__inner">
        <a class="nav__brand" href="/" @click.prevent="$router.push('/')">MiroFish</a>
        <a
          class="nav__link"
          href="https://github.com/666ghj/MiroFish"
          target="_blank"
          rel="noopener noreferrer"
        >
          GitHub
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
            <path d="M3 9L9 3M9 3H4.5M9 3v4.5" stroke="currentColor" stroke-width="1.4"
                  fill="none" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </a>
      </div>
    </nav>

    <!-- Hero -->
    <header class="hero">
      <div class="mf-container hero__inner">
        <div class="hero__copy">
          <p class="mf-eyebrow hero__eyebrow">群体智能引擎 · v0.1 预览版</p>

          <h1 class="hero__title">
            上传任意报告，<br />
            即刻推演未来
          </h1>

          <p class="hero__lede">
            即使只有一段文字，MiroFish 也能从中提取现实种子，生成至多百万级 Agent
            构成的平行世界。从上帝视角注入变量，在群体交互中找到动态环境下的局部最优解。
          </p>

          <div class="hero__actions">
            <button class="mf-btn mf-btn--primary mf-btn--lg" @click="scrollToConsole">
              开始一次推演
            </button>
            <span class="hero__cost mf-mono">常规模拟约 $5 / 次</span>
          </div>
        </div>

        <div class="hero__visual" aria-hidden="true">
          <img
            src="../assets/logo/MiroFish_logo_left.jpeg"
            alt=""
            class="hero__logo"
            loading="lazy"
            decoding="async"
          />
        </div>
      </div>
    </header>

    <!-- 主控制台 + 工作流 -->
    <main class="mf-container main">
      <section id="console" ref="consoleEl" class="console" aria-labelledby="console-title">
        <div class="console__head">
          <h2 id="console-title" class="console__title">新建推演</h2>
          <p class="console__sub">上传现实种子，用一句话描述你要预测什么。</p>
        </div>

        <div class="mf-card console__card">
          <!-- 1. 上传 -->
          <div class="field console__pane">
            <div class="field__head">
              <label class="field__label" for="file-trigger">现实种子</label>
              <span class="field__hint mf-mono">PDF · MD · TXT</span>
            </div>

            <button
              id="file-trigger"
              type="button"
              class="dropzone"
              :class="{ 'is-dragging': isDragOver, 'has-files': files.length > 0 }"
              :disabled="loading"
              @dragover.prevent="handleDragOver"
              @dragleave.prevent="handleDragLeave"
              @drop.prevent="handleDrop"
              @click="triggerFileInput"
            >
              <input
                ref="fileInput"
                type="file"
                multiple
                accept=".pdf,.md,.txt"
                class="mf-sr-only"
                tabindex="-1"
                :disabled="loading"
                @change="handleFileSelect"
              />

              <template v-if="files.length === 0">
                <svg class="dropzone__icon" width="24" height="24" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"
                        stroke="currentColor" stroke-width="1.6" fill="none"
                        stroke-linecap="round" stroke-linejoin="round" />
                </svg>
                <span class="dropzone__title">拖拽文件到此处</span>
                <span class="dropzone__hint">或点击选择</span>
              </template>

              <span v-else class="dropzone__summary">
                已选 {{ files.length }} 个文件 · {{ totalSize }}，点击继续添加
              </span>
            </button>

            <ul v-if="files.length" class="filelist">
              <li v-for="(file, index) in files" :key="`${file.name}-${index}`" class="filelist__item">
                <span class="filelist__ext mf-mono">{{ extensionOf(file.name) }}</span>
                <span class="filelist__name">{{ file.name }}</span>
                <span class="filelist__size mf-mono">{{ formatSize(file.size) }}</span>
                <button
                  type="button"
                  class="filelist__remove"
                  :aria-label="`移除 ${file.name}`"
                  :disabled="loading"
                  @click.stop="removeFile(index)"
                >
                  <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
                    <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.5"
                          stroke-linecap="round" />
                  </svg>
                </button>
              </li>
            </ul>

            <p v-if="error" class="field__error" role="alert">{{ error }}</p>
          </div>

          <!-- 2. 提示词 + 启动 -->
          <div class="console__pane console__pane--right">
            <div class="field">
              <div class="field__head">
                <label class="field__label" for="requirement">预测需求</label>
                <span class="field__hint mf-mono">{{ requirementLength }} 字</span>
              </div>
              <textarea
                id="requirement"
                v-model="formData.simulationRequirement"
                class="mf-textarea console__textarea"
                :disabled="loading"
                placeholder="例：若发布撤销处分的公告，会引发什么舆情走向？"
              ></textarea>
            </div>

            <div class="console__submit">
              <button
                class="mf-btn mf-btn--primary mf-btn--lg mf-btn--block"
                :disabled="!canSubmit || loading"
                @click="startSimulation"
              >
                {{ loading ? '初始化中…' : '启动引擎' }}
              </button>
              <p v-if="!canSubmit && !loading" class="console__requirement">
                {{ missingRequirement }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- 工作流：这里的编号是真实的执行顺序，不是装饰 -->
      <section class="workflow" aria-labelledby="workflow-title">
        <div class="workflow__head">
          <h2 id="workflow-title" class="workflow__title">推演流程</h2>
          <p class="workflow__sub">启动后，引擎依次走完五个阶段。</p>
        </div>

        <ol class="workflow__list">
          <li v-for="step in workflowSteps" :key="step.n" class="step">
            <span class="step__n mf-mono">{{ step.n }}</span>
            <div class="step__body">
              <h3 class="step__title">{{ step.title }}</h3>
              <p class="step__desc">{{ step.desc }}</p>
            </div>
          </li>
        </ol>
      </section>

      <HistoryDatabase />
    </main>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'

const router = useRouter()

const ACCEPTED = ['pdf', 'md', 'txt']

const workflowSteps = [
  { n: '01', title: '图谱构建', desc: '提取现实种子，注入个体与群体记忆，构建 GraphRAG。' },
  { n: '02', title: '环境搭建', desc: '抽取实体关系，生成人设，由配置 Agent 注入仿真参数。' },
  { n: '03', title: '开始模拟', desc: '双平台并行推演，自动解析预测需求，动态更新时序记忆。' },
  { n: '04', title: '报告生成', desc: 'ReportAgent 借助工具集与模拟后的环境深度交互。' },
  { n: '05', title: '深度互动', desc: '与模拟世界中的任意个体对话，也可继续追问 ReportAgent。' }
]

// 表单数据
const formData = ref({
  simulationRequirement: ''
})

const files = ref([])

const loading = ref(false)
const error = ref('')
const isDragOver = ref(false)

const fileInput = ref(null)
const consoleEl = ref(null)

const canSubmit = computed(() =>
  formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
)

const requirementLength = computed(() => formData.value.simulationRequirement.length)

const totalSize = computed(() =>
  formatSize(files.value.reduce((sum, f) => sum + (f.size || 0), 0))
)

const missingRequirement = computed(() => {
  if (files.value.length === 0 && !formData.value.simulationRequirement.trim()) {
    return '需要至少一个文件，以及一句预测需求。'
  }
  if (files.value.length === 0) return '还需要上传至少一个文件。'
  return '还需要填写预测需求。'
})

function extensionOf (name) {
  const parts = String(name).split('.')
  return parts.length > 1 ? parts.pop().toUpperCase() : 'FILE'
}

function formatSize (bytes) {
  if (!bytes) return '0 KB'
  const units = ['B', 'KB', 'MB', 'GB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`
}

const triggerFileInput = () => {
  if (!loading.value) {
    fileInput.value?.click()
  }
}

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files))
  // 允许重新选择同一个文件
  event.target.value = ''
}

const handleDragOver = () => {
  if (!loading.value) {
    isDragOver.value = true
  }
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return
  addFiles(Array.from(e.dataTransfer.files))
}

// 之前不合规的文件会被静默丢弃，用户得不到任何反馈
const addFiles = (newFiles) => {
  const accepted = []
  const rejected = []

  newFiles.forEach((file) => {
    const ext = file.name.split('.').pop().toLowerCase()
    if (ACCEPTED.includes(ext)) {
      accepted.push(file)
    } else {
      rejected.push(file.name)
    }
  })

  files.value.push(...accepted)

  error.value = rejected.length
    ? `已跳过 ${rejected.length} 个不支持的文件：${rejected.join('、')}。仅支持 PDF、MD、TXT。`
    : ''
}

const removeFile = (index) => {
  files.value.splice(index, 1)
  if (files.value.length === 0) error.value = ''
}

const scrollToConsole = () => {
  consoleEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// 立即跳转，API 调用在 Process 页面进行
const startSimulation = () => {
  if (!canSubmit.value || loading.value) return

  import('../store/pendingUpload.js').then(({ setPendingUpload }) => {
    setPendingUpload(files.value, formData.value.simulationRequirement)
    router.push({ name: 'Process', params: { projectId: 'new' } })
  })
}
</script>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--mf-ground);
}

/* ---- 导航 ---- */

.nav {
  position: sticky;
  top: 0;
  z-index: 20;
  height: var(--mf-header-height);
  background: color-mix(in srgb, var(--mf-ground) 82%, transparent);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--mf-separator);
}

.nav__inner {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav__brand {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
  color: var(--mf-ink);
}

.nav__link {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: var(--mf-text-sm);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-secondary);
}
.nav__link:hover { color: var(--mf-ink); }

/* ---- Hero ---- */

.hero {
  padding: var(--mf-space-9) 0 var(--mf-space-8);
}

.hero__inner {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(240px, 340px);
  gap: var(--mf-space-7);
  align-items: center;
}

.hero__eyebrow {
  margin-bottom: var(--mf-space-4);
}

.hero__title {
  font-size: clamp(var(--mf-text-2xl), 5.5vw, var(--mf-text-4xl));
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: var(--mf-leading-tight);
  color: var(--mf-ink);
}

.hero__lede {
  margin-top: var(--mf-space-5);
  max-width: 46ch;
  font-size: var(--mf-text-md);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-secondary);
}

.hero__actions {
  margin-top: var(--mf-space-6);
  display: flex;
  align-items: center;
  gap: var(--mf-space-4);
  flex-wrap: wrap;
}

.hero__cost {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.hero__visual {
  display: flex;
  justify-content: center;
}

.hero__logo {
  width: 100%;
  max-width: 340px;
  border-radius: var(--mf-radius-xl);
  box-shadow: var(--mf-shadow-lg);
}

/* ---- 主区 ---- */

.main {
  padding-bottom: var(--mf-space-9);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-9);
}

/* ---- 控制台 ---- */

.console {
  scroll-margin-top: calc(var(--mf-header-height) + var(--mf-space-5));
}

.console__head {
  margin-bottom: var(--mf-space-5);
}

.console__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.console__sub {
  margin-top: var(--mf-space-2);
  color: var(--mf-ink-muted);
  font-size: var(--mf-text-base);
}

/* 宽屏下两栏：左边放种子，右边放需求与启动，把整幅宽度用起来 */
.console__card {
  padding: var(--mf-space-6);
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--mf-space-6);
  align-items: start;
}

.console__pane {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-3);
  min-width: 0;
}

.console__pane--right {
  gap: var(--mf-space-5);
  align-self: stretch;
}

/* 让右栏的输入框与左栏的拖拽区高度呼应 */
.console__textarea {
  flex: 1;
  min-height: 148px;
}

.console__submit {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-3);
  align-items: center;
}

.console__requirement {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

/* ---- 表单块 ---- */

.field {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-3);
}

.field__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--mf-space-3);
}

.field__label {
  font-size: var(--mf-text-sm);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.field__hint {
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}

.field__error {
  font-size: var(--mf-text-sm);
  color: var(--mf-danger);
  line-height: var(--mf-leading-normal);
}

/* ---- 拖拽区 ---- */

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--mf-space-2);
  width: 100%;
  min-height: 148px;
  padding: var(--mf-space-6);
  background: var(--mf-surface-sunken);
  border: 1px dashed var(--mf-separator-strong);
  border-radius: var(--mf-radius-md);
  color: var(--mf-ink-muted);
  cursor: pointer;
  transition:
    background-color var(--mf-duration) var(--mf-ease),
    border-color var(--mf-duration) var(--mf-ease),
    color var(--mf-duration) var(--mf-ease);
}

.dropzone:hover:not(:disabled),
.dropzone.is-dragging {
  background: var(--mf-accent-soft);
  border-color: var(--mf-accent);
  color: var(--mf-accent);
}

.dropzone.has-files {
  min-height: 0;
  padding: var(--mf-space-4);
  border-style: solid;
}

.dropzone:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.dropzone__icon { color: currentColor; }

.dropzone__title {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink);
}

.dropzone.is-dragging .dropzone__title,
.dropzone:hover:not(:disabled) .dropzone__title { color: inherit; }

.dropzone__hint,
.dropzone__summary {
  font-size: var(--mf-text-sm);
}

/* ---- 文件列表 ---- */

.filelist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--mf-separator);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-md);
  overflow: hidden;
}

.filelist__item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto;
  align-items: center;
  gap: var(--mf-space-3);
  padding: var(--mf-space-3) var(--mf-space-4);
  background: var(--mf-surface);
}

.filelist__ext {
  font-size: var(--mf-text-2xs);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink-muted);
  background: var(--mf-surface-sunken);
  padding: 2px 6px;
  border-radius: var(--mf-radius-xs);
}

.filelist__name {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filelist__size {
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}

.filelist__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 0;
  border-radius: var(--mf-radius-sm);
  background: transparent;
  color: var(--mf-ink-faint);
  cursor: pointer;
  transition:
    background-color var(--mf-duration-fast) var(--mf-ease),
    color var(--mf-duration-fast) var(--mf-ease);
}

.filelist__remove:hover:not(:disabled) {
  background: var(--mf-danger-soft);
  color: var(--mf-danger);
}

/* ---- 工作流 ---- */

.workflow__head {
  margin-bottom: var(--mf-space-5);
}

.workflow__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.workflow__sub {
  margin-top: var(--mf-space-2);
  color: var(--mf-ink-muted);
  font-size: var(--mf-text-base);
}

.workflow__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 1px;
  background: var(--mf-separator);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
  overflow: hidden;
}

.step {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-3);
  padding: var(--mf-space-5);
  background: var(--mf-surface);
}

.step__n {
  font-size: var(--mf-text-xs);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-accent);
  letter-spacing: var(--mf-tracking-wide);
}

.step__title {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.step__desc {
  margin-top: var(--mf-space-2);
  font-size: var(--mf-text-sm);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-muted);
}

/* ---- 响应式 ---- */

@media (max-width: 900px) {
  .hero { padding: var(--mf-space-7) 0 var(--mf-space-6); }
  .hero__inner {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--mf-space-6);
  }
  .hero__visual { order: -1; justify-content: flex-start; }
  .hero__logo { max-width: 200px; }
  .main { gap: var(--mf-space-7); }
}

@media (max-width: 860px) {
  .console__card {
    grid-template-columns: minmax(0, 1fr);
    gap: var(--mf-space-5);
  }
}

@media (max-width: 560px) {
  .console__card { padding: var(--mf-space-4); }
  .filelist__item { grid-template-columns: auto minmax(0, 1fr) auto; }
  .filelist__size { display: none; }
}
</style>
