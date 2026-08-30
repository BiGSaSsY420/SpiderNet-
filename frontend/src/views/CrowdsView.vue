<template>
  <div class="crowds">
    <nav class="nav">
      <div class="mf-container nav__inner">
        <a class="nav__brand" href="/" @click.prevent="$router.push('/')">SpiderNet</a>
        <div class="nav__right">
          <button
            v-if="credits !== null"
            class="nav__credits mf-mono"
            @click="$router.push('/billing')"
          >
            {{ credits.toLocaleString() }} credits
          </button>
        </div>
      </div>
    </nav>

    <main class="mf-container main">
      <header class="head">
        <h1 class="head__title">Ask a crowd</h1>
        <p class="head__lede">
          These are groups of people SpiderNet has already built. Asking one takes
          seconds, not the half hour it takes to build a new one.
        </p>
      </header>

      <p v-if="loadError" class="notice notice--error" role="alert">{{ loadError }}</p>

      <div v-if="loading" class="notice">Loading your crowds…</div>

      <div v-else-if="crowds.length === 0 && !showCapture" class="mf-card empty">
        <h2 class="empty__title">No crowds yet</h2>
        <p class="empty__body">
          Save the people from a finished run, and you can keep asking them things
          without building anything again.
        </p>
        <div class="empty__actions">
          <button
            v-if="runs.length"
            class="mf-btn mf-btn--primary"
            @click="showCapture = true"
          >
            Save people from a run
          </button>
          <button class="mf-btn mf-btn--secondary" @click="$router.push('/')">
            Start a run
          </button>
        </div>
      </div>

      <!-- Save people from a finished run -->
      <section v-if="showCapture" class="mf-card capture">
        <h2 class="capture__title">Save people from a run</h2>
        <p class="capture__body">
          Give them a name you'll recognise later, like "Ohio parents" or
          "Our customers, Q3".
        </p>

        <div class="capture__row">
          <select v-model="captureRunId" class="capture__select" aria-label="Which run">
            <option value="" disabled>Choose a run…</option>
            <option v-for="run in runs" :key="run.simulation_id" :value="run.simulation_id">
              {{ runLabel(run) }}
            </option>
          </select>
          <input
            v-model="captureName"
            class="mf-input"
            placeholder="Name this crowd"
            aria-label="Name this crowd"
          />
          <button
            class="mf-btn mf-btn--primary"
            :disabled="!captureRunId || !captureName.trim() || capturing"
            @click="capture"
          >
            {{ capturing ? 'Saving…' : 'Save' }}
          </button>
          <button class="mf-btn mf-btn--ghost" @click="showCapture = false">Cancel</button>
        </div>

        <p v-if="captureError" class="capture__error" role="alert">{{ captureError }}</p>
        <p class="capture__note">Free — you already paid to create these people.</p>
      </section>

      <template v-if="crowds.length">
        <!-- 1. Who -->
        <section class="step">
          <div class="step__toolbar">
            <button
              v-if="runs.length && !showCapture"
              class="mf-btn mf-btn--secondary mf-btn--sm"
              @click="showCapture = true"
            >
              Save people from another run
            </button>
          </div>
          <div class="step__head">
            <span class="step__n" aria-hidden="true">1</span>
            <h2 class="step__title">Who do you want to ask?</h2>
          </div>

          <ul class="crowdlist">
            <li v-for="crowd in crowds" :key="crowd.crowd_id">
              <button
                type="button"
                class="crowdcard"
                :class="{ 'is-selected': selectedId === crowd.crowd_id }"
                :aria-pressed="selectedId === crowd.crowd_id"
                @click="selectedId = crowd.crowd_id"
              >
                <span class="crowdcard__name">{{ crowd.name }}</span>
                <span class="crowdcard__meta">
                  {{ crowd.size.toLocaleString() }} people
                  <template v-if="crowd.visibility === 'library'"> · shared</template>
                </span>
                <span v-if="crowd.description" class="crowdcard__desc">
                  {{ crowd.description }}
                </span>
              </button>
            </li>
          </ul>
        </section>

        <!-- 2. What -->
        <section class="step">
          <div class="step__head">
            <span class="step__n" aria-hidden="true">2</span>
            <h2 class="step__title">What do you want to ask them?</h2>
          </div>

          <textarea
            v-model="question"
            class="mf-textarea ask__textarea"
            rows="3"
            :disabled="asking"
            placeholder="How would you feel if we announced this tomorrow?"
            aria-label="What do you want to ask them?"
          ></textarea>

          <div class="sample">
            <label class="sample__label" for="sample-size">Ask</label>
            <select
              id="sample-size"
              v-model.number="sampleSize"
              class="sample__select"
              :disabled="asking"
            >
              <option :value="10">10 people</option>
              <option :value="25">25 people</option>
              <option :value="50">50 people</option>
              <option :value="100">100 people</option>
            </select>
          </div>
        </section>

        <div class="go">
          <button
            class="mf-btn mf-btn--primary mf-btn--lg go__btn"
            :disabled="!canAsk || asking"
            @click="ask"
          >
            {{ asking ? 'Asking…' : 'Ask them' }}
          </button>
          <p class="go__note">
            <template v-if="askError">
              <span class="go__error">{{ askError }}</span>
            </template>
            <template v-else-if="!canAsk">Pick a crowd and type a question.</template>
            <template v-else>Costs 3 credits. Takes a few seconds.</template>
          </p>
        </div>

        <!-- Answers -->
        <section v-if="result" class="answers" aria-live="polite">
          <div class="answers__head">
            <h2 class="answers__title">What they said</h2>
            <p class="answers__meta">
              {{ result.answered }} of {{ result.asked }} answered
              <template v-if="result.failed">
                · {{ result.failed }} couldn't be reached
              </template>
            </p>
          </div>

          <ul class="answerlist">
            <li v-for="(r, i) in result.responses" :key="i" class="answer">
              <div class="answer__who">
                <span class="answer__name">{{ r.name }}</span>
                <span v-if="r.age || r.profession" class="answer__detail">
                  {{ [r.age, r.profession].filter(Boolean).join(' · ') }}
                </span>
              </div>
              <p class="answer__text">{{ r.answer }}</p>
            </li>
          </ul>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { credits, hasKey } from '../store/accessKey'
import { refreshAccount } from '../api/account'
import { listCrowds, askCrowd, captureCrowd, listSimulations } from '../api/crowd'

const crowds = ref([])
const loading = ref(true)
const loadError = ref('')

const selectedId = ref(null)
const question = ref('')
const sampleSize = ref(25)

const runs = ref([])
const showCapture = ref(false)
const captureRunId = ref('')
const captureName = ref('')
const capturing = ref(false)
const captureError = ref('')

const asking = ref(false)
const askError = ref('')
const result = ref(null)

const canAsk = computed(() => Boolean(selectedId.value) && question.value.trim() !== '')

function runLabel (run) {
  const when = new Date(run.created_at)
  const date = Number.isNaN(when.getTime())
    ? ''
    : when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  const people = run.profiles_count
    ? `${run.profiles_count.toLocaleString()} people`
    : 'no people yet'
  return `${date} — ${people}`
}

async function loadCrowds () {
  const res = await listCrowds()
  crowds.value = res.data || []
  if (!selectedId.value && crowds.value.length === 1) {
    selectedId.value = crowds.value[0].crowd_id
  }
}

onMounted(async () => {
  if (hasKey.value) refreshAccount()
  try {
    await loadCrowds()
  } catch (e) {
    loadError.value = e.message || 'Could not load your crowds.'
  }
  try {
    // Only runs that actually produced people can become a crowd.
    const res = await listSimulations()
    runs.value = (res.data || []).filter(r => (r.profiles_count || 0) > 0)
  } catch {
    runs.value = []
  }
  loading.value = false
})

async function capture () {
  if (capturing.value) return
  capturing.value = true
  captureError.value = ''
  try {
    const res = await captureCrowd({
      simulation_id: captureRunId.value,
      name: captureName.value.trim(),
    })
    await loadCrowds()
    selectedId.value = res.data.crowd_id
    showCapture.value = false
    captureName.value = ''
    captureRunId.value = ''
  } catch (e) {
    captureError.value = e.message || 'Could not save those people.'
  } finally {
    capturing.value = false
  }
}

async function ask () {
  if (!canAsk.value || asking.value) return

  asking.value = true
  askError.value = ''
  result.value = null

  try {
    const res = await askCrowd(selectedId.value, {
      question: question.value.trim(),
      sample_size: sampleSize.value
    })
    result.value = res.data
    refreshAccount()
  } catch (e) {
    askError.value = e.message || 'That did not work. Please try again.'
  } finally {
    asking.value = false
  }
}
</script>

<style scoped>
.crowds {
  min-height: 100vh;
  background: var(--mf-ground);
}

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

.nav__credits {
  border: 0;
  background: transparent;
  padding: 0;
  font-size: var(--mf-text-sm);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-secondary);
  cursor: pointer;
}
.nav__credits:hover { color: var(--mf-accent); }

.main {
  max-width: 760px;
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-8);
  padding-top: var(--mf-space-8);
  padding-bottom: var(--mf-space-9);
}

.head__title {
  font-size: clamp(var(--mf-text-2xl), 6vw, var(--mf-text-3xl));
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: var(--mf-leading-tight);
}

.head__lede {
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-md);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-secondary);
  max-width: 52ch;
}

.notice {
  font-size: var(--mf-text-base);
  color: var(--mf-ink-muted);
}
.notice--error { color: var(--mf-danger); }

/* ---- Empty ---- */

.empty {
  padding: var(--mf-space-7) var(--mf-space-6);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--mf-space-3);
}

.empty__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.empty__body {
  color: var(--mf-ink-secondary);
  max-width: 44ch;
  margin-bottom: var(--mf-space-2);
}

/* ---- Steps ---- */

.step {
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-4);
}

.step__head {
  display: flex;
  align-items: center;
  gap: var(--mf-space-3);
}

.step__n {
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

.step__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

/* ---- Capture ---- */

.capture { padding: var(--mf-space-5); }

.capture__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.capture__body {
  margin-top: var(--mf-space-2);
  color: var(--mf-ink-secondary);
}

.capture__row {
  margin-top: var(--mf-space-4);
  display: flex;
  gap: var(--mf-space-3);
  flex-wrap: wrap;
  align-items: center;
}

.capture__row .mf-input { flex: 1 1 200px; width: auto; }

.capture__select {
  height: 40px;
  padding: 0 var(--mf-space-3);
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator-strong);
  border-radius: var(--mf-radius-md);
  color: var(--mf-ink);
  cursor: pointer;
}

.capture__error {
  margin-top: var(--mf-space-3);
  color: var(--mf-danger);
  font-size: var(--mf-text-sm);
}

.capture__note {
  margin-top: var(--mf-space-3);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.empty__actions {
  display: flex;
  gap: var(--mf-space-3);
  flex-wrap: wrap;
  justify-content: center;
}

.step__toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: calc(var(--mf-space-2) * -1);
}

/* ---- Crowd picker ---- */

.crowdlist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: var(--mf-space-3);
}

.crowdcard {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--mf-space-1);
  padding: var(--mf-space-4);
  text-align: left;
  background: var(--mf-surface);
  border: 2px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
  cursor: pointer;
  transition:
    border-color var(--mf-duration) var(--mf-ease),
    background-color var(--mf-duration) var(--mf-ease);
}

.crowdcard:hover { border-color: var(--mf-separator-strong); }

.crowdcard.is-selected {
  border-color: var(--mf-accent);
  background: var(--mf-accent-soft);
}

.crowdcard__name {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.crowdcard__meta {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.crowdcard__desc {
  margin-top: var(--mf-space-1);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-secondary);
  line-height: var(--mf-leading-normal);
}

/* ---- Question ---- */

.ask__textarea {
  font-size: var(--mf-text-md);
  min-height: 96px;
  padding: var(--mf-space-4);
}

.sample {
  display: flex;
  align-items: center;
  gap: var(--mf-space-3);
}

.sample__label {
  font-size: var(--mf-text-base);
  color: var(--mf-ink-secondary);
}

.sample__select {
  height: 40px;
  padding: 0 var(--mf-space-3);
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator-strong);
  border-radius: var(--mf-radius-md);
  font-size: var(--mf-text-base);
  color: var(--mf-ink);
  cursor: pointer;
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

.go__error { color: var(--mf-danger); }

/* ---- Answers ---- */

.answers__head { margin-bottom: var(--mf-space-5); }

.answers__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.answers__meta {
  margin-top: var(--mf-space-2);
  font-size: var(--mf-text-base);
  color: var(--mf-ink-muted);
}

.answerlist {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-4);
}

.answer {
  padding: var(--mf-space-4) var(--mf-space-5);
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
}

.answer__who {
  display: flex;
  align-items: baseline;
  gap: var(--mf-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--mf-space-2);
}

.answer__name {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.answer__detail {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.answer__text {
  font-size: var(--mf-text-base);
  line-height: var(--mf-leading-relaxed);
  color: var(--mf-ink-secondary);
}

@media (max-width: 560px) {
  .go__btn { max-width: none; }
  .crowdlist { grid-template-columns: minmax(0, 1fr); }
}
</style>
