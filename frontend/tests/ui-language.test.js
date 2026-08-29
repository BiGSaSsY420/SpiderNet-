import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const CJK = /[一-鿿]/

function vueFiles (dir, found = []) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) vueFiles(path, found)
    else if (entry.endsWith('.vue')) found.push(path)
  }
  return found
}

/** Everything before <script> is what a user actually sees. */
function templateOf (source) {
  const i = source.indexOf('<script')
  return i === -1 ? source : source.slice(0, i)
}

describe('the interface is in English', () => {
  const files = vueFiles(new URL('../src', import.meta.url).pathname)

  it('finds the components to check', () => {
    expect(files.length).toBeGreaterThan(5)
  })

  it.each(files)('%s renders no Chinese text', (file) => {
    const template = templateOf(readFileSync(file, 'utf8'))

    const offending = template
      .split('\n')
      .map((line, n) => [n + 1, line])
      // Comments are internal; only rendered text matters here.
      .filter(([, line]) => CJK.test(line) && !line.trim().startsWith('<!--'))
      .map(([n, line]) => `  line ${n}: ${line.trim().slice(0, 90)}`)

    expect(offending.join('\n')).toBe('')
  })
})
