import service from './index'

/** Write down a claim before reality is known. */
export const recordPrediction = (data) =>
  service.post('/api/calibration/predictions', data)

/** @param {string} [status] - 'open' or 'resolved' */
export const listPredictions = (status) =>
  service.get('/api/calibration/predictions', { params: status ? { status } : {} })

/** Record what actually happened. */
export const resolvePrediction = (predictionId, outcome, note = '') =>
  service.post(`/api/calibration/predictions/${predictionId}/outcome`,
               { outcome, note })

/** How good the predictions have actually been. */
export const getScorecard = () => service.get('/api/calibration/scorecard')
