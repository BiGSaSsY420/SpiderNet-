/**
 * The API client modules are the frontend half of the backend's route table.
 * A typo in a URL or a query-parameter name fails only at runtime, in a screen
 * that may take a full simulation run to reach - so pin them here.
 *
 * These tests also assert *which* calls go through `requestWithRetry`: retrying
 * a non-idempotent POST is what produced duplicate simulations before.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

const service = vi.fn(() => Promise.resolve({ success: true }))
service.get = vi.fn(() => Promise.resolve({ success: true }))
service.post = vi.fn(() => Promise.resolve({ success: true }))

const requestWithRetry = vi.fn((fn) => fn())

vi.mock('../src/api/index.js', () => ({
  default: service,
  requestWithRetry: (...args) => requestWithRetry(...args),
  isRetryableError: () => false
}))

const graph = await import('../src/api/graph.js')
const report = await import('../src/api/report.js')
const simulation = await import('../src/api/simulation.js')

beforeEach(() => {
  service.mockClear()
  service.get.mockClear()
  service.post.mockClear()
  requestWithRetry.mockClear()
})

/** The (url, config) pair of the single GET this call made. */
const lastGet = () => service.get.mock.calls.at(-1)
const lastPost = () => service.post.mock.calls.at(-1)

describe('graph API', () => {
  it('posts ontology generation as multipart', async () => {
    const formData = new FormData()
    await graph.generateOntology(formData)

    const [config] = service.mock.calls.at(-1)
    expect(config.url).toBe('/api/graph/ontology/generate')
    expect(config.method).toBe('post')
    expect(config.data).toBe(formData)
    expect(config.headers['Content-Type']).toBe('multipart/form-data')
  })

  it('posts the graph build request', async () => {
    await graph.buildGraph({ project_id: 'proj_1', chunk_size: 500 })

    const [config] = service.mock.calls.at(-1)
    expect(config.url).toBe('/api/graph/build')
    expect(config.method).toBe('post')
    expect(config.data).toEqual({ project_id: 'proj_1', chunk_size: 500 })
  })

  it('reads a task, a graph and a project by id', async () => {
    await graph.getTaskStatus('task_1')
    expect(service.mock.calls.at(-1)[0].url).toBe('/api/graph/task/task_1')

    await graph.getGraphData('graph_1')
    expect(service.mock.calls.at(-1)[0].url).toBe('/api/graph/data/graph_1')

    await graph.getProject('proj_1')
    expect(service.mock.calls.at(-1)[0].url).toBe('/api/graph/project/proj_1')
  })

  it('retries only the two long-running creates', async () => {
    await graph.generateOntology(new FormData())
    await graph.buildGraph({})
    expect(requestWithRetry).toHaveBeenCalledTimes(2)

    requestWithRetry.mockClear()
    await graph.getTaskStatus('task_1')
    await graph.getGraphData('graph_1')
    await graph.getProject('proj_1')
    expect(requestWithRetry).not.toHaveBeenCalled()
  })
})

describe('report API', () => {
  it('starts generation and passes the body through', async () => {
    await report.generateReport({ simulation_id: 'sim_1', force_regenerate: true })

    expect(lastPost()[0]).toBe('/api/report/generate')
    expect(lastPost()[1]).toEqual({ simulation_id: 'sim_1', force_regenerate: true })
    expect(requestWithRetry).toHaveBeenCalledTimes(1)
  })

  it('queries status by report_id query parameter', async () => {
    await report.getReportStatus('report_1')

    expect(lastGet()[0]).toBe('/api/report/generate/status')
    expect(lastGet()[1].params).toEqual({ report_id: 'report_1' })
  })

  it('reads logs incrementally from a line offset', async () => {
    await report.getAgentLog('report_1', 42)
    expect(lastGet()[0]).toBe('/api/report/report_1/agent-log')
    expect(lastGet()[1].params).toEqual({ from_line: 42 })

    await report.getConsoleLog('report_1', 7)
    expect(lastGet()[0]).toBe('/api/report/report_1/console-log')
    expect(lastGet()[1].params).toEqual({ from_line: 7 })
  })

  it('starts log reads at line 0 by default', async () => {
    await report.getAgentLog('report_1')
    expect(lastGet()[1].params).toEqual({ from_line: 0 })

    await report.getConsoleLog('report_1')
    expect(lastGet()[1].params).toEqual({ from_line: 0 })
  })

  it('fetches a finished report', async () => {
    await report.getReport('report_1')
    expect(lastGet()[0]).toBe('/api/report/report_1')
  })

  it('retries the chat turn', async () => {
    await report.chatWithReport({ simulation_id: 'sim_1', message: 'hi' })

    expect(lastPost()[0]).toBe('/api/report/chat')
    expect(requestWithRetry).toHaveBeenCalledTimes(1)
  })
})

describe('simulation API', () => {
  it('routes the lifecycle POSTs', async () => {
    await simulation.createSimulation({ project_id: 'proj_1' })
    expect(lastPost()[0]).toBe('/api/simulation/create')

    await simulation.prepareSimulation({ simulation_id: 'sim_1' })
    expect(lastPost()[0]).toBe('/api/simulation/prepare')

    await simulation.getPrepareStatus({ task_id: 'task_1' })
    expect(lastPost()[0]).toBe('/api/simulation/prepare/status')

    await simulation.startSimulation({ simulation_id: 'sim_1' })
    expect(lastPost()[0]).toBe('/api/simulation/start')

    await simulation.stopSimulation({ simulation_id: 'sim_1' })
    expect(lastPost()[0]).toBe('/api/simulation/stop')

    await simulation.closeSimulationEnv({ simulation_id: 'sim_1' })
    expect(lastPost()[0]).toBe('/api/simulation/close-env')

    await simulation.getEnvStatus({ simulation_id: 'sim_1' })
    expect(lastPost()[0]).toBe('/api/simulation/env-status')

    await simulation.interviewAgents({ simulation_id: 'sim_1', interviews: [] })
    expect(lastPost()[0]).toBe('/api/simulation/interview/batch')
  })

  it('retries create, prepare, start and interview - and nothing else', async () => {
    await simulation.createSimulation({})
    await simulation.prepareSimulation({})
    await simulation.startSimulation({})
    await simulation.interviewAgents({})
    expect(requestWithRetry).toHaveBeenCalledTimes(4)

    requestWithRetry.mockClear()
    await simulation.stopSimulation({})
    await simulation.getPrepareStatus({})
    await simulation.closeSimulationEnv({})
    await simulation.getEnvStatus({})
    expect(requestWithRetry).not.toHaveBeenCalled()
  })

  it('reads a simulation and its config', async () => {
    await simulation.getSimulation('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1')

    await simulation.getSimulationConfig('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/config')

    await simulation.getSimulationConfigRealtime('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/config/realtime')
  })

  it('defaults the profile platform to reddit', async () => {
    await simulation.getSimulationProfiles('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/profiles')
    expect(lastGet()[1].params).toEqual({ platform: 'reddit' })

    await simulation.getSimulationProfilesRealtime('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/profiles/realtime')
    expect(lastGet()[1].params).toEqual({ platform: 'reddit' })
  })

  it('passes an explicit platform through', async () => {
    await simulation.getSimulationProfiles('sim_1', 'twitter')
    expect(lastGet()[1].params).toEqual({ platform: 'twitter' })

    await simulation.getSimulationProfilesRealtime('sim_1', 'twitter')
    expect(lastGet()[1].params).toEqual({ platform: 'twitter' })
  })

  it('omits the project filter when listing everything', async () => {
    await simulation.listSimulations()
    expect(lastGet()[0]).toBe('/api/simulation/list')
    expect(lastGet()[1].params).toEqual({})

    await simulation.listSimulations('proj_1')
    expect(lastGet()[1].params).toEqual({ project_id: 'proj_1' })
  })

  it('reads run status at both levels of detail', async () => {
    await simulation.getRunStatus('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/run-status')

    await simulation.getRunStatusDetail('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/run-status/detail')
  })

  it('pages through posts with defaults', async () => {
    await simulation.getSimulationPosts('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/posts')
    expect(lastGet()[1].params).toEqual({ platform: 'reddit', limit: 50, offset: 0 })

    await simulation.getSimulationPosts('sim_1', 'twitter', 10, 20)
    expect(lastGet()[1].params).toEqual({ platform: 'twitter', limit: 10, offset: 20 })
  })

  it('omits end_round unless the caller bounds the timeline', async () => {
    await simulation.getSimulationTimeline('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/timeline')
    expect(lastGet()[1].params).toEqual({ start_round: 0 })

    await simulation.getSimulationTimeline('sim_1', 3, 9)
    expect(lastGet()[1].params).toEqual({ start_round: 3, end_round: 9 })
  })

  it('does not drop a zero end_round', async () => {
    await simulation.getSimulationTimeline('sim_1', 0, 0)
    expect(lastGet()[1].params).toEqual({ start_round: 0, end_round: 0 })
  })

  it('reads agent stats and the action history', async () => {
    await simulation.getAgentStats('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/agent-stats')

    await simulation.getSimulationActions('sim_1')
    expect(lastGet()[0]).toBe('/api/simulation/sim_1/actions')
    expect(lastGet()[1].params).toEqual({})

    await simulation.getSimulationActions('sim_1', { limit: 5, round_num: 2 })
    expect(lastGet()[1].params).toEqual({ limit: 5, round_num: 2 })
  })

  it('defaults the history page size', async () => {
    await simulation.getSimulationHistory()
    expect(lastGet()[0]).toBe('/api/simulation/history')
    expect(lastGet()[1].params).toEqual({ limit: 20 })

    await simulation.getSimulationHistory(5)
    expect(lastGet()[1].params).toEqual({ limit: 5 })
  })
})
