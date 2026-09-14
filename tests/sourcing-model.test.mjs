import test from 'node:test';
import assert from 'node:assert/strict';
import {basket, currentExitEvidence, diagnose, invalidateQuote} from '../web/sourcing-model.mjs';

const now = new Date('2026-09-11T12:00:00+08:00');
const evidence = (overrides = {}) => ({
  id:'ev-1',kind:'sold',channel:'得物',amount_cny:850,amount_basis:'net',fees_cny:null,
  observed_at:'2026-09-11T10:00:00+08:00',source_ref:'得物卖家端，同款同码成交',source_url:'https://example.com/evidence',
  note:'',code:'ABC',color:'黑',size:'27 cm',...overrides,
});
const good = () => ({
  id:'a',name:'测试',code:'ABC',color:'黑',size:'27 cm',source_url:'https://example.com/a',source_name:'店',pool:'stable',channel:'得物',selected:true,
  quote:{buy_jpy:10000,fx:0.05,extra_cny:100,net_cny:850,target_profit:100,units:2,checked_at:'2026-09-11',evidence_at:'2026-09-11',evidence_kind:'sold',evidence:'旧摘要',evidence_records:[evidence()],stock:true,delivery:true,tax:true,seller:true},
});

test('missing cost is unknown, never free',()=>{let i=good();i.quote.extra_cny=null;let d=diagnose(i,now);assert.equal(d.cost,null);assert.equal(d.ready,false);assert.equal(d.profit,null);});
test('profit and maximum buying price use the selected evidence net amount',()=>{let d=diagnose(good(),now);assert.equal(d.cost,600);assert.equal(d.profit,250);assert.equal(d.maxBuyJPY,13000);assert.equal(d.stressProfit,165);assert.equal(d.ready,true);});
test('multiple valid records use the lowest net proceeds conservatively',()=>{const i=good();i.quote.evidence_records.push(evidence({id:'ev-2',kind:'offer',amount_cny:790,observed_at:'2026-09-11T11:00:00+08:00',source_ref:'真实买家有效报价'}));const d=diagnose(i,now);assert.equal(d.exitEvidence.id,'ev-2');assert.equal(d.validExitEvidenceCount,2);assert.equal(d.profit,190);});
test('gross evidence subtracts selling fees once',()=>{const i=good();i.quote.evidence_records=[evidence({amount_cny:900,amount_basis:'gross',fees_cny:80})];const d=diagnose(i,now);assert.equal(d.exitEvidence.net_cny,820);assert.equal(d.profit,220);});
test('asking price and legacy manual fields cannot qualify',()=>{let i=good();i.quote.evidence_records[0].kind='ask';assert.equal(diagnose(i,now).ready,false);i=good();i.quote.evidence_records=[];i.quote.net_cny=999;i.quote.evidence_kind='sold';i.quote.evidence_at='2026-09-11';i.quote.evidence='旧手填字段';assert.equal(diagnose(i,now).ready,false);});
test('stale, future, malformed and timezone-less evidence must be rechecked',()=>{for(const observed_at of ['2026-09-01T10:00:00+08:00','2026-09-15T10:00:00+08:00','2026-09-11T10:00:00','bad']){const i=good();i.quote.evidence_records[0].observed_at=observed_at;assert.equal(diagnose(i,now).ready,false);}});
test('wrong specification or channel never becomes an exit price',()=>{for(const change of [{size:'28 cm'},{code:'OTHER'},{color:'白'},{channel:'闲鱼'}]){const i=good();Object.assign(i.quote.evidence_records[0],change);assert.equal(currentExitEvidence(i,now).selected,null);assert.equal(diagnose(i,now).ready,false);}});
test('stale and future purchase checks must be rechecked',()=>{for(const date of ['2026-09-01','2026-09-15','bad']){let i=good();i.quote.checked_at=date;assert.equal(diagnose(i,now).ready,false);}});
test('unspecified size and missing fulfillment block purchase',()=>{for(const key of ['stock','delivery','tax','seller']){let i=good();i.quote[key]=false;assert.equal(diagnose(i,now).ready,false);}let i=good();i.size='';assert.equal(diagnose(i,now).ready,false);});
test('below target is not ready even with positive profit',()=>{let i=good();i.quote.evidence_records[0].amount_cny=650;assert.equal(diagnose(i,now).ready,false);});
test('basket includes quantities, reserve, and invalidated selected items',()=>{let i=good();let b=basket([i],10000,3000,now);assert.equal(b.cost,1200);assert.equal(b.profit,500);assert.equal(b.remaining,5800);assert.equal(b.ready,true);i.quote.units=20;assert.equal(basket([i],10000,3000,now).ready,false);i.quote.extra_cny=null;assert.equal(basket([i],10000,3000,now).ready,false);});
test('empty basket is not an executable purchase plan',()=>{assert.equal(basket([],10000,3000,now).ready,false);});
test('changing a specification retains evidence history but invalidates execution checks',()=>{const original=good(),q=invalidateQuote(original.quote);assert.equal(q.stock,false);assert.equal(q.evidence_kind,'unknown');assert.equal(q.evidence_at,null);assert.equal(q.checked_at,null);assert.equal(q.evidence,'');assert.equal(q.buy_jpy,10000);assert.equal(q.evidence_records.length,1);assert.equal(diagnose({...original,size:'28 cm',quote:q},now).ready,false);});
