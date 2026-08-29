import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { requestWithRetry, isRetryableError } from '../src/api/index.js'

const networkError = () => Object.assign(new Error('Network Error'), {
  code: 'ERR_NETWORK', request: {}
})
const timeoutError = () => Object.assign(new Error('timeout of 300000ms exceeded'), {
  code: 'ECONNABORTED', request: {}
})
const httpError = (status) => Object.assign(new Error(`Request failed with status code ${status}`), {
  response: { status }, request: {}
})

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

/** Run a retrying call to completion, flushing the backoff timers. */
async function settle(promise) {
  const outcome = promise.then(v => ({ ok: v }), e => ({ err: e }))
  await vi.runAllTimersAsync()
  return outcome
}

describe('isRetryableError', () => {
  it('never retries a request the server answered', () => {
    for (const status of [400, 401, 404, 409, 422, 500, 502, 503]) {
      expect(isRetryableError(httpError(status))).toBe(false)
    }
  })

  it('never retries a timeout - the server may have processed it', () => {
    expect(isRetryableError(timeoutError())).toBe(false)
  })

  it('retries a connection that never established', () => {
    expect(isRetryableError(networkError())).toBe(true)
  })
})

describe('requestWithRetry', () => {
  it('returns the value without retrying on success', async () => {
    const fn = vi.fn().mockResolvedValue({ success: true })
    const { ok } = await settle(requestWithRetry(fn))
    expect(ok).toEqual({ success: true })
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('does NOT retry a timeout on a non-idempotent call', async () => {
    // This is the duplicate-simulation bug: a 5 minute timeout on
    // POST /api/simulation/create, retried 3x, created three simulations.
    const fn = vi.fn().mockRejectedValue(timeoutError())
    const { err } = await settle(requestWithRetry(fn, 3, 1000))
    expect(fn).toHaveBeenCalledTimes(1)
    expect(err.code).toBe('ECONNABORTED')
  })

  it('does NOT retry a 4xx that will fail identically', async () => {
    const fn = vi.fn().mockRejectedValue(httpError(400))
    const { err } = await settle(requestWithRetry(fn, 3, 1000))
    expect(fn).toHaveBeenCalledTimes(1)
    expect(err.response.status).toBe(400)
  })

  it('does NOT retry a 5xx that may already have had a side effect', async () => {
    const fn = vi.fn().mockRejectedValue(httpError(500))
    await settle(requestWithRetry(fn, 3, 1000))
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('retries a genuine connection failure and succeeds', async () => {
    const fn = vi.fn()
      .mockRejectedValueOnce(networkError())
      .mockRejectedValueOnce(networkError())
      .mockResolvedValue({ success: true })
    const { ok } = await settle(requestWithRetry(fn, 3, 1000))
    expect(ok).toEqual({ success: true })
    expect(fn).toHaveBeenCalledTimes(3)
  })

  it('backs off exponentially: 1s then 2s', async () => {
    const delays = []
    const spy = vi.spyOn(globalThis, 'setTimeout').mockImplementation((cb, ms) => {
      delays.push(ms); return cb()
    })
    const fn = vi.fn().mockRejectedValue(networkError())
    await requestWithRetry(fn, 3, 1000).catch(() => {})
    expect(delays).toEqual([1000, 2000])
    spy.mockRestore()
  })

  it('throws the last error after exhausting attempts', async () => {
    const fn = vi.fn().mockRejectedValue(networkError())
    const { err } = await settle(requestWithRetry(fn, 3, 1000))
    expect(fn).toHaveBeenCalledTimes(3)
    expect(err.code).toBe('ERR_NETWORK')
  })

  it('throws rather than resolving undefined when maxRetries is 0', async () => {
    // The old loop never executed and silently returned undefined.
    const fn = vi.fn().mockRejectedValue(networkError())
    const { ok, err } = await settle(requestWithRetry(fn, 0, 1000))
    expect(ok).toBeUndefined()
    expect(err).toBeInstanceOf(Error)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('honours a caller-supplied retry policy', async () => {
    const fn = vi.fn().mockRejectedValue(httpError(503))
    await settle(requestWithRetry(fn, 3, 1000, { isRetryable: () => true }))
    expect(fn).toHaveBeenCalledTimes(3)
  })
})
