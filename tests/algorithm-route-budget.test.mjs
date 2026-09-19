// Partial Coding Plan draft adopted after review: nine fully emitted, schema-valid
// fixtures with unique optima; all shops share a location and wide time windows.
// This checks budget selection and membership, not route ordering or live travel.
import test from 'node:test';
import assert from 'node:assert/strict';
import { planDay, defaultSettings } from '../web/tokyo-planner.mjs';

const now = new Date('2026-10-02T08:00:00+09:00');
const places = [
  { id: 'base', name: '起点', lat: 35.68, lng: 139.76, open: '00:00', close: '23:59' },
  { id: 'a', name: '店 A', lat: 35.68, lng: 139.76, open: '00:00', close: '23:59' },
  { id: 'b', name: '店 B', lat: 35.68, lng: 139.76, open: '00:00', close: '23:59' }
];
const settings = () => ({ ...defaultSettings(), date: '2026-10-02', start: places[0], end: places[0], extra_cny: 0, limit_cny: 7000, travel: {} });
const item = (id, place, cost, net, units = 1) => ({
  id, name: id, code: id, color: '黑', size: '27',
  source_url: 'https://example.com/' + id, source_name: place, channel: '得物',
  quote: {
    buy_jpy: cost * 20, fx: .05, extra_cny: 0, net_cny: net, target_profit: 1, units,
    checked_at: '2026-10-02', evidence_at: '2026-10-02', evidence_kind: 'sold', evidence: '旧摘要',
    evidence_records: [{ id: 'ev-' + id, kind: 'sold', channel: '得物', amount_cny: net, amount_basis: 'net', fees_cny: null, observed_at: '2026-10-02T06:00:00+08:00', source_ref: '测试成交', source_url: 'https://example.com/evidence/' + id, note: '', code: id, color: '黑', size: '27' }],
    stock: true, delivery: true, tax: true, seller: true
  },
  visit: { place_id: place, mode: 'store', duration_min: 30 }
});
const day = (date, records = [], extra_cny = 0) => ({ date, start: places[0], end: places[0], start_time: '10:00', end_time: '18:00', records, extra_cny });
const bought = (item_id, units, cost, net = cost + 100) => ({ item_id, units, status: 'bought', cost_cny: cost, actual_net_cny: net });
const skipped = (item_id) => ({ item_id, units: 0, status: 'skipped', cost_cny: 0 });
const plan = (items, s = settings(), days = [], mode = 'buy') => planDay(items, s, days, places, mode, now);
const subsetCount = n => 1 << n;
const maskItems = (items, mask) => items.filter((_, i) => mask & (1 << i));
const subsetCost = xs => xs.reduce((sum, x) => sum + x.cost * x.units, 0);
const subsetScore = (xs, extra) => xs.reduce((sum, x) => sum + (x.net - x.cost) * x.units, 0) - extra;

function oracle(items, s, days) {
  const records = [s, ...days].flatMap(d => d.records.filter(r => r.status === 'bought'));
  const spent = records.reduce((n, r) => n + r.cost_cny, 0) + [s, ...days].reduce((n, d) => n + (d.extra_cny || 0), 0);
  const closed = new Set((s.records || []).map(r => r.item_id));
  const available = [];
  for (const original of items) {
    if (closed.has(original.id)) continue;
    const already = records.filter(r => r.item_id === original.id).reduce((n, r) => n + r.units, 0);
    const units = Math.max(0, original.quote.units - already);
    if (units > 0) available.push({ id: original.id, cost: original.quote.buy_jpy * original.quote.fx + original.quote.extra_cny, net: original.quote.net_cny, units });
  }
  const cashCap = 7000 - spent;
  const todayCap = Math.max(0, s.limit_cny - (s.records || []).filter(r => r.status === 'bought').reduce((n, r) => n + r.cost_cny, 0) - (s.extra_cny || 0));
  const candidates = [];
  for (let mask = 1; mask < subsetCount(available.length); mask++) {
    const xs = maskItems(available, mask);
    const purchase = subsetCost(xs);
    if (purchase <= cashCap + 1e-6 && purchase <= todayCap + 1e-6) {
      const score = subsetScore(xs, s.extra_cny || 0);
      if (score > 0) candidates.push({ ids: xs.map(x => x.id).sort(), score, purchase, remaining: new Map(available.map(x => [x.id, x.units])) });
    }
  }
  if (!candidates.length) return { ids: [], score: 0, purchase: 0, remaining: new Map(available.map(x => [x.id, x.units])) };
  let best = candidates[0];
  for (const candidate of candidates.slice(1)) if (candidate.score > best.score) best = candidate;
  return best;
}

function assertPlanCase(items, s = settings(), days = []) {
  const result = plan(items.map(x => x.selected === undefined ? { ...x, selected: true } : x), s, days);
  const expected = oracle(items, s, days);
  const selectedIds = result.items.map(i => i.id).sort();
  assert.deepEqual(selectedIds, expected.ids);
  assert.equal(Math.round(result.forecast.plannedCost), Math.round(expected.purchase));
  assert.equal(Math.round(result.forecast.remaining), Math.round(7000 - ([s, ...days].flatMap(d => d.records.filter(r => r.status === 'bought')).reduce((n, r) => n + r.cost_cny, 0) + [s, ...days].reduce((n, d) => n + (d.extra_cny || 0), 0)) - expected.purchase));
  const byId = new Map(result.items.map(i => [i.id, i]));
  for (const [id, units] of expected.remaining) assert.equal((byId.get(id)?.quote.units) ?? 0, selectedIds.includes(id) ? units : 0);
  for (const stop of result.route.stops) {
    assert.equal(stop.items.every(i => i.selected === true), true);
    assert.deepEqual(stop.items.map(i => i.id).sort(), stop.items.map(i => i.id).filter(id => selectedIds.includes(id)).sort());
  }
}

const cases = [
  () => assertPlanCase([item('p100', 'a', 100, 300), item('p40', 'b', 40, 80)]),
  () => assertPlanCase([item('zero', 'a', 100, 200)], {...settings(), extra_cny: 100}),
  () => assertPlanCase([item('neg', 'a', 300, 250), item('small', 'b', 20, 30)]),
  () => assertPlanCase([item('bulk', 'a', 100, 120, 5), item('one', 'b', 100, 500)]),
  () => assertPlanCase([item('cash7000', 'a', 1000, 1100, 7)]),
  () => assertPlanCase([item('cash7001', 'a', 7001, 8000)]),
  () => assertPlanCase([item('today6000', 'a', 1000, 1001, 6), item('today1000', 'b', 1000, 1500)], {...settings(), records: [bought('done', 1, 6000)]}),
  () => assertPlanCase([item('todayExtra500', 'a', 1000, 1200, 6), item('other', 'b', 500, 2000)], {...settings(), extra_cny: 500, records: [bought('done', 1, 500)]}),
  () => assertPlanCase([item('skipMe', 'a', 100, 500), item('takeMe', 'b', 100, 300)], {...settings(), records: [skipped('skipMe')]}),
];

for (const [index, run] of cases.entries()) test(`budget subset fixture ${index + 1}`, run);
