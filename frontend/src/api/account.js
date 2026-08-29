import service from './index'
import { account } from '../store/accessKey'

/** Balance and plan for the current key. Free to call. */
export const getAccount = () => service.get('/api/account/me')

/** What each step costs, in credits. No key needed. */
export const getPricing = () => service.get('/api/account/pricing')

/**
 * Refresh the cached account and report whether the key works.
 * Returns the account on success, or null if the key was rejected.
 */
export async function refreshAccount () {
  try {
    const res = await getAccount()
    account.value = res.data
    return res.data
  } catch {
    account.value = null
    return null
  }
}
