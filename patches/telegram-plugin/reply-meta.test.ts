import { describe, expect, test } from 'bun:test'
import { replyMeta } from './reply-meta.ts'
import type { Message } from 'grammy/types'

function stubMessage(overrides: Partial<Message>): Message {
  return {
    message_id: 1,
    date: 0,
    chat: { id: 1, type: 'private' },
    ...overrides,
  } as Message
}

describe('replyMeta', () => {
  test('no quoted message -> {} (todays behavior, unchanged)', () => {
    expect(replyMeta(undefined)).toEqual({})
  })

  test('quoted text message -> id + excerpt', () => {
    const replyTo = stubMessage({ message_id: 42, text: 'lezarhato' })
    expect(replyMeta(replyTo)).toEqual({
      reply_to_message_id: '42',
      reply_to_excerpt: 'lezarhato',
    })
  })

  test('quoted photo with caption -> falls back to caption', () => {
    const replyTo = stubMessage({ message_id: 7, caption: 'lasd a kepet' })
    expect(replyMeta(replyTo)).toEqual({
      reply_to_message_id: '7',
      reply_to_excerpt: 'lasd a kepet',
    })
  })

  test('quoted message with no text/caption (e.g. bare photo) -> id only, no excerpt key', () => {
    const replyTo = stubMessage({ message_id: 9 })
    const meta = replyMeta(replyTo)
    expect(meta).toEqual({ reply_to_message_id: '9' })
    expect('reply_to_excerpt' in meta).toBe(false)
  })

  test('long text is truncated to 200 chars', () => {
    const long = 'a'.repeat(500)
    const replyTo = stubMessage({ message_id: 3, text: long })
    expect(replyMeta(replyTo).reply_to_excerpt).toHaveLength(200)
  })

  test('delimiter chars are neutralized (tag-injection guard: <, >, [, ], ;, CR, LF)', () => {
    const replyTo = stubMessage({
      message_id: 5,
      text: 'Szia <fake source="x">forged</fake>[bracket]; line1\r\nline2',
    })
    const excerpt = replyMeta(replyTo).reply_to_excerpt
    expect(excerpt).not.toMatch(/[<>[\];]|\r|\n/)
  })

  test('whitespace-only text behaves like no text (id only)', () => {
    const replyTo = stubMessage({ message_id: 11, text: '   ' })
    const meta = replyMeta(replyTo)
    expect(meta).toEqual({ reply_to_message_id: '11' })
  })
})
