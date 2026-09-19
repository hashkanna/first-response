import { describe, expect, it } from 'vitest'
import type { FixCandidate, IncidentUpdate, VerifyResult } from './contracts'
import { createInitialState, elapsedMs, getVerifiedCandidates, parseIncidentUpdate, reduceIncident } from './incident'
import badConfig from '../../public/sample_events.json'
import nullError from '../../public/sample_null_events.json'

const time = (second: number) => new Date(Date.UTC(2026, 8, 19, 14, 2, second)).toISOString()
const event = (overrides: Partial<IncidentUpdate> = {}): IncidentUpdate => ({ incident_id: 'inc-1', stage: 'alerted', at: time(0), message: 'Checkout is failing.', ...overrides })
const candidate: FixCandidate = { candidate_id: 'fix-1', title: 'Restore timeout', rationale: 'Restore the known value.', patch: '-3\n+3000', files_touched: ['config.py'] }
const passed: VerifyResult = { candidate_id: 'fix-1', applied: true, repro_passed: true, suite_passed: true, tests_run: 24, tests_failed: 0, duration_s: 12.1, log_tail: '24 passed' }
const evidence = { evidence_id: 'trace-1', kind: 'trace' as const, summary: 'Timeout', detail: 'TimeoutError', source_ref: 'trace-1' }
const apply = (...events: IncidentUpdate[]) => events.reduce(reduceIncident, createInitialState())

describe('untrusted IncidentUpdate parsing', () => {
  it('accepts a minimal event and supplies Pydantic list defaults', () => {
    expect(parseIncidentUpdate(event())).toMatchObject({ evidence: [], candidates: [], results: [], root_cause: null, pr_url: null })
  })
  it('rejects missing required fields, empty IDs, and unknown stages', () => {
    expect(parseIncidentUpdate({})).toBeNull()
    expect(parseIncidentUpdate(event({ incident_id: ' ' }))).toBeNull()
    expect(parseIncidentUpdate({ ...event(), stage: 'victory' })).toBeNull()
    expect(parseIncidentUpdate({ ...event(), message: null })).toBeNull()
  })
  it('requires an ISO datetime with an explicit timezone', () => {
    for (const at of ['yesterday', '2026-09-19', '2026-09-19T14:02:00', 123, null]) expect(parseIncidentUpdate({ ...event(), at })).toBeNull()
    expect(parseIncidentUpdate(event({ at: '2026-09-19T15:02:00+01:00' }))).not.toBeNull()
  })
  it('rejects invalid nested evidence instead of dropping it silently', () => {
    expect(parseIncidentUpdate({ ...event(), evidence: [evidence, { evidence_id: 'bad' }] })).toBeNull()
    expect(parseIncidentUpdate({ ...event(), evidence: null })).toBeNull()
  })
  it('rejects invalid causes and non-finite confidence values', () => {
    const cause = { service: 'payments', file: 'config.py', explanation: 'Bad timeout.', evidence_ids: [], confidence: .9 }
    expect(parseIncidentUpdate({ ...event(), root_cause: cause })).not.toBeNull()
    for (const confidence of [-.1, 1.1, NaN, Infinity]) expect(parseIncidentUpdate({ ...event(), root_cause: { ...cause, confidence } })).toBeNull()
  })
  it('rejects malformed candidates and verification results', () => {
    expect(parseIncidentUpdate({ ...event(), candidates: [{ ...candidate, files_touched: 'config.py' }] })).toBeNull()
    for (const result of [{ ...passed, applied: 'true' }, { ...passed, tests_failed: 25 }, { ...passed, tests_run: -1 }, { ...passed, duration_s: Infinity }]) expect(parseIncidentUpdate({ ...event(), results: [result] })).toBeNull()
  })
  it('retains generated provenance and rejects malformed snapshot bindings', () => {
    const generated = { ...candidate, origin: 'gemini', snapshot_sha: 'a'.repeat(64) }
    expect(parseIncidentUpdate({ ...event(), candidates: [generated] })?.candidates?.[0]).toEqual(generated)
    for (const invalid of [{ ...generated, origin: 'verified' }, { ...generated, snapshot_sha: 'not-a-hash' }]) {
      expect(parseIncidentUpdate({ ...event(), candidates: [invalid] })).toBeNull()
    }
  })
  it('permits only HTTP or HTTPS pull request links', () => {
    expect(parseIncidentUpdate(event({ pr_url: 'https://github.com/example/shop/pull/1' }))).not.toBeNull()
    expect(parseIncidentUpdate(event({ pr_url: 'javascript:alert(1)' }))).toBeNull()
    expect(parseIncidentUpdate(event({ pr_url: 'file:///etc/passwd' }))).toBeNull()
  })
  it('ignores unknown top-level extension fields', () => {
    const parsed = parseIncidentUpdate({ ...event(), metadata: { fixture: true } })
    expect(parsed).not.toBeNull()
    expect(parsed).not.toHaveProperty('metadata')
  })
})

describe('incident state', () => {
  it('starts empty, with independent arrays for each initial state', () => {
    const a = createInitialState(), b = createInitialState()
    a.evidence.push(evidence)
    expect(b.evidence).toEqual([])
    expect(b.incidentId).toBeNull()
    expect(elapsedMs(b, 123)).toBe(0)
  })
  it('preserves evidence and candidates when later partial updates omit them', () => {
    const state = apply(event({ evidence: [evidence], candidates: [candidate] }), event({ stage: 'investigating', at: time(3) }))
    expect(state.evidence).toEqual([evidence])
    expect(state.candidates).toEqual([candidate])
  })
  it('merges evidence, candidates, and results by their IDs', () => {
    const state = apply(event({ evidence: [evidence], candidates: [candidate], results: [{ ...passed, suite_passed: false }] }), event({ at: time(2), evidence: [{ ...evidence, detail: 'New trace' }], candidates: [{ ...candidate, title: 'New title' }], results: [passed] }))
    expect(state.evidence).toHaveLength(1)
    expect(state.evidence[0].detail).toBe('New trace')
    expect(state.candidates).toHaveLength(1)
    expect(state.candidates[0].title).toBe('New title')
    expect(state.results).toEqual([passed])
  })
  it('deduplicates retransmitted events and returns the same state reference', () => {
    const first = event({ evidence: [evidence] }), state = apply(first)
    expect(reduceIncident(state, first)).toBe(state)
    expect(state.updates).toHaveLength(1)
  })
  it('retains the previous state for invalid input', () => {
    const state = apply(event())
    expect(reduceIncident(state, { ...event(), stage: 'bad' } as unknown as IncidentUpdate)).toBe(state)
  })
  it('ignores events belonging to another incident without an alert boundary', () => {
    const state = apply(event())
    expect(reduceIncident(state, event({ incident_id: 'inc-2', stage: 'fix_verified', at: time(10), results: [passed] }))).toBe(state)
  })
  it('resets all incident data on a newer incident alert', () => {
    const state = apply(event({ evidence: [evidence], candidates: [candidate], results: [passed] }), event({ incident_id: 'inc-2', at: time(20) }))
    expect(state.incidentId).toBe('inc-2')
    expect(state.evidence).toEqual([])
    expect(state.candidates).toEqual([])
    expect(state.results).toEqual([])
    expect(state.updates).toHaveLength(1)
  })
  it('rejects delayed alerts and retired incident IDs, even with a newer timestamp', () => {
    const state = apply(event(), event({ incident_id: 'inc-2', at: time(20) }))
    expect(reduceIncident(state, event({ at: time(40) }))).toBe(state)
    expect(reduceIncident(state, event({ incident_id: 'inc-3', at: time(10) }))).toBe(state)
  })
  it('does not let out-of-order entities overwrite newer facts', () => {
    const state = apply(event(), event({ stage: 'verifying', at: time(20), evidence: [{ ...evidence, detail: 'new' }], candidates: [candidate], results: [passed] }), event({ stage: 'investigating', at: time(10), evidence: [evidence], results: [{ ...passed, suite_passed: false }] }))
    expect(state.stage).toBe('verifying')
    expect(state.evidence[0].detail).toBe('new')
    expect(state.results).toEqual([passed])
    expect(state.updates.map(update => update.at)).toEqual([time(0), time(10), time(20)])
  })
  it('does not regress a stage on a later progress message', () => {
    const state = apply(event(), event({ stage: 'cause_found', at: time(10) }), event({ stage: 'investigating', at: time(20) }))
    expect(state.stage).toBe('cause_found')
  })
  it('keeps root cause and PR link when later events omit or null them', () => {
    const cause = { service: 'payments' as const, file: 'config.py', explanation: 'Bad setting.', evidence_ids: [], confidence: .95 }
    const state = apply(event({ root_cause: cause, pr_url: 'https://github.com/example/shop/pull/1' }), event({ at: time(10), root_cause: null, pr_url: null }))
    expect(state.rootCause).toEqual(cause)
    expect(state.prUrl).toBe('https://github.com/example/shop/pull/1')
  })
  it('requires applied, reproduction, and suite success for an existing candidate', () => {
    for (const field of ['applied', 'repro_passed', 'suite_passed'] as const) {
      expect(getVerifiedCandidates(apply(event({ candidates: [candidate], results: [{ ...passed, [field]: false }] })))).toEqual([])
    }
    expect(getVerifiedCandidates(apply(event({ results: [passed] })))).toEqual([])
    expect(getVerifiedCandidates(apply(event({ candidates: [candidate], results: [passed] })))).toEqual([candidate])
  })
  it('does not accept a completion message as proof of verification', () => {
    const state = apply(event(), event({ stage: 'verifying', at: time(10), candidates: [candidate] }), event({ stage: 'fix_verified', at: time(20) }))
    expect(state.stage).toBe('verifying')
    expect(state.verifiedAt).toBeNull()
    expect(elapsedMs(state, Date.parse(time(30)))).toBe(30_000)
  })
  it('rejects a passing claim with no executed tests or reported failures', () => {
    for (const result of [{ ...passed, tests_run: 0 }, { ...passed, tests_failed: 1 }]) {
      const state = apply(event(), event({ stage: 'verifying', at: time(10), candidates: [candidate] }), event({ stage: 'fix_verified', at: time(20), results: [result] }))
      expect(getVerifiedCandidates(state)).toEqual([])
      expect(state.stage).toBe('verifying')
      expect(state.verifiedAt).toBeNull()
      expect(elapsedMs(state, Date.parse(time(30)))).toBe(30_000)
    }
  })
  it('withdraws verification if a later result contradicts the successful count', () => {
    const state = apply(event(), event({ stage: 'fix_verified', at: time(20), candidates: [candidate], results: [passed] }), event({ stage: 'verifying', at: time(30), results: [{ ...passed, tests_failed: 1 }] }))
    expect(getVerifiedCandidates(state)).toEqual([])
    expect(state.stage).toBe('verifying')
    expect(state.verifiedAt).toBeNull()
  })
  it('runs the alert timer, clamps clock skew, and freezes only at verified completion', () => {
    const start = apply(event())
    expect(elapsedMs(start, Date.parse(time(12)))).toBe(12_000)
    expect(elapsedMs(start, Date.parse(time(-1)))).toBe(0)
    const done = reduceIncident(start, event({ stage: 'fix_verified', at: time(24), candidates: [candidate], results: [passed] }))
    expect(elapsedMs(done, Date.parse(time(100)))).toBe(24_000)
    const opened = reduceIncident(done, event({ stage: 'pr_opened', at: time(40), pr_url: 'https://github.com/example/shop/pull/1' }))
    expect(elapsedMs(opened, Date.parse(time(110)))).toBe(24_000)
  })
  it('handles failure outcomes without inventing a verified candidate', () => {
    const state = apply(event(), event({ stage: 'no_fix_found', at: time(30), candidates: [candidate], results: [{ ...passed, repro_passed: false, suite_passed: false, tests_failed: 2 }] }))
    expect(state.stage).toBe('no_fix_found')
    expect(state.verifiedAt).toBeNull()
    expect(getVerifiedCandidates(state)).toEqual([])
  })
  it('replays both recorded fault scenarios with exactly one passing 24-test candidate', () => {
    for (const fixture of [badConfig, nullError]) {
      const events = fixture.map(parseIncidentUpdate)
      expect(events.every(Boolean)).toBe(true)
      const state = apply(...events as IncidentUpdate[])
      expect(state.stage).toBe('fix_verified')
      expect(state.candidates).toHaveLength(3)
      expect(state.results).toHaveLength(3)
      expect(getVerifiedCandidates(state)).toHaveLength(1)
      expect(state.results.every(result => result.tests_run === 24)).toBe(true)
      expect(state.prUrl).toBeNull()
      expect(elapsedMs(state)).toBeGreaterThan(0)
      expect(state.updates[0].message).toContain('Recorded scenario')
    }
  })
})
