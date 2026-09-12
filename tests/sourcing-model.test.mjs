import test from 'node:test';
import assert from 'node:assert/strict';
import {diagnose, basket} from '../web/sourcing-model.mjs';
const now = new Date('2026-09-11T12:00:00+08:00');
const good = () => ({id:'a',name:'测试',code:'ABC',color:'黑',size:'27 cm',source_url:'https://example.com/a',source_name:'店',pool:'stable',channel:'得物',selected:true,quote:{buy_jpy:10000,fx:0.05,extra_cny:100,net_cny:850,target_profit:100,units:2,checked_at:'2026-09-11',evidence_at:'2026-09-11',evidence_kind:'sold',evidence:'同款同码成交记录',stock:true,delivery:true,tax:true,seller:true}});
test('missing cost is unknown, never free',()=>{let i=good();i.quote.extra_cny=null;let d=diagnose(i,now);assert.equal(d.cost,null);assert.equal(d.ready,false);assert.equal(d.profit,null);});
test('profit and maximum buying price do not double deduct selling fees',()=>{let d=diagnose(good(),now);assert.equal(d.cost,600);assert.equal(d.profit,250);assert.equal(d.maxBuyJPY,13000);assert.equal(d.stressProfit,165);assert.equal(d.ready,true);});
test('asking price and missing evidence cannot qualify',()=>{let i=good();i.quote.evidence_kind='ask';assert.equal(diagnose(i,now).ready,false);i.quote.evidence_kind='sold';i.quote.evidence='';assert.equal(diagnose(i,now).ready,false);});
test('stale and future price or demand evidence must be rechecked',()=>{for(const key of ['checked_at','evidence_at']) for(const date of ['2026-09-01','2026-09-15','bad']){let i=good();i.quote[key]=date;assert.equal(diagnose(i,now).ready,false);}});
test('unspecified size and missing fulfillment block purchase',()=>{for(const key of ['stock','delivery','tax','seller']){let i=good();i.quote[key]=false;assert.equal(diagnose(i,now).ready,false);}let i=good();i.size='';assert.equal(diagnose(i,now).ready,false);});
test('below target is not ready even with positive profit',()=>{let i=good();i.quote.net_cny=650;assert.equal(diagnose(i,now).ready,false);});
test('basket includes quantities, reserve, and invalidated selected items',()=>{let i=good();let b=basket([i],10000,3000,now);assert.equal(b.cost,1200);assert.equal(b.profit,500);assert.equal(b.remaining,5800);assert.equal(b.ready,true);i.quote.units=20;assert.equal(basket([i],10000,3000,now).ready,false);i.quote.extra_cny=null;assert.equal(basket([i],10000,3000,now).ready,false);});
test('empty basket is not an executable purchase plan',()=>{assert.equal(basket([],10000,3000,now).ready,false);});

test('changing a specification requires new evidence while retaining cost estimates',async()=>{
  const {invalidateQuote}=await import('../web/sourcing-model.mjs');
  const q=invalidateQuote(good().quote);
  assert.equal(q.stock,false);
  assert.equal(q.evidence_kind,'unknown');
  assert.equal(q.evidence_at,null);
  assert.equal(q.checked_at,null);
  assert.equal(q.evidence,'');
  assert.equal(q.buy_jpy,10000);
  assert.equal(diagnose({...good(),quote:q},now).ready,false);
});
