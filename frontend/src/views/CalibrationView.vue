<template>
  <div class="cal">
    <nav class="nav">
      <div class="mf-container nav__inner">
        <a class="nav__brand" href="/" @click.prevent="$router.push('/')">SpiderNet</a>
        <button
          v-if="credits !== null"
          class="nav__credits mf-mono"
          @click="$router.push('/billing')"
        >
          {{ credits.toLocaleString() }} credits
        </button>
      </div>
    </nav>

    <main class="mf-container main">
      <header class="head">
        <h1 class="head__title">Track record</h1>
        <p class="head__lede">
          Write down what you expect before you know. Come back and record what
          actually happened. Over time this is the only honest answer to "is any
          of this right?"
        </p>
      </header>

      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <!-- Score -->
      <section v-if="score" class="mf-card score">
        <template v-if="score.resolved === 0">
          <p class="score__empty">
            Nothing has been settled yet. The score appears once you record what
            happened to at least one prediction.
          </p>
        </template>
        <template v-else>
          <div class="score__row">
            <div class="score__item">
              <span class="score__label">Brier score</span>
              <span class="score__value mf-mono">{{ score.mean_brier.toFixed(3) }}</span>
              <span class="score__note">lower is better · 0 is perfect</span>
            </div>
            <div class="score__item">
              <span class="score__label">Coin flip scores</span>
              <span class="score__value mf-mono score__value--muted">0.250</span>
              <span class="score__note">the bar to clear</span>
            </div>
            <div class="score__item">
              <span class="score__label">Called correctly</span>
              <span class="score__value mf-mono">{{ (score.hit_rate * 100).toFixed(0) }}%</span>
              <span class="score__note">{{ score.resolved }} settled</span>
            </div>
          </div>
          <p class="score__verdict" :class="score.beats_coin_flip ? 'is-good' : 'is-bad'">
            {{ score.beats_coin_flip
              ? 'Better than guessing, on the record so far.'
              : 'No better than guessing yet.' }}
          </p>
        </template>
      </section>

      <!-- New prediction -->
      <section class="mf-card new" aria-labelledby="new-title">
        <h2 id="new-title" class="new__title">Write down a prediction</h2>

        <label class="field">
          <span class="field__label">What did you ask?</span>
          <input v-model="form.question" class="mf-input"
                 placeholder="How will people react to the price rise?" />
        </label>

        <label class="field">
          <span class="field__label">What do you expect to happen?</span>
          <input v-model="form.claim" class="mf-input"
                 placeholder="More complaints than praise in the first week" />
          <span class="field__hint">
            Make it something you can later say yes or no to.
          </span>
        </label>

        <label class="field">
          <span class="field__label">
            How sure are you? <strong class="mf-mono">{{ form.probability }}%</strong>
          </span>
          <input v-model.number="form.probability" type="range" min="1" max="99"
                 class="field__slider" />
          <span class="field__hint">
            Being confidently wrong costs more than hedging, so say what you
            actually think.
          </span>
        </label>

        <button class="mf-btn mf-btn--primary" :disabled="!canRecord || saving"
                @click="record">
          {{ saving ? 'Saving…' : 'Write it down' }}
        </button>
      </section>

      <!-- Open -->
      <section v-if="open.length" class="section">
        <h2 class="section__title">Waiting on reality</h2>
        <ul class="list">
          <li v-for="p in open" :key="p.prediction_id" class="item">
            <div class="item__body">
              <p class="item__claim">{{ p.claim }}</p>
              <p class="item__meta">
                <span class="mf-mono">{{ (p.probability * 100).toFixed(0) }}%</span>
                · {{ p.question }}
              </p>
            </div>
            <div class="item__actions">
              <button class="mf-btn mf-btn--secondary mf-btn--sm"
                      :disabled="resolving === p.prediction_id"
                      @click="settle(p, true)">
                It happened
              </button>
              <button class="mf-btn mf-btn--secondary mf-btn--sm"
                      :disabled="resolving === p.prediction_id"
                      @click="settle(p, false)">
                It didn't
              </button>
            </div>
          </li>
        </ul>
      </section>

      <!-- Settled -->
      <section v-if="resolved.length" class="section">
        <h2 class="section__title">Settled</h2>
        <ul class="list">
          <li v-for="p in resolved" :key="p.prediction_id" class="item item--done">
            <div class="item__body">
              <p class="item__claim">{{ p.claim }}</p>
              <p class="item__meta">
                said <span class="mf-mono">{{ (p.probability * 100).toFixed(0) }}%</span>
                · {{ p.outcome ? 'it happened' : "it didn't" }}
              </p>
            </div>
            <span class="item__score mf-pill"
                  :class="p.brier <= 0.25 ? 'mf-pill--success' : 'mf-pill--warning'">
              {{ p.brier.toFixed(3) }}
            </span>
          </li>
        </ul>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { credits, hasKey } from '../store/accessKey'
import { refreshAccount } from '../api/account'
import {
  recordPrediction, listPredictions, resolvePrediction, getScorecard,
} from '../api/calibration'

const predictions = ref([])
const score = ref(null)
const error = ref('')
const saving = ref(false)
const resolving = ref(null)

const form = ref({ question: '', claim: '', probability: 60 })

const canRecord = computed(() =>
  form.value.question.trim() !== '' && form.value.claim.trim() !== ''
)

const open = computed(() => predictions.value.filter(p => p.status === 'open'))
const resolved = computed(() => predictions.value.filter(p => p.status === 'resolved'))

async function load () {
  const [list, card] = await Promise.all([listPredictions(), getScorecard()])
  predictions.value = list.data || []
  score.value = card.data
}

onMounted(async () => {
  if (hasKey.value) refreshAccount()
  try {
    await load()
  } catch (e) {
    error.value = e.message || 'Could not load your track record.'
  }
})

async function record () {
  if (!canRecord.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    await recordPrediction({
      question: form.value.question.trim(),
      claim: form.value.claim.trim(),
      // The API takes 0–1; the slider is friendlier in percent.
      probability: form.value.probability / 100,
    })
    form.value.question = ''
    form.value.claim = ''
    form.value.probability = 60
    await load()
  } catch (e) {
    error.value = e.message || 'Could not save that prediction.'
  } finally {
    saving.value = false
  }
}

async function settle (prediction, outcome) {
  resolving.value = prediction.prediction_id
  error.value = ''
  try {
    await resolvePrediction(prediction.prediction_id, outcome)
    await load()
  } catch (e) {
    error.value = e.message || 'Could not record that outcome.'
  } finally {
    resolving.value = null
  }
}
</script>

<style scoped>
.cal { min-height: 100vh; background: var(--mf-ground); }

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
  gap: var(--mf-space-7);
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
  max-width: 54ch;
}

.banner {
  padding: var(--mf-space-3) var(--mf-space-4);
  border-radius: var(--mf-radius-md);
  font-size: var(--mf-text-base);
}
.banner--error { background: var(--mf-danger-soft); color: var(--mf-danger); }

/* ---- Score ---- */

.score { padding: var(--mf-space-6); }

.score__empty { color: var(--mf-ink-muted); }

.score__row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: var(--mf-space-5);
}

.score__item { display: flex; flex-direction: column; gap: var(--mf-space-1); }

.score__label {
  font-size: var(--mf-text-2xs);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-caps);
  text-transform: uppercase;
  color: var(--mf-ink-muted);
}

.score__value {
  font-size: var(--mf-text-2xl);
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: 1.1;
}

.score__value--muted { color: var(--mf-ink-faint); }

.score__note { font-size: var(--mf-text-xs); color: var(--mf-ink-faint); }

.score__verdict {
  margin-top: var(--mf-space-5);
  padding-top: var(--mf-space-4);
  border-top: 1px solid var(--mf-separator);
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-medium);
}
.score__verdict.is-good { color: var(--mf-success); }
.score__verdict.is-bad { color: var(--mf-warning); }

/* ---- New prediction ---- */

.new {
  padding: var(--mf-space-6);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-5);
  align-items: flex-start;
}

.new__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.field {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-2);
}

.field__label {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink);
}

.field__hint { font-size: var(--mf-text-sm); color: var(--mf-ink-muted); }

.field__slider { width: 100%; accent-color: var(--mf-accent); }

/* ---- Lists ---- */

.section__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
  margin-bottom: var(--mf-space-4);
}

.list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-3);
}

.item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mf-space-4);
  flex-wrap: wrap;
  padding: var(--mf-space-4) var(--mf-space-5);
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
}

.item--done { opacity: 0.85; }

.item__body { flex: 1 1 260px; min-width: 0; }

.item__claim {
  font-size: var(--mf-text-base);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink);
}

.item__meta {
  margin-top: var(--mf-space-1);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.item__actions { display: flex; gap: var(--mf-space-2); }

@media (max-width: 560px) {
  .item__actions { width: 100%; }
  .item__actions .mf-btn { flex: 1; }
}
</style>
