import service from './index'

/**
 * Where to get the source of the running version.
 *
 * Public and unauthenticated: AGPL section 13 owes this to everyone using the
 * software over a network, not only to customers.
 */
export const getSource = () => service.get('/api/legal/source')
