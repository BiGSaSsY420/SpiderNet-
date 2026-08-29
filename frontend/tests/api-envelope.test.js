/**
 * The response interceptor unwraps the backend's `{success, data}` envelope.
 * `backend/tests/test_api_contract.py` asserts the server side of the same
 * contract; these two suites have to agree or every screen breaks at once.
 */
import { describe, it, expect } from 'vitest'
import service from '../src/api/index.js'

const [{ fulfilled, rejected }] = service.interceptors.response.handlers

const respond = (data) => fulfilled({ data })

describe('response envelope', () => {
  it('unwraps a successful envelope to its payload', () => {
    const body = { success: true, data: { project_id: 'proj_1' } }
    expect(respond(body)).toEqual(body)
  })

  it('rejects a failure envelope with the server error text', async () => {
    await expect(respond({ success: false, error: '项目不存在' }))
      .rejects.toThrow('项目不存在')
  })

  it('falls back to `message` when there is no `error`', async () => {
    await expect(respond({ success: false, message: 'legacy field' }))
      .rejects.toThrow('legacy field')
  })

  it('still rejects when a failure carries no explanation', async () => {
    await expect(respond({ success: false })).rejects.toThrow('请求失败')
  })

  it('passes through a body with no success key', () => {
    // Some endpoints stream raw payloads; absent means "not an envelope".
    const body = { nodes: [], edges: [] }
    expect(respond(body)).toEqual(body)
  })

  it('does not mistake success:0 for a missing key', async () => {
    await expect(respond({ success: 0, error: 'falsy but present' }))
      .rejects.toThrow('falsy but present')
  })

  it('rejects transport errors unchanged', async () => {
    const error = new Error('Network Error')
    await expect(rejected(error)).rejects.toBe(error)
  })
})

describe('axios instance', () => {
  it('allows a long timeout - ontology generation is slow', () => {
    expect(service.defaults.timeout).toBeGreaterThanOrEqual(300000)
  })

  it('sends JSON by default', () => {
    expect(service.defaults.headers['Content-Type']).toBe('application/json')
  })
})
