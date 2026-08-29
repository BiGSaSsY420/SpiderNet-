/**
 * The home screen hands files to this store and navigates away immediately;
 * the process screen picks them up and uploads them. Anything dropped here is
 * a silently empty run.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import state, {
  setPendingUpload,
  getPendingUpload,
  clearPendingUpload
} from '../src/store/pendingUpload.js'

beforeEach(() => clearPendingUpload())

describe('pendingUpload', () => {
  it('starts out empty and not pending', () => {
    expect(getPendingUpload()).toEqual({
      files: [],
      simulationRequirement: '',
      isPending: false
    })
  })

  it('hands back what was handed in', () => {
    const files = [new File(['seed'], 'seed.txt')]
    setPendingUpload(files, '推演舆情走向')

    expect(getPendingUpload()).toEqual({
      files,
      simulationRequirement: '推演舆情走向',
      isPending: true
    })
  })

  it('marks itself pending so the next screen knows to consume it', () => {
    setPendingUpload([], '')
    expect(getPendingUpload().isPending).toBe(true)
  })

  it('clears back to the empty state after the upload is consumed', () => {
    setPendingUpload([new File(['x'], 'x.txt')], 'requirement')
    clearPendingUpload()

    expect(getPendingUpload()).toEqual({
      files: [],
      simulationRequirement: '',
      isPending: false
    })
  })

  it('replaces the previous upload rather than appending to it', () => {
    setPendingUpload([new File(['a'], 'a.txt')], 'first')
    setPendingUpload([new File(['b'], 'b.txt')], 'second')

    const { files, simulationRequirement } = getPendingUpload()
    expect(files).toHaveLength(1)
    expect(files[0].name).toBe('b.txt')
    expect(simulationRequirement).toBe('second')
  })

  it('is reactive, so a component reading it re-renders', () => {
    setPendingUpload([new File(['x'], 'x.txt')], 'requirement')
    expect(state.isPending).toBe(true)
    expect(state.simulationRequirement).toBe('requirement')
  })
})
