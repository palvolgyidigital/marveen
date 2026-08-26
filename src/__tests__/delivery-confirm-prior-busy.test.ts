// confirmsDeliveryDespitePriorBusy: the ea2eb050 fix.
//
// Reproduced separately (2026-08-26, against the unmodified src) that
// decideSubmitFollowup returns 'done' at attempt 0 for a pane that was
// ALREADY busy before we sent anything -- with zero evidence the just-sent
// text was ever accepted. This function is the extra check the caller must
// run in exactly that ambiguous case before trusting 'done'.

import { describe, it, expect } from 'vitest'
import { confirmsDeliveryDespitePriorBusy } from '../pane-state.js'

const SEP = '─'.repeat(80)

const BUSY_PANE_UNRELATED_TURN = [
  '✢ Combobulating… (4m 12s · ↓ 8.9k tokens · thinking some more)',
  '',
  SEP,
  '❯ ',
  SEP,
  '  ⏵⏵ bypass permissions on (shift+tab to cycle) · esc to interrupt',
].join('\n')

const PAYLOAD_HINT = 'vesd ossze a rendelesen szereplo arakkal: 15238 -> 1735'

describe('confirmsDeliveryDespitePriorBusy', () => {
  it('trusts the verdict unconditionally when the pane was idle before we sent (the common, unambiguous case)', () => {
    // wasBusyPreSend=false -> no proof required, regardless of what the wider
    // capture shows (it might not even contain the hint -- irrelevant here).
    expect(confirmsDeliveryDespitePriorBusy(false, null, PAYLOAD_HINT)).toBe(true)
    expect(confirmsDeliveryDespitePriorBusy(false, 'anything or nothing', PAYLOAD_HINT)).toBe(true)
  })

  it('does NOT trust a busy-pre-send verdict when the payload is nowhere in the wider capture', () => {
    expect(confirmsDeliveryDespitePriorBusy(true, BUSY_PANE_UNRELATED_TURN, PAYLOAD_HINT)).toBe(false)
  })

  it('does NOT trust when the wider capture could not be taken at all (null)', () => {
    expect(confirmsDeliveryDespitePriorBusy(true, null, PAYLOAD_HINT)).toBe(false)
  })

  it('trusts a busy-pre-send verdict once the payload hint is actually found in the wider capture', () => {
    const paneWithHistoryShowingOurText = [
      '(scrollback) ❯ ' + PAYLOAD_HINT,
      BUSY_PANE_UNRELATED_TURN,
    ].join('\n')
    expect(confirmsDeliveryDespitePriorBusy(true, paneWithHistoryShowingOurText, PAYLOAD_HINT)).toBe(true)
  })

  it('never trusts on an empty payload hint, even if busy-pre-send is false is not the case', () => {
    // Defends against a caller accidentally passing an empty hint (e.g. a
    // zero-length oneLine) and getting a free pass via String.includes('').
    expect(confirmsDeliveryDespitePriorBusy(true, BUSY_PANE_UNRELATED_TURN, '')).toBe(false)
  })
})
