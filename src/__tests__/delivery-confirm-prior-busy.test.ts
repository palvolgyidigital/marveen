// confirmsDeliveryDespitePriorBusy: the ea2eb050 fix.
//
// Reproduced separately (2026-08-26, against the unmodified src) that
// decideSubmitFollowup returns 'done' at attempt 0 for a pane that was
// ALREADY busy before we sent anything -- with zero evidence the just-sent
// text was ever accepted. This function is the extra check the caller must
// run in exactly that ambiguous case before trusting 'done'.

import { describe, it, expect } from 'vitest'
import { confirmsDeliveryDespitePriorBusy, hasDedupCoverage } from '../pane-state.js'

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

  // WRAP826 (Pedro's review): the fleet's panes are 80 columns wide and
  // capture-pane is never called with -J, so a landed payload can still have
  // a newline spliced into the middle of it by terminal line-wrapping. A raw
  // substring search would then miss text that genuinely arrived -- exactly
  // in the ambiguous case this function exists to resolve.
  it('trusts a busy-pre-send verdict when the payload landed but got LINE-WRAPPED across an 80-col pane', () => {
    // Mirrors agent-process.ts exactly: payloadHint is oneLine.slice(0, 96).
    const oneLine = 'vesd ossze a rendelesen szereplo arakkal: 15238 -> 1.735 1 db, '
      + 'es jelezz vissza minel elobb mert David varja a valaszt surgosen ma delutan'
    const wideHint = oneLine.slice(0, 96)
    expect(wideHint.length).toBe(96)

    // Simulate a real tmux capture-pane -p (no -J): an 80-column pane wraps
    // any line longer than 80 chars onto the next terminal row, so a single
    // logical line becomes multiple array entries with '\n' where the wrap
    // happened -- splicing a newline into the middle of wideHint itself.
    const PANE_WIDTH = 80
    const fullLine = '❯ ' + wideHint
    const wrappedRows: string[] = []
    for (let i = 0; i < fullLine.length; i += PANE_WIDTH) {
      wrappedRows.push(fullLine.slice(i, i + PANE_WIDTH))
    }
    const wrappedCapture = wrappedRows.join('\n')

    // Sanity: this fixture genuinely reproduces the bug -- a naive raw
    // substring search must fail on it, or the test below would be
    // vacuous (passing regardless of whether the fix works).
    expect(wrappedRows.length).toBeGreaterThan(1)
    expect(wrappedCapture.includes(wideHint)).toBe(false)

    // The actual function, despite the wrap, must still confirm delivery.
    expect(confirmsDeliveryDespitePriorBusy(true, wrappedCapture, wideHint)).toBe(true)
  })

  it('still correctly rejects when a wrapped capture genuinely does not contain the payload', () => {
    // The wrap-tolerant comparison must not become "trust anything wrapped":
    // a busy pane showing unrelated multi-row content still fails.
    const wideHint = 'a'.repeat(96)
    const unrelatedWrapped = [BUSY_PANE_UNRELATED_TURN, '(more unrelated scrollback text)'].join('\n')
    expect(confirmsDeliveryDespitePriorBusy(true, unrelatedWrapped, wideHint)).toBe(false)
  })
})

describe('hasDedupCoverage', () => {
  it('recognises the msg_id marker wrapAgentMessageForDelivery stamps on inter-agent messages', () => {
    const text = "[Uzenet @pedro-tol -- trusted team member, msg_id:1622]: valami tartalom"
    expect(hasDedupCoverage(text)).toBe(true)
  })

  it('returns false for a scheduled-task prompt (no msg_id, not dedup-covered)', () => {
    const text = '[Utemezett feladat: heti-hirlevel] Az eredmenyt kuldd el Telegramon (chat_id: 8668856531, reply tool).'
    expect(hasDedupCoverage(text)).toBe(false)
  })

  it('returns false for a channel-inbound wrap (no msg_id, not dedup-covered)', () => {
    const text = '<channel source="plugin:telegram:telegram" chat_id="1" message_id="2" ts="2026-08-26T06:00:00.000Z">szia</channel>'
    expect(hasDedupCoverage(text)).toBe(false)
  })

  it('does not false-positive on an unrelated numeric token that merely looks similar', () => {
    expect(hasDedupCoverage('a cikkszam 1622, nem uzenet-azonosito')).toBe(false)
  })
})
