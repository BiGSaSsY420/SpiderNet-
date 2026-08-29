import { afterEach, beforeEach, vi } from 'vitest'

/**
 * Much of this suite drives failure paths on purpose - retries, rejected
 * envelopes, network errors - and the code under test logs each one. Left
 * alone, a fully passing run prints a screenful of stack traces and reads
 * like a broken build.
 *
 * Silence those two channels per test. They are still spies, so a test that
 * cares what was logged can assert on `console.error.mock.calls`.
 */
beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  vi.spyOn(console, 'warn').mockImplementation(() => {})
})

afterEach(() => {
  vi.mocked(console.error).mockRestore()
  vi.mocked(console.warn).mockRestore()
})
