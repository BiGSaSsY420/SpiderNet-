import service from './index'

/** Subscription plans and top-up packs. Public - no key needed. */
export const getPlans = () => service.get('/api/account/plans')

/** Every credit movement on this key. */
export const getLedger = () => service.get('/api/account/ledger')

/** Start paying for a monthly plan. Returns a Stripe Checkout URL. */
export const checkoutSubscription = (plan) =>
  service.post('/api/account/checkout/subscription', { plan })

/** Buy a one-off pack of credits that never expire. */
export const checkoutTopup = (pack) =>
  service.post('/api/account/checkout/topup', { pack })
