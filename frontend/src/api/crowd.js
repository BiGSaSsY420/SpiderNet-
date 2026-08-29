import service from './index'

/** Crowds you own, plus the shared library. Free to call. */
export const listCrowds = () => service.get('/api/crowds')

export const getCrowd = (crowdId) => service.get(`/api/crowds/${crowdId}`)

/** Save the people from a finished run so they can be asked things later. */
export const captureCrowd = (data) =>
  service.post('/api/crowds/from-simulation', data)

/**
 * Ask a crowd a question.
 * @param {string} crowdId
 * @param {Object} data - { question, sample_size? }
 */
export const askCrowd = (crowdId, data) =>
  service.post(`/api/crowds/${crowdId}/ask`, data)

export const deleteCrowd = (crowdId) => service.delete(`/api/crowds/${crowdId}`)
