import { describe, it, expect } from 'vitest'
import { classifyAutomated, parseCredentials } from '../graph-mail.js'

// parseCredentials is the pure, filesystem-free core of the credentials
// loader. The network paths (token mint, Graph calls) are exercised out of
// band against the live tenant; here we pin the parsing + validation contract.
describe('parseCredentials', () => {
  const full = [
    'TENANT_ID=3a682944-ae23-4489-b5ad-d2c7840c9458',
    'CLIENT_ID=db39e644-2a24-4fc6-9690-5f75f7e6ed02',
    'CLIENT_SECRET=xy~8Q~secretvalue',
    'MAILBOX=marveen@pecibt.hu',
  ].join('\n')

  it('parses a well-formed credentials file', () => {
    const c = parseCredentials(full)
    expect(c.tenantId).toBe('3a682944-ae23-4489-b5ad-d2c7840c9458')
    expect(c.clientId).toBe('db39e644-2a24-4fc6-9690-5f75f7e6ed02')
    expect(c.clientSecret).toBe('xy~8Q~secretvalue')
    expect(c.mailbox).toBe('marveen@pecibt.hu')
  })

  it('ignores comments and blank lines', () => {
    const c = parseCredentials(`# header comment\n\n${full}\n# trailing`)
    expect(c.mailbox).toBe('marveen@pecibt.hu')
  })

  it('strips surrounding quotes from values', () => {
    const c = parseCredentials(full.replace('CLIENT_SECRET=xy~8Q~secretvalue', 'CLIENT_SECRET="xy~8Q~secretvalue"'))
    expect(c.clientSecret).toBe('xy~8Q~secretvalue')
  })

  it('keeps = characters inside a value', () => {
    const c = parseCredentials(full.replace('CLIENT_SECRET=xy~8Q~secretvalue', 'CLIENT_SECRET=ab=cd=ef'))
    expect(c.clientSecret).toBe('ab=cd=ef')
  })

  it('throws listing every missing key', () => {
    expect(() => parseCredentials('MAILBOX=marveen@pecibt.hu')).toThrowError(/TENANT_ID.*CLIENT_ID.*CLIENT_SECRET/)
  })

  it('treats an empty value as missing', () => {
    expect(() => parseCredentials(full.replace('CLIENT_SECRET=xy~8Q~secretvalue', 'CLIENT_SECRET='))).toThrowError(
      /CLIENT_SECRET/,
    )
  })
})

// classifyAutomated is the pure half of the unsubscribe-chain validation step
// (store/leiratkozas-agent/ELJARAS.md). Its whole job is to keep the chain
// from answering another robot, so the cases below pin both directions: what
// must be recognised as machine-generated, and what must NOT be, because a
// false positive silently drops a real customer's request.
describe('classifyAutomated', () => {
  const h = (...pairs: Array<[string, string]>) => pairs.map(([name, value]) => ({ name, value }))

  it('treats a plain human reply as human', () => {
    const v = classifyAutomated(
      h(['From', 'vevo@example.hu'], ['Subject', 'Leiratkozas'], ['Return-Path', '<vevo@example.hu>']),
    )
    expect(v.automated).toBe(false)
    expect(v.reasons).toEqual([])
  })

  it('flags RFC 3834 Auto-Submitted values other than "no"', () => {
    expect(classifyAutomated(h(['Auto-Submitted', 'auto-replied'])).automated).toBe(true)
    expect(classifyAutomated(h(['Auto-Submitted', 'auto-generated'])).automated).toBe(true)
  })

  it('accepts Auto-Submitted: no as human, including with parameters', () => {
    expect(classifyAutomated(h(['Auto-Submitted', 'no'])).automated).toBe(false)
    expect(classifyAutomated(h(['Auto-Submitted', 'No; owner=x'])).automated).toBe(false)
  })

  it('flags an out-of-office suppression header', () => {
    const v = classifyAutomated(h(['X-Auto-Response-Suppress', 'OOF, AutoReply']))
    expect(v.automated).toBe(true)
    expect(v.reasons[0]).toContain('X-Auto-Response-Suppress')
  })

  it('flags bulk precedence but not a normal one', () => {
    expect(classifyAutomated(h(['Precedence', 'bulk'])).automated).toBe(true)
    expect(classifyAutomated(h(['Precedence', 'auto_reply'])).automated).toBe(true)
    expect(classifyAutomated(h(['Precedence', 'normal'])).automated).toBe(false)
  })

  it('flags the null sender used by every bounce, bracketed or not', () => {
    expect(classifyAutomated(h(['Return-Path', '<>'])).automated).toBe(true)
    expect(classifyAutomated(h(['Return-Path', '< >'])).automated).toBe(true)
    // Graph strips the angle brackets (measured on the live tenant), so an
    // empty value is what a real null sender actually looks like here.
    expect(classifyAutomated(h(['Return-Path', ''])).automated).toBe(true)
    expect(classifyAutomated(h(['Return-Path', '  '])).automated).toBe(true)
  })

  it('does not flag an ordinary unbracketed Return-Path', () => {
    expect(classifyAutomated(h(['Return-Path', 'abel.kondics@pdb.hu'])).automated).toBe(false)
  })

  it('flags a delivery-status report', () => {
    expect(classifyAutomated(h(['X-Failed-Recipients', 'nincs@example.hu'])).automated).toBe(true)
    expect(
      classifyAutomated(h(['Content-Type', 'multipart/report; report-type=delivery-status; boundary=x'])).automated,
    ).toBe(true)
  })

  it('does not flag an ordinary multipart message', () => {
    expect(classifyAutomated(h(['Content-Type', 'multipart/alternative; boundary=x'])).automated).toBe(false)
  })

  it('matches header names case-insensitively, as RFC 5322 requires', () => {
    expect(classifyAutomated(h(['auto-submitted', 'AUTO-REPLIED'])).automated).toBe(true)
    expect(classifyAutomated(h(['PRECEDENCE', 'Bulk'])).automated).toBe(true)
  })

  it('collects every reason, not just the first', () => {
    const v = classifyAutomated(h(['Auto-Submitted', 'auto-replied'], ['Precedence', 'bulk'], ['Return-Path', '<>']))
    expect(v.reasons).toHaveLength(3)
  })

  it('survives an empty or malformed header list', () => {
    expect(classifyAutomated([]).automated).toBe(false)
    expect(classifyAutomated([{ name: 'X-Odd' } as never]).automated).toBe(false)
  })
})
