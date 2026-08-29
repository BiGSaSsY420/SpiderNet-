<template>
  <div class="home">
    <!-- Top bar -->
    <nav class="nav">
      <div class="mf-container nav__inner">
        <a class="nav__brand" href="/" @click.prevent="$router.push('/')">SpiderNet</a>

        <div class="nav__right">
          <span
            v-if="credits !== null"
            class="nav__credits mf-mono"
            :title="account ? `Plan: ${account.plan}` : ''"
          >
            {{ credits.toLocaleString() }} credits
          </span>
          <button
            v-if="hasKey"
            class="mf-btn mf-btn--ghost mf-btn--sm"
            @click="$router.push('/crowds')"
          >
            Ask a crowd
          </button>
          <button v-if="hasKey" class="mf-btn mf-btn--ghost mf-btn--sm" @click="signOut">
            Sign out
          </button>
        </div>
      </div>
    </nav>

    <main class="mf-container main">
      <!-- What this is, in one breath -->
      <header class="hero">
        <h1 class="hero__title">See what happens next.</h1>
        <p class="hero__lede">
          Give SpiderNet something to read and a question about the future. It builds
          a crowd of thousands of people, lets them react, and tells you how it went.
        </p>
      </header>

      <!-- Sign in, if we don't have a key yet -->
      <section v-if="!hasKey" class="mf-card gate" aria-labelledby="gate-title">
        <h2 id="gate-title" class="gate__title">Enter your access key</h2>
        <p class="gate__body">
          Your key came in your welcome email. It starts with <code>sn_live_</code>.
        </p>

        <form class="gate__form" @submit.prevent="signIn">
          <input
            v-model="keyInput"
            class="mf-input gate__input mf-mono"
            type="password"
            autocomplete="off"
            spellcheck="false"
            placeholder="sn_live_…"
            aria-label="Access key"
            :disabled="checkingKey"
          />
          <button
            class="mf-btn mf-btn--primary mf-btn--lg"
            type="submit"
            :disabled="!keyInput.trim() || checkingKey"
          >
            {{ checkingKey ? 'Checking…' : 'Continue' }}
          </button>
        </form>

        <p v-if="keyError" class="gate__error" role="alert">{{ keyError }}</p>
        <p class="gate__help">
          Don't have one yet? <a href="mailto:hello@spidernet.app">Ask for access.</a>
        </p>
      </section>

      <!-- The whole product, in two questions -->
      <section v-else class="ask" aria-labelledby="ask-title">
        <h2 id="ask-title" class="mf-sr-only">Start a new run</h2>

        <!-- 1 -->
        <div class="question">
          <div class="question__head">
            <span class="question__n" aria-hidden="true">1</span>
            <h3 class="question__title">What should it read?</h3>
          </div>

          <button
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
              <svg class="dropzone__icon" width="32" height="32" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 16v2.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V16"
                      stroke="currentColor" stroke-width="1.6" fill="none"
                      stroke-linecap="round" stroke-linejoin="round" />
              </svg>
              <span class="dropzone__title">Choose a file</span>
              <span class="dropzone__hint">or drag one here — PDF, text, or Markdown</span>
            </template>

            <span v-else class="dropzone__summary">Add another file</span>
          </button>

          <ul v-if="files.length" class="filelist">
            <li v-for="(file, index) in files" :key="`${file.name}-${index}`" class="filelist__item">
              <span class="filelist__ext mf-mono">{{ extensionOf(file.name) }}</span>
              <span class="filelist__name">{{ file.name }}</span>
              <span class="filelist__size mf-mono">{{ formatSize(file.size) }}</span>
              <button
                type="button"
                class="filelist__remove"
                :aria-label="`Remove ${file.name}`"
                :disabled="loading"
                @click.stop="removeFile(index)"
              >
                <svg width="14" height="14" viewBox="0 0 12 12" aria-hidden="true">
                  <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" stroke-width="1.6"
                        stroke-linecap="round" />
                </svg>
              </button>
            </li>
          </ul>

          <p v-if="error" class="question__error" role="alert">{{ error }}</p>
        </div>

        <!-- 2 -->
        <div class="question">
          <div class="question__head">
            <span class="question__n" aria-hidden="true">2</span>
            <h3 class="question__title">What do you want to know?</h3>
          </div>

          <textarea
            id="requirement"
            v-model="formData.simulationRequirement"
            class="mf-textarea ask__textarea"
            rows="4"
            :disabled="loading"
            placeholder="What happens if we raise the price by 20%?"
            aria-label="What do you want to know?"
          ></textarea>

          <div class="examples">
            <span class="examples__label">Not sure? Try one:</span>
            <button
              v-for="example in EXAMPLES"
              :key="example"
              type="button"
              class="examples__chip"
              :disabled="loading"
              @click="formData.simulationRequirement = example"
            >
              {{ example }}
            </button>
          </div>
        </div>

        <!-- Go -->
        <div class="go">
          <button
            class="mf-btn mf-btn--primary mf-btn--lg go__btn"
            :disabled="!canSubmit || loading"
            @click="startSimulation"
          >
            {{ loading ? 'Starting…' : 'Start' }}
          </button>

          <p class="go__note">
            <template v-if="!canSubmit && !loading">{{ missingRequirement }}</template>
            <template v-else-if="runCost">
              Uses about {{ runCost }} credits. Takes 20 to 40 minutes.
            </template>
          </p>
        </div>
      </section>

      <!-- How it works -->
      <section class="how" aria-labelledby="how-title">
        <h2 id="how-title" class="how__title">How it works</h2>
        <ol class="how__list">
          <li v-for="step in HOW_IT_WORKS" :key="step.n" class="step">
            <span class="step__n mf-mono" aria-hidden="true">{{ step.n }}</span>
            <div>
              <h3 class="step__title">{{ step.title }}</h3>
              <p class="step__desc">{{ step.desc }}</p>
            </div>
          </li>
        </ol>
      </section>

      <HistoryDatabase v-if="hasKey" />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import {
  account, credits, hasKey, setAccessKey, clearAccessKey, looksLikeKey
} from '../store/accessKey'
import { refreshAccount, getPricing } from '../api/account'

const router = useRouter()

const ACCEPTED = ['pdf', 'md', 'txt']

const EXAMPLES = [
  'How would people react to this announcement?',
  'What happens if we raise the price?',
  'Which part of this will people argue about?'
]

// Plain language on purpose. Nobody outside this codebase knows what an
// ontology or a GraphRAG is, and nobody needs to.
const HOW_IT_WORKS = [
  { n: '1', title: 'It reads',
    desc: 'SpiderNet goes through everything you gave it and works out who matters and how they are connected.' },
  { n: '2', title: 'It builds a crowd',
    desc: 'Thousands of people are created, each with their own history, opinions and reasons to care.' },
  { n: '3', title: 'They react',
    desc: 'The crowd posts, argues, agrees and changes its mind, the way a real one would.' },
  { n: '4', title: 'You get the story',
    desc: 'A plain write-up of what happened and why, with the moments that mattered.' },
  { n: '5', title: 'You can ask',
    desc: 'Talk to anyone in the crowd, or ask follow-up questions about the result.' }
]

const formData = ref({ simulationRequirement: '' })
const files = ref([])

const loading = ref(false)
const error = ref('')
const isDragOver = ref(false)
const fileInput = ref(null)

const keyInput = ref('')
const keyError = ref('')
const checkingKey = ref(false)

const runCost = ref(null)

const canSubmit = computed(() =>
  formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
)

const missingRequirement = computed(() => {
  if (files.value.length === 0 && !formData.value.simulationRequirement.trim()) {
    return 'Add a file and a question to begin.'
  }
  if (files.value.length === 0) return 'Add at least one file.'
  return 'Tell it what you want to know.'
})

onMounted(async () => {
  if (hasKey.value) refreshAccount()
  try {
    const res = await getPricing()
    runCost.value = res.data.estimated_run_total
  } catch {
    runCost.value = null
  }
})

// --- access key ---------------------------------------------------------

async function signIn () {
  keyError.value = ''
  const candidate = keyInput.value.trim()

  if (!looksLikeKey(candidate)) {
    keyError.value =
      "That doesn't look like a key. It should start with sn_live_ and be one long line."
    return
  }

  checkingKey.value = true
  setAccessKey(candidate)

  const result = await refreshAccount()
  checkingKey.value = false

  if (!result) {
    clearAccessKey()
    keyError.value = 'That key was not accepted. Check for a missing character and try again.'
    return
  }
  keyInput.value = ''
}

function signOut () {
  clearAccessKey()
  files.value = []
  formData.value.simulationRequirement = ''
}

// --- files --------------------------------------------------------------

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
  if (!loading.value) fileInput.value?.click()
}

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files))
  event.target.value = ''
}

const handleDragOver = () => {
  if (!loading.value) isDragOver.value = true
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (e) => {
  isDragOver.value = false
  if (loading.value) return
  addFiles(Array.from(e.dataTransfer.files))
}

// Unsupported files used to be dropped without a word.
const addFiles = (newFiles) => {
  const accepted = []
  const rejected = []

  newFiles.forEach((file) => {
    const ext = file.name.split('.').pop().toLowerCase()
    if (ACCEPTED.includes(ext)) accepted.push(file)
    else rejected.push(file.name)
  })

  files.value.push(...accepted)

  error.value = rejected.length
    ? `Couldn't use ${rejected.join(', ')}. SpiderNet reads PDF, text and Markdown files.`
    : ''
}

const removeFile = (index) => {
  files.value.splice(index, 1)
  if (files.value.length === 0) error.value = ''
}

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

/* ---- Top bar ---- */

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

.nav__right {
  display: flex;
  align-items: center;
  gap: var(--mf-space-4);
}

.nav__credits {
  font-size: var(--mf-text-sm);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-secondary);
}

/* ---- Layout: one narrow column, so there is never a question about
       where to look next ---- */

.main {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-9);
  padding-top: var(--mf-space-8);
  padding-bottom: var(--mf-space-9);
  max-width: 760px;
}

/* ---- Hero ---- */

.hero__title {
  font-size: clamp(var(--mf-text-2xl), 6vw, var(--mf-text-3xl));
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: var(--mf-leading-tight);
}

.hero__lede {
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-md);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-secondary);
  max-width: 52ch;
}

/* ---- Key gate ---- */

.gate { padding: var(--mf-space-6); }

.gate__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.gate__body {
  margin-top: var(--mf-space-2);
  color: var(--mf-ink-secondary);
}

.gate__form {
  margin-top: var(--mf-space-5);
  display: flex;
  gap: var(--mf-space-3);
  flex-wrap: wrap;
}

.gate__input {
  flex: 1 1 260px;
  height: 48px;
}

.gate__error {
  margin-top: var(--mf-space-3);
  color: var(--mf-danger);
  font-size: var(--mf-text-sm);
}

.gate__help {
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

/* ---- The two questions ---- */

.ask {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-8);
}

.question {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-4);
}

.question__head {
  display: flex;
  align-items: center;
  gap: var(--mf-space-3);
}

/* The numbered circle is the whole navigation model: two steps, then Start */
.question__n {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--mf-radius-full);
  background: var(--mf-accent);
  color: var(--mf-on-accent);
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-bold);
  font-variant-numeric: tabular-nums;
}

.question__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.question__error {
  font-size: var(--mf-text-base);
  color: var(--mf-danger);
  line-height: var(--mf-leading-normal);
}

.ask__textarea {
  font-size: var(--mf-text-md);
  min-height: 116px;
  padding: var(--mf-space-4);
}

/* ---- Drop zone: one big target ---- */

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--mf-space-2);
  width: 100%;
  min-height: 168px;
  padding: var(--mf-space-6);
  background: var(--mf-surface-sunken);
  border: 2px dashed var(--mf-separator-strong);
  border-radius: var(--mf-radius-lg);
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

.dropzone:disabled { opacity: 0.5; cursor: not-allowed; }

.dropzone__title {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.dropzone.is-dragging .dropzone__title,
.dropzone:hover:not(:disabled) .dropzone__title { color: inherit; }

.dropzone__hint,
.dropzone__summary { font-size: var(--mf-text-base); }

/* ---- File list ---- */

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
  font-size: var(--mf-text-base);
  color: var(--mf-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.filelist__size {
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}

/* 32px hit target: a small x is the first thing to fail for anyone
   without steady hands */
.filelist__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: 0;
  border-radius: var(--mf-radius-sm);
  background: transparent;
  color: var(--mf-ink-muted);
  cursor: pointer;
  transition:
    background-color var(--mf-duration-fast) var(--mf-ease),
    color var(--mf-duration-fast) var(--mf-ease);
}

.filelist__remove:hover:not(:disabled) {
  background: var(--mf-danger-soft);
  color: var(--mf-danger);
}

/* ---- Examples ---- */

.examples {
  display: flex;
  align-items: center;
  gap: var(--mf-space-2);
  flex-wrap: wrap;
}

.examples__label {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.examples__chip {
  border: 1px solid var(--mf-separator-strong);
  background: var(--mf-surface);
  border-radius: var(--mf-radius-full);
  padding: 6px var(--mf-space-4);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-secondary);
  cursor: pointer;
  transition:
    background-color var(--mf-duration-fast) var(--mf-ease),
    border-color var(--mf-duration-fast) var(--mf-ease),
    color var(--mf-duration-fast) var(--mf-ease);
}

.examples__chip:hover:not(:disabled) {
  background: var(--mf-accent-soft);
  border-color: var(--mf-accent);
  color: var(--mf-accent);
}

/* ---- Go ---- */

.go {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--mf-space-3);
}

.go__btn {
  width: 100%;
  max-width: 320px;
  height: 56px;
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.go__note {
  font-size: var(--mf-text-base);
  color: var(--mf-ink-muted);
  text-align: center;
  min-height: 1.5em;
}

/* ---- How it works ---- */

.how__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
  margin-bottom: var(--mf-space-5);
}

.how__list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-5);
}

.step {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  gap: var(--mf-space-4);
  align-items: start;
}

.step__n {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-accent);
  line-height: 1.5;
}

.step__title {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.step__desc {
  margin-top: var(--mf-space-1);
  font-size: var(--mf-text-base);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-secondary);
}

@media (max-width: 560px) {
  .main { gap: var(--mf-space-8); padding-top: var(--mf-space-6); }
  .gate { padding: var(--mf-space-4); }
  .go__btn { max-width: none; }
  .filelist__item { grid-template-columns: auto minmax(0, 1fr) auto; }
  .filelist__size { display: none; }
}
</style>
