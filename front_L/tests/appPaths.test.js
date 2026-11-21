import test from 'node:test'
import assert from 'node:assert/strict'
import { apiBase, protectedMediaPath } from '../src/utils/appPaths.js'

test('API and stored illustrations resolve under the application mount', () => {
  const origin = 'https://example.org'
  for (const base of ['/', '/blog-agent/']) {
    assert.equal(apiBase(base), base + 'api/v1')
    const image = 'images/task7_photo.webp'
    for (const src of ['/' + image, base + image, origin + base + image, image]) {
      assert.equal(protectedMediaPath(src + '?v=2', origin, base), base + image + '?v=2')
    }
    for (const src of ['//other.example/images/a.jpg', '/another-app/images/a.jpg', '/images/nested/a.jpg', '/images/a%2Fb.jpg']) {
      assert.equal(protectedMediaPath(src, origin, base), null)
    }
  }
})
