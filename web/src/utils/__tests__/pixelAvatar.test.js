import assert from 'node:assert/strict'
import { generatePixelAvatar } from '../pixelAvatar.js'

const decodeAvatarSvg = (avatar) => decodeURIComponent(avatar.replace('data:image/svg+xml,', ''))

const run = () => {
  {
    const first = generatePixelAvatar('user-001')
    const second = generatePixelAvatar('user-001')
    assert.equal(first, second, 'Same ID should generate the same avatar')
    console.log('T1 Stable output: PASS')
  }

  {
    const first = generatePixelAvatar('user-001')
    const second = generatePixelAvatar('user-002')
    assert.notEqual(first, second, 'Different IDs should generate different avatars')
    console.log('T2 Different IDs: PASS')
  }

  {
    const avatar = generatePixelAvatar('user-003')
    assert.ok(avatar.startsWith('data:image/svg+xml,'), 'Should return an SVG data URL')
    console.log('T3 Data URL prefix: PASS')
  }

  {
    const svg = decodeAvatarSvg(generatePixelAvatar('user-004'))
    assert.ok(svg.includes('<svg'), 'Decoded output should contain an SVG tag')
    assert.ok(svg.includes('<rect'), 'Decoded output should contain pixel rects')
    console.log('T4 Decodable SVG: PASS')
  }

  {
    assert.throws(
      () => generatePixelAvatar(''),
      /requires an id/,
      'Empty ID should be treated as invalid data'
    )
    assert.throws(
      () => generatePixelAvatar(null),
      /requires an id/,
      'Null ID should be treated as invalid data'
    )
    console.log('T5 Missing ID fails: PASS')
  }

  console.log('\nAll 5 pixel avatar tests passed!')
}

run()
