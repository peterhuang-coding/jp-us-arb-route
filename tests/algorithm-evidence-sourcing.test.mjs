import test from 'node:test';
import assert from 'node:assert/strict';
import {recent, currentExitEvidence} from '../web/sourcing-model.mjs';

const now = new Date('2026-03-02T12:00:00+08:00');

function evidence(overrides = {}) {
  return {
    channel: '得物',
    kind: 'sold',
    source_ref: 'src-1',
    code: 'ABC',
    color: 'black',
    size: 'M',
    amount_basis: 'net',
    amount_cny: 100,
    observed_at: '2026-03-02T10:00:00+08:00',
    ...overrides
  };
}

const item = {
  channel: '得物',
  code: 'ABC',
  color: 'black',
  size: 'M',
  quote: {evidence_records: [evidence()]}
};

test('recent accepts a real date within 72 hours', () => {
  assert.equal(recent('2026-02-28', now), true);
});

test('recent rejects impossible calendar dates', () => {
  assert.equal(recent('2026-02-30', now), false);
  assert.equal(recent('2026-04-31', now), false);
});

test('recent preserves leap day and timezone boundary', () => {
  assert.equal(recent('2024-02-29', new Date('2024-02-29T12:00:00+08:00')), true);
  assert.equal(recent('2026-03-02', now), true);
});

test('recent keeps exact 72 hour cutoff and rejects one millisecond later', () => {
  const boundary = new Date('2026-03-02T00:00:00+08:00');
  assert.equal(recent('2026-02-27', boundary), true);
  assert.equal(recent('2026-02-27', new Date(boundary.getTime() + 1)), false);
  assert.equal(recent('2026-02-27', now), false);
});

test('currentExitEvidence rejects impossible timezone-qualified observed_at', () => {
  const impossible = {...item, quote: {evidence_records: [evidence({observed_at: '2026-02-30T10:00:00+08:00'})]}};
  const result = currentExitEvidence(impossible, now);
  assert.equal(result.validRecords.length, 0);
  assert.equal(result.selected, null);
  for (const observed_at of ['2026-03-02T10:00:00.123456+08:00', '2026-03-02 10:00:00+08:00']) {
    const valid = {...item, quote: {evidence_records: [evidence({observed_at})]}};
    assert.notEqual(currentExitEvidence(valid, now).selected, null, observed_at);
  }
});
