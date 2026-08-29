/**
 * The customer's access key.
 *
 * Kept in localStorage so people do not have to paste it on every visit, and
 * exposed as a ref so the header can show the balance live.
 *
 * localStorage can throw outright (Safari private mode, browsers set to block
 * site data), so every read and write is guarded and the app still works with
 * the key held in memory for the session.
 */

import { ref, computed } from 'vue'

const STORAGE_KEY = 'spidernet.access_key'

function readStored () {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

function writeStored (value) {
  try {
    if (value) localStorage.setItem(STORAGE_KEY, value)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // Not fatal: the key stays in memory for this session.
  }
}

export const accessKey = ref(readStored())

/** Balance and plan for the current key, refreshed by refreshAccount(). */
export const account = ref(null)

export const hasKey = computed(() => Boolean(accessKey.value))

export const credits = computed(() =>
  account.value ? account.value.credits_remaining : null
)

export function setAccessKey (value) {
  const trimmed = (value || '').trim()
  accessKey.value = trimmed
  writeStored(trimmed)
  if (!trimmed) account.value = null
}

export function clearAccessKey () {
  setAccessKey('')
}

/**
 * Catch obvious paste errors before we bother the server.
 *
 * Deliberately loose about length: the server is the authority on whether a
 * key is real, and pinning an exact length here means a change to the key
 * format silently locks every customer out of the sign-in form.
 */
export function looksLikeKey (value) {
  return /^sn_[a-z0-9]+_[0-9a-f]{32,}$/i.test((value || '').trim())
}
