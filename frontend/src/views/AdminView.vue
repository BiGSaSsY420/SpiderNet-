<template>
  <div class="admin">
    <nav class="nav">
      <div class="nav__inner">
        <span class="nav__brand">SpiderNet <span class="nav__tag">operator</span></span>
        <button v-if="unlocked" class="mf-btn mf-btn--ghost mf-btn--sm" @click="lock">
          Lock
        </button>
      </div>
    </nav>

    <!-- Token gate -->
    <main v-if="!unlocked" class="gate-wrap">
      <form class="mf-card gate" @submit.prevent="unlock">
        <h1 class="gate__title">Operator console</h1>
        <p class="gate__body">This shows every customer. Enter the operator token.</p>
        <input
          v-model="tokenInput"
          class="mf-input mf-mono"
          type="password"
          autocomplete="off"
          spellcheck="false"
          placeholder="Operator token"
          aria-label="Operator token"
        />
        <button class="mf-btn mf-btn--primary mf-btn--block" type="submit"
                :disabled="!tokenInput.trim() || checking">
          {{ checking ? 'Checking…' : 'Unlock' }}
        </button>
        <p v-if="gateError" class="gate__error" role="alert">{{ gateError }}</p>
      </form>
    </main>

    <main v-else class="main">
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <!-- The numbers -->
      <section class="tiles" aria-label="Business summary">
        <div class="tile tile--wide">
          <span class="tile__label">Monthly recurring</span>
          <span class="tile__value mf-mono">${{ fmt(overview.mrr_usd) }}</span>
          <span class="tile__sub mf-mono">${{ fmt(overview.arr_usd) }} annualised</span>
        </div>
        <div class="tile">
          <span class="tile__label">Subscribers</span>
          <span class="tile__value mf-mono">{{ fmt(overview.subscribers) }}</span>
          <span class="tile__sub">of {{ fmt(overview.active_customers) }} active</span>
        </div>
        <div class="tile" :class="{ 'tile--warn': overview.past_due > 0 }">
          <span class="tile__label">Past due</span>
          <span class="tile__value mf-mono">{{ fmt(overview.past_due) }}</span>
          <span class="tile__sub">payment failed</span>
        </div>
        <div class="tile">
          <span class="tile__label">Credits owed</span>
          <span class="tile__value mf-mono">{{ fmt(overview.credits_outstanding) }}</span>
          <span class="tile__sub">liability, not revenue</span>
        </div>
        <div class="tile">
          <span class="tile__label">Delivered</span>
          <span class="tile__value mf-mono">{{ fmt(overview.credits_delivered) }}</span>
          <span class="tile__sub">{{ fmt(overview.credits_spent_30d) }} in 30 days</span>
        </div>
      </section>

      <p v-if="!overview.payments_enabled" class="banner banner--warn">
        Stripe isn't configured, so nothing can be bought. Credits can still be
        granted by hand below.
      </p>

      <!-- Customers -->
      <section class="section">
        <div class="section__head">
          <h2 class="section__title">Customers</h2>
          <button class="mf-btn mf-btn--secondary mf-btn--sm" @click="showNew = !showNew">
            {{ showNew ? 'Cancel' : 'Issue a key' }}
          </button>
        </div>

        <form v-if="showNew" class="mf-card newkey" @submit.prevent="issueKey">
          <div class="newkey__row">
            <input v-model="newLabel" class="mf-input" placeholder="Customer name"
                   aria-label="Customer name" />
            <select v-model="newPlan" class="newkey__select" aria-label="Plan">
              <option v-for="p in planIds" :key="p" :value="p">{{ p }}</option>
            </select>
            <label class="newkey__check">
              <input v-model="newSubscribe" type="checkbox" />
              start the plan
            </label>
            <button class="mf-btn mf-btn--primary" type="submit" :disabled="!newLabel.trim()">
              Issue
            </button>
          </div>
          <p v-if="issuedKey" class="newkey__issued">
            Copy this now — it cannot be shown again:
            <code class="mf-mono">{{ issuedKey }}</code>
          </p>
        </form>

        <div class="mf-scroll-x">
          <table class="grid">
            <thead>
              <tr>
                <th>Customer</th><th>Plan</th><th class="num">Allowance</th>
                <th class="num">Top-ups</th><th class="num">Used</th>
                <th>State</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="c in customers" :key="c.public_id"
                  :class="{ 'is-revoked': c.status !== 'active' }">
                <td>
                  <button class="linkish" @click="open(c.public_id)">{{ c.label }}</button>
                  <span class="grid__id mf-mono">{{ c.public_id }}</span>
                </td>
                <td>{{ c.plan_label || c.plan }}</td>
                <td class="num mf-mono">{{ fmt(c.subscription_credits) }}</td>
                <td class="num mf-mono">{{ fmt(c.topup_credits) }}</td>
                <td class="num mf-mono">{{ fmt(c.credits_used) }}</td>
                <td>
                  <span class="mf-pill" :class="stateClass(c)">{{ stateLabel(c) }}</span>
                </td>
                <td class="num">
                  <button class="linkish" @click="grant(c)">+ credits</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Detail -->
      <section v-if="detail" class="section">
        <div class="section__head">
          <h2 class="section__title">{{ detail.label }}</h2>
          <button class="mf-btn mf-btn--ghost mf-btn--sm" @click="detail = null">Close</button>
        </div>
        <div class="mf-scroll-x">
          <table class="grid">
            <thead>
              <tr><th>When</th><th>What</th><th class="num">Change</th><th class="num">Balance</th></tr>
            </thead>
            <tbody>
              <tr v-for="(e, i) in detail.ledger" :key="i">
                <td>{{ when(e.at) }}</td>
                <td>{{ e.bucket }}<template v-if="e.reason"> — {{ e.reason }}</template></td>
                <td class="num mf-mono" :class="e.delta < 0 ? 'is-spend' : 'is-add'">
                  {{ e.delta > 0 ? '+' : '' }}{{ fmt(e.delta) }}
                </td>
                <td class="num mf-mono">{{ fmt(e.balance_after) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Crowds worth promoting -->
      <section v-if="crowds.length" class="section">
        <h2 class="section__title">Crowds by use</h2>
        <p class="section__lede">
          The most-polled private crowds are the candidates for the shared library.
        </p>
        <div class="mf-scroll-x">
          <table class="grid">
            <thead>
              <tr><th>Crowd</th><th class="num">People</th><th class="num">Polls</th><th>Visibility</th></tr>
            </thead>
            <tbody>
              <tr v-for="c in crowds" :key="c.crowd_id">
                <td>{{ c.name }}</td>
                <td class="num mf-mono">{{ fmt(c.size) }}</td>
                <td class="num mf-mono">{{ fmt(c.poll_count) }}</td>
                <td>{{ c.visibility }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- Activity -->
      <section v-if="overview.recent_activity && overview.recent_activity.length"
               class="section">
        <h2 class="section__title">Latest activity</h2>
        <ul class="feed">
          <li v-for="(e, i) in overview.recent_activity" :key="i" class="feed__item">
            <span class="feed__when mf-mono">{{ when(e.at) }}</span>
            <span class="feed__who">{{ e.label || e.public_id }}</span>
            <span class="feed__what">{{ e.bucket }}<template v-if="e.reason"> — {{ e.reason }}</template></span>
            <span class="feed__delta mf-mono" :class="e.delta < 0 ? 'is-spend' : 'is-add'">
              {{ e.delta > 0 ? '+' : '' }}{{ fmt(e.delta) }}
            </span>
          </li>
        </ul>
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import service from '../api/index'

const TOKEN_KEY = 'spidernet.admin_token'

const token = ref('')
const tokenInput = ref('')
const unlocked = ref(false)
const checking = ref(false)
const gateError = ref('')
const error = ref('')

const overview = ref({})
const customers = ref([])
const crowds = ref([])
const detail = ref(null)

const showNew = ref(false)
const newLabel = ref('')
const newPlan = ref('trial')
const newSubscribe = ref(false)
const issuedKey = ref('')
const planIds = ref(['trial', 'starter', 'pro', 'scale'])

const fmt = (n) => (n === undefined || n === null ? '—' : Number(n).toLocaleString())

function when (iso) {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function stateLabel (c) {
  if (c.status !== 'active') return 'revoked'
  return c.subscription_status === 'none' ? 'pay as you go' : c.subscription_status
}

function stateClass (c) {
  if (c.status !== 'active') return 'mf-pill--danger'
  return {
    active: 'mf-pill--success',
    past_due: 'mf-pill--warning',
    canceled: 'mf-pill--neutral',
  }[c.subscription_status] || 'mf-pill--neutral'
}

/** The operator token travels in its own header, never the customer one. */
function adminRequest (method, url, data) {
  return service({
    method, url, data,
    headers: { 'X-SpiderNet-Admin': token.value },
  })
}

async function load () {
  error.value = ''
  try {
    const [o, c, cr] = await Promise.all([
      adminRequest('get', '/api/admin/overview'),
      adminRequest('get', '/api/admin/customers'),
      adminRequest('get', '/api/admin/crowds'),
    ])
    overview.value = o.data
    customers.value = c.data
    crowds.value = cr.data
  } catch (e) {
    error.value = e.message || 'Could not load the console.'
  }
}

async function unlock () {
  checking.value = true
  gateError.value = ''
  token.value = tokenInput.value.trim()
  try {
    await adminRequest('get', '/api/admin/status')
    unlocked.value = true
    tokenInput.value = ''
    // Session-scoped on purpose: an operator token in localStorage outlives
    // the person who typed it.
    try { sessionStorage.setItem(TOKEN_KEY, token.value) } catch { /* fine */ }
    await load()
  } catch {
    token.value = ''
    gateError.value = 'That token was not accepted.'
  } finally {
    checking.value = false
  }
}

function lock () {
  token.value = ''
  unlocked.value = false
  detail.value = null
  try { sessionStorage.removeItem(TOKEN_KEY) } catch { /* fine */ }
}

async function open (publicId) {
  try {
    detail.value = (await adminRequest('get', `/api/admin/customers/${publicId}`)).data
  } catch (e) {
    error.value = e.message || 'Could not load that customer.'
  }
}

async function grant (customer) {
  const raw = window.prompt(`How many credits for ${customer.label}?`, '500')
  if (!raw) return
  const credits = parseInt(raw, 10)
  if (!Number.isFinite(credits) || credits <= 0) {
    error.value = 'Enter a positive whole number of credits.'
    return
  }
  try {
    await adminRequest('post', `/api/admin/customers/${customer.public_id}/credits`,
                       { credits, reason: 'granted by operator' })
    await load()
  } catch (e) {
    error.value = e.message || 'Could not grant those credits.'
  }
}

async function issueKey () {
  issuedKey.value = ''
  try {
    const res = await adminRequest('post', '/api/admin/customers', {
      label: newLabel.value.trim(),
      plan: newPlan.value,
      subscribe: newSubscribe.value,
    })
    issuedKey.value = res.data.key
    newLabel.value = ''
    await load()
  } catch (e) {
    error.value = e.message || 'Could not issue that key.'
  }
}

onMounted(async () => {
  let stored = ''
  try { stored = sessionStorage.getItem(TOKEN_KEY) || '' } catch { /* fine */ }
  if (!stored) return
  token.value = stored
  try {
    await adminRequest('get', '/api/admin/status')
    unlocked.value = true
    await load()
  } catch {
    lock()
  }
})
</script>

<style scoped>
.admin {
  min-height: 100vh;
  background: var(--mf-surface-sunken);
}

.nav {
  height: var(--mf-header-height);
  background: var(--mf-surface);
  border-bottom: 1px solid var(--mf-separator);
}

.nav__inner {
  height: 100%;
  max-width: 1280px;
  margin: 0 auto;
  padding: 0 var(--mf-space-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav__brand {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.nav__tag {
  font-family: var(--mf-font-mono);
  font-size: var(--mf-text-2xs);
  letter-spacing: var(--mf-tracking-caps);
  text-transform: uppercase;
  color: var(--mf-accent);
  margin-left: var(--mf-space-2);
}

/* ---- Gate ---- */

.gate-wrap {
  display: flex;
  justify-content: center;
  padding: var(--mf-space-9) var(--mf-space-4);
}

.gate {
  width: 100%;
  max-width: 380px;
  padding: var(--mf-space-6);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-4);
}

.gate__title {
  font-size: var(--mf-text-lg);
  font-weight: var(--mf-weight-semibold);
}

.gate__body {
  font-size: var(--mf-text-base);
  color: var(--mf-ink-secondary);
  margin-top: calc(var(--mf-space-4) * -1 + var(--mf-space-1));
}

.gate__error { color: var(--mf-danger); font-size: var(--mf-text-sm); }

/* ---- Layout ---- */

.main {
  max-width: 1280px;
  margin: 0 auto;
  padding: var(--mf-space-6) var(--mf-space-5) var(--mf-space-9);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-7);
}

.banner {
  padding: var(--mf-space-3) var(--mf-space-4);
  border-radius: var(--mf-radius-md);
  font-size: var(--mf-text-base);
}
.banner--error { background: var(--mf-danger-soft); color: var(--mf-danger); }
.banner--warn { background: var(--mf-warning-soft); color: var(--mf-warning); }

/* ---- Tiles ---- */

.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--mf-space-3);
}

.tile {
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
  padding: var(--mf-space-4) var(--mf-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-1);
}

.tile--wide { grid-column: span 2; }
.tile--warn { border-color: var(--mf-warning); }

.tile__label {
  font-size: var(--mf-text-2xs);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-caps);
  text-transform: uppercase;
  color: var(--mf-ink-muted);
}

.tile__value {
  font-size: var(--mf-text-2xl);
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: 1.1;
}

.tile__sub {
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}

/* ---- Sections ---- */

.section {
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-lg);
  padding: var(--mf-space-5);
}

.section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mf-space-4);
  margin-bottom: var(--mf-space-4);
}

.section__title {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
}

.section__lede {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
  margin: 0 0 var(--mf-space-4);
}

/* A section with a lede sets its own spacing, so the heading margin would
   double up. */
.section > .section__title { margin-bottom: var(--mf-space-4); }
.section > .section__title + .section__lede { margin-top: calc(var(--mf-space-4) * -1); }

/* ---- New key ---- */

.newkey {
  padding: var(--mf-space-4);
  margin-bottom: var(--mf-space-4);
  background: var(--mf-surface-sunken);
}

.newkey__row {
  display: flex;
  gap: var(--mf-space-3);
  flex-wrap: wrap;
  align-items: center;
}

.newkey__row .mf-input { flex: 1 1 200px; width: auto; }

.newkey__select {
  height: 40px;
  padding: 0 var(--mf-space-3);
  background: var(--mf-surface);
  border: 1px solid var(--mf-separator-strong);
  border-radius: var(--mf-radius-md);
  color: var(--mf-ink);
}

.newkey__check {
  display: inline-flex;
  align-items: center;
  gap: var(--mf-space-2);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-secondary);
}

.newkey__issued {
  margin-top: var(--mf-space-3);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-secondary);
}

.newkey__issued code {
  display: block;
  margin-top: var(--mf-space-2);
  padding: var(--mf-space-2) var(--mf-space-3);
  background: var(--mf-accent-soft);
  color: var(--mf-accent);
  border-radius: var(--mf-radius-sm);
  word-break: break-all;
}

/* ---- Tables ---- */

.grid {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
  font-size: var(--mf-text-sm);
}

.grid th {
  text-align: left;
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink-muted);
  padding: var(--mf-space-2) var(--mf-space-3);
  border-bottom: 1px solid var(--mf-separator);
  white-space: nowrap;
}

.grid td {
  padding: var(--mf-space-3);
  border-bottom: 1px solid var(--mf-separator);
  color: var(--mf-ink-secondary);
  vertical-align: middle;
}

.grid .num { text-align: right; }
.grid tr.is-revoked { opacity: 0.5; }

.grid__id {
  display: block;
  font-size: var(--mf-text-2xs);
  color: var(--mf-ink-faint);
}

.linkish {
  border: 0;
  background: transparent;
  padding: 0;
  font: inherit;
  color: var(--mf-accent);
  cursor: pointer;
}
.linkish:hover { text-decoration: underline; }

.is-spend { color: var(--mf-ink-muted); }
.is-add { color: var(--mf-success); }

/* ---- Feed ---- */

.feed { list-style: none; margin: 0; padding: 0; }

.feed__item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) minmax(0, 2fr) auto;
  gap: var(--mf-space-3);
  align-items: baseline;
  padding: var(--mf-space-2) 0;
  border-bottom: 1px solid var(--mf-separator);
  font-size: var(--mf-text-sm);
}

.feed__when { font-size: var(--mf-text-xs); color: var(--mf-ink-faint); white-space: nowrap; }
.feed__who { font-weight: var(--mf-weight-medium); color: var(--mf-ink); }
.feed__what { color: var(--mf-ink-muted); overflow: hidden; text-overflow: ellipsis; }
.feed__delta { text-align: right; }

@media (max-width: 720px) {
  .tile--wide { grid-column: span 1; }
  .feed__item { grid-template-columns: minmax(0, 1fr) auto; }
  .feed__when, .feed__what { display: none; }
}
</style>
