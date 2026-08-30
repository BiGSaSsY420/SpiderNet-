<template>
  <div class="billing">
    <nav class="nav">
      <div class="mf-container nav__inner">
        <a class="nav__brand" href="/" @click.prevent="$router.push('/')">SpiderNet</a>
        <span v-if="credits !== null" class="nav__credits mf-mono">
          {{ credits.toLocaleString() }} credits
        </span>
      </div>
    </nav>

    <main class="mf-container main">
      <header class="head">
        <h1 class="head__title">Credits</h1>
        <p class="head__lede">
          A plan gives you credits every month. Top-ups are extra credits you buy
          once — those never expire.
        </p>
      </header>

      <p v-if="justPaid" class="banner banner--ok" role="status">
        Payment received. Your credits appear here within a few seconds.
      </p>
      <p v-if="error" class="banner banner--error" role="alert">{{ error }}</p>

      <!-- Where you stand -->
      <section v-if="account" class="mf-card balance">
        <div class="balance__total">
          <span class="balance__num mf-mono">{{ credits.toLocaleString() }}</span>
          <span class="balance__unit">credits left</span>
        </div>

        <dl class="balance__split">
          <div class="balance__row">
            <dt>
              This month's allowance
              <span v-if="account.period_end" class="balance__note">
                refreshes {{ formatDate(account.period_end) }}
              </span>
            </dt>
            <dd class="mf-mono">{{ account.subscription_credits.toLocaleString() }}</dd>
          </div>
          <div class="balance__row">
            <dt>
              Top-ups
              <span class="balance__note">never expire</span>
            </dt>
            <dd class="mf-mono">{{ account.topup_credits.toLocaleString() }}</dd>
          </div>
        </dl>

        <p class="balance__order">
          Your monthly allowance is spent first, so nothing you bought outright
          goes to waste.
        </p>

        <p v-if="account.subscription_status === 'past_due'" class="balance__warn">
          Your last payment didn't go through, so the monthly allowance has
          stopped. Anything you bought outright is untouched.
        </p>
      </section>

      <!-- Plans -->
      <section class="section" aria-labelledby="plans-title">
        <h2 id="plans-title" class="section__title">Monthly plans</h2>

        <ul class="cards">
          <li v-for="plan in paidPlans" :key="plan.id" class="mf-card card"
              :class="{ 'is-current': account && account.plan === plan.id
                                       && account.subscription_status === 'active' }">
            <h3 class="card__name">{{ plan.label }}</h3>
            <p class="card__price">
              <span class="card__amount mf-mono">${{ plan.price_usd }}</span>
              <span class="card__per">/month</span>
            </p>
            <p class="card__credits">
              {{ plan.monthly_credits.toLocaleString() }} credits a month
            </p>
            <p class="card__rate mf-mono">
              {{ perCredit(plan.price_usd, plan.monthly_credits) }} per credit
            </p>

            <button
              class="mf-btn mf-btn--primary mf-btn--block card__btn"
              :disabled="busy || !paymentsEnabled"
              @click="startSubscription(plan.id)"
            >
              {{ currentPlan === plan.id ? 'Current plan' : 'Choose' }}
            </button>
          </li>
        </ul>
      </section>

      <!-- Top-ups -->
      <section class="section" aria-labelledby="topups-title">
        <h2 id="topups-title" class="section__title">One-off top-ups</h2>
        <p class="section__lede">
          For a busy month. Slightly dearer per credit than a plan, and they
          never expire.
        </p>

        <ul class="cards">
          <li v-for="pack in topups" :key="pack.id" class="mf-card card">
            <h3 class="card__name">{{ pack.label }}</h3>
            <p class="card__price">
              <span class="card__amount mf-mono">${{ pack.price_usd }}</span>
              <span class="card__per">once</span>
            </p>
            <p class="card__rate mf-mono">
              {{ perCredit(pack.price_usd, pack.credits) }} per credit
            </p>

            <button
              class="mf-btn mf-btn--secondary mf-btn--block card__btn"
              :disabled="busy || !paymentsEnabled"
              @click="startTopup(pack.id)"
            >
              Buy
            </button>
          </li>
        </ul>

        <p v-if="!paymentsEnabled && !loading" class="section__note">
          Payments aren't switched on yet. Ask us and we'll add credits by hand.
        </p>
      </section>

      <!-- History -->
      <section v-if="ledger.length" class="section" aria-labelledby="history-title">
        <h2 id="history-title" class="section__title">History</h2>
        <div class="mf-scroll-x">
          <table class="ledger">
            <thead>
              <tr>
                <th>When</th><th>What</th><th class="num">Change</th><th class="num">Balance</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(entry, i) in ledger" :key="i">
                <td>{{ formatDate(entry.at) }}</td>
                <td>{{ describe(entry) }}</td>
                <td class="num mf-mono" :class="entry.delta < 0 ? 'is-spend' : 'is-add'">
                  {{ entry.delta > 0 ? '+' : '' }}{{ entry.delta.toLocaleString() }}
                </td>
                <td class="num mf-mono">{{ entry.balance_after.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <LicenceFooter />
  </div>
</template>

<script setup>
import LicenceFooter from '../components/LicenceFooter.vue'
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { account, credits, hasKey } from '../store/accessKey'
import { refreshAccount } from '../api/account'
import {
  getPlans, getLedger, checkoutSubscription, checkoutTopup,
} from '../api/billing'

const route = useRoute()

const plans = ref([])
const topups = ref([])
const ledger = ref([])
const paymentsEnabled = ref(false)

const loading = ref(true)
const busy = ref(false)
const error = ref('')

const justPaid = computed(() => route.query.paid === '1')
const paidPlans = computed(() => plans.value.filter(p => p.price_usd > 0))
const currentPlan = computed(() =>
  account.value && account.value.subscription_status === 'active'
    ? account.value.plan
    : null
)

function perCredit (dollars, creditCount) {
  if (!creditCount) return '—'
  return `$${(dollars / creditCount).toFixed(3)}`
}

function formatDate (iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? ''
    : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function describe (entry) {
  const bucket = {
    issue: 'Key created',
    topup: 'Top-up',
    subscription: 'Plan',
    charge: 'Used',
    refund: 'Refunded',
  }[entry.bucket] || entry.bucket
  return entry.reason ? `${bucket} — ${entry.reason}` : bucket
}

onMounted(async () => {
  try {
    const res = await getPlans()
    plans.value = res.data.plans
    topups.value = res.data.topups
    paymentsEnabled.value = res.data.payments_enabled
  } catch (e) {
    error.value = e.message || 'Could not load the plans.'
  }

  if (hasKey.value) {
    refreshAccount()
    try {
      ledger.value = (await getLedger()).data || []
    } catch {
      // A missing history is not worth an error banner.
    }
  }
  loading.value = false
})

async function go (request) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    const res = await request()
    // Stripe hosts the card form; we never see the card details.
    window.location.href = res.data.checkout_url
  } catch (e) {
    error.value = e.message || 'Could not start the payment. Please try again.'
    busy.value = false
  }
}

const startSubscription = (plan) => go(() => checkoutSubscription(plan))
const startTopup = (pack) => go(() => checkoutTopup(pack))
</script>

<style scoped>
.billing {
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
  font-size: var(--mf-text-sm);
  font-weight: var(--mf-weight-medium);
  color: var(--mf-ink-secondary);
}

.main {
  max-width: 860px;
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
  max-width: 54ch;
}

.banner {
  padding: var(--mf-space-3) var(--mf-space-4);
  border-radius: var(--mf-radius-md);
  font-size: var(--mf-text-base);
}
.banner--ok { background: var(--mf-success-soft); color: var(--mf-success); }
.banner--error { background: var(--mf-danger-soft); color: var(--mf-danger); }

/* ---- Balance ---- */

.balance { padding: var(--mf-space-6); }

.balance__total {
  display: flex;
  align-items: baseline;
  gap: var(--mf-space-3);
}

.balance__num {
  font-size: var(--mf-text-3xl);
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-display);
  line-height: 1;
}

.balance__unit {
  font-size: var(--mf-text-md);
  color: var(--mf-ink-muted);
}

.balance__split {
  margin: var(--mf-space-5) 0 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--mf-separator);
  border: 1px solid var(--mf-separator);
  border-radius: var(--mf-radius-md);
  overflow: hidden;
}

.balance__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--mf-space-4);
  padding: var(--mf-space-3) var(--mf-space-4);
  background: var(--mf-surface);
}

.balance__row dt {
  font-size: var(--mf-text-base);
  color: var(--mf-ink);
}

.balance__row dd {
  margin: 0;
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink);
}

.balance__note {
  display: block;
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.balance__order {
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.balance__warn {
  margin-top: var(--mf-space-4);
  padding: var(--mf-space-3) var(--mf-space-4);
  background: var(--mf-warning-soft);
  color: var(--mf-warning);
  border-radius: var(--mf-radius-md);
  font-size: var(--mf-text-sm);
}

/* ---- Sections ---- */

.section__title {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-semibold);
  letter-spacing: var(--mf-tracking-tight);
}

.section__lede {
  margin-top: var(--mf-space-2);
  color: var(--mf-ink-muted);
  font-size: var(--mf-text-base);
  max-width: 52ch;
}

.section__note {
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.cards {
  list-style: none;
  margin: var(--mf-space-5) 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: var(--mf-space-4);
}

.card {
  padding: var(--mf-space-5);
  display: flex;
  flex-direction: column;
  gap: var(--mf-space-1);
}

.card.is-current { border-color: var(--mf-accent); }

.card__name {
  font-size: var(--mf-text-md);
  font-weight: var(--mf-weight-semibold);
}

.card__price {
  display: flex;
  align-items: baseline;
  gap: var(--mf-space-2);
  margin-top: var(--mf-space-2);
}

.card__amount {
  font-size: var(--mf-text-xl);
  font-weight: var(--mf-weight-bold);
  letter-spacing: var(--mf-tracking-tight);
}

.card__per {
  font-size: var(--mf-text-sm);
  color: var(--mf-ink-muted);
}

.card__credits {
  font-size: var(--mf-text-base);
  color: var(--mf-ink-secondary);
}

.card__rate {
  font-size: var(--mf-text-xs);
  color: var(--mf-ink-faint);
}

.card__btn { margin-top: auto; padding-top: 0; }
.card .card__btn { margin-top: var(--mf-space-4); }

/* ---- Ledger ---- */

.ledger {
  width: 100%;
  min-width: 480px;
  border-collapse: collapse;
  margin-top: var(--mf-space-4);
  font-size: var(--mf-text-sm);
}

.ledger th {
  text-align: left;
  font-weight: var(--mf-weight-semibold);
  color: var(--mf-ink-muted);
  padding: var(--mf-space-2) var(--mf-space-3);
  border-bottom: 1px solid var(--mf-separator);
  white-space: nowrap;
}

.ledger td {
  padding: var(--mf-space-3);
  border-bottom: 1px solid var(--mf-separator);
  color: var(--mf-ink-secondary);
}

.ledger .num { text-align: right; }
.ledger .is-spend { color: var(--mf-ink-muted); }
.ledger .is-add { color: var(--mf-success); }

@media (max-width: 560px) {
  .cards { grid-template-columns: minmax(0, 1fr); }
}
</style>
