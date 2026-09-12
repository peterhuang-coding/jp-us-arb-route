import test from 'node:test';
import assert from 'node:assert/strict';
import {planDay, routeTable, totals, resolveVisit, defaultSettings, navURL, deskBasket} from '../web/tokyo-planner.mjs';
const now=new Date('2026-10-02T08:00:00+09:00');
const places=[{id:'base',name:'起点',lat:35.68,lng:139.76,open:'00:00',close:'23:59'}, {id:'a',name:'店 A',lat:35.69,lng:139.76,open:'10:30',close:'18:00'}, {id:'b',name:'店 B',lat:35.70,lng:139.77,open:'10:00',close:'19:00'}];
const settings=()=>({...defaultSettings(),date:'2026-10-02',start:places[0],end:places[0],extra_cny:0,limit_cny:7000,travel:{}});
const item=(id,place,cost,net,units=1)=>({id,name:id,code:id,color:'黑',size:'27',source_url:'https://example.com/'+id,source_name:place,channel:'得物',quote:{buy_jpy:cost*20,fx:.05,extra_cny:0,net_cny:net,target_profit:1,units,checked_at:'2026-10-02',evidence_at:'2026-10-02',evidence_kind:'sold',evidence:'测试成交',stock:true,delivery:true,tax:true,seller:true},visit:{place_id:place,mode:'store',duration_min:30}});
const plan=(items,s=settings(),days=[],mode='buy')=>planDay(items,s,days,places,mode,now);
test('chooses the most profitable affordable combination, not highest ROI',()=>{
 const p=plan([item('x','a',4000,4800),item('y','b',3500,4250),item('z','b',3000,3600)]);
 assert.deepEqual(p.items.map(x=>x.id).sort(),['x','z']); assert.equal(p.forecast.profit,1400); assert.equal(p.forecast.roi,20);
});
test('same store is one visit and store opens before shopping starts',()=>{
 const p=plan([item('x','a',100,200),item('y','a',100,200)]);
 assert.equal(p.route.stops.length,1); assert.ok(p.route.stops[0].at>=630); assert.equal(p.route.stops[0].items.length,2);
});
test('closing and return deadline exclude an infeasible store',()=>{
 const s=settings();s.end_time='10:40'; assert.equal(plan([item('x','a',100,200)],s).items.length,0);
});
test('unqualified products appear in research routes without made up ROI',()=>{
 const i=item('x','a',100,200);i.quote.net_cny=null;
 assert.equal(plan([i]).items.length,0);
 const p=plan([i],settings(),[],'research'); assert.equal(p.route.stops.length,1); assert.equal(p.forecast.profit,null);assert.equal(p.forecast.roi,null);
});
test('missing extra expenses prevents an executable profit plan',()=>{
 const s=settings();s.extra_cny=null;assert.equal(plan([item('x','a',100,200)],s).items.length,0);
});
test('recorded purchases across dates consume one trip budget and quantities',()=>{
 const days=[{...settings(),date:'2026-10-01',records:[{item_id:'other',status:'bought',units:1,cost_cny:6000,expected_net_cny:6500,actual_net_cny:null}]}];
 assert.equal(plan([item('x','a',1500,1700)],settings(),days).items.length,0);
 assert.equal(plan([item('x','a',1000,1300)],settings(),days).forecast.tripCost,7000);
});
test('partial purchases are retained as actual cost, not purchased again today',()=>{
 const s=settings();s.records=[{item_id:'x',status:'bought',units:1,cost_cny:110,expected_net_cny:200,actual_net_cny:null}];
 const p=plan([item('x','a',100,200,2),item('y','b',100,200)],s);
 assert.deepEqual(p.items.map(x=>x.id),['y']);assert.equal(p.forecast.cost,210);assert.equal(p.forecast.net,400);assert.equal(p.forecast.settled,0);
 const next={...settings(),date:'2026-10-03'}; assert.equal(plan([item('x','a',100,200,2)],next,[s]).items[0].quote.units,1);
});
test('skips remove today only and stale quotes cannot become a buy recommendation',()=>{
 const s=settings();s.records=[{item_id:'x',status:'skipped',units:0,cost_cny:0}];assert.equal(plan([item('x','a',100,200)],s).items.length,0);
 const i=item('x','a',100,200);i.quote.checked_at='2026-09-01';assert.equal(plan([i]).items.length,0);
});
test('official online release is a timed task at departure point, preserves seconds',()=>{
 const i=item('x','a',100,200);i.visit={mode:'online',duration_min:10,release_at:'2026-10-02T10:45:30+09:00',release_source:'https://example.com/release'};
 const p=plan([i]);assert.equal(p.route.stops[0].at,645.5);assert.equal(p.route.stops[0].lat,places[0].lat);
 const s=settings();s.start_time='10:46';assert.equal(plan([i],s).items.length,0);
});
test('release on a different day is excluded, missing source blocks exact-time route',()=>{
 const i=item('x','a',100,200);i.visit.release_at='2026-10-03T10:45:30+09:00';i.visit.release_source='https://example.com/event';assert.equal(plan([i]).items.length,0);
 i.visit.release_at='2026-10-02T10:45:30+09:00';i.visit.release_source='';assert.equal(plan([i]).items.length,0);
});
test('travel overrides can change feasibility and affect direction independently',()=>{
 const s=settings();s.end_time='11:10';s.travel={'base>a':5,'a>base':5}; assert.equal(plan([item('x','a',100,200)],s).items.length,1);
 s.travel['a>base']=60;assert.equal(plan([item('x','a',100,200)],s).items.length,0);
});
test('too many candidate lines returns an explicit limit instead of silently dropping data',()=>{
 const p=plan(Array.from({length:11},(_,n)=>item('x'+n,'a',100,200)));assert.match(p.error,/10/);assert.equal(p.items.length,0);
});
test('unknown expected proceeds never appear as zero profit; settled money stays separate',()=>{
 const s=settings();s.records=[{item_id:'x',status:'bought',units:1,cost_cny:100,expected_net_cny:null,actual_net_cny:null}];
 const f=totals(s,[],[]);assert.equal(f.profit,null);assert.equal(f.settled,0);
 s.records[0].actual_net_cny=180;assert.equal(totals(s,[],[]).profit,80);
});
test('empty / loss making day stays home; fixed day expenses reduce profit once',()=>{
 const s=settings();s.extra_cny=150;assert.equal(plan([item('x','a',100,200)],s).items.length,0);
 s.extra_cny=20;const p=plan([item('x','a',100,200),item('y','a',100,200)],s);assert.equal(p.forecast.cost,220);assert.equal(p.forecast.profit,180);
});
test('navigation is an encoded one-leg link, not a promise of real-time ETA',()=>{
 const url=new URL(navURL({name:'起点 & A'}, {name:'店 #B'},'transit'));assert.equal(url.searchParams.get('api'),'1');assert.equal(url.searchParams.get('travelmode'),'transit');assert.equal(url.searchParams.get('origin'),'起点 & A');
});
test('an unaffordable slow SKU must not constrain a cheap SKU at the same shop',()=>{
 const s=settings();s.start_time='10:30';s.end_time='11:10';s.travel={'base>a':0,'a>base':0};
 const x=item('x','a',100,200),y=item('y','a',8000,9000);y.visit.duration_min=240;
 assert.deepEqual(plan([x,y],s).items.map(x=>x.id),['x']);
});
test('map-selected navigation preserves coordinates instead of a generic label',()=>{
 const u=new URL(navURL({id:'custom',name:'地图自选起点',lat:35.71,lng:139.81},{name:'地图终点',lat:35.72,lng:139.82}));assert.equal(u.searchParams.get('origin'),'35.71,139.81');
});
test('release before opening cannot become a later claimed release appointment',()=>{
 const i=item('x','a',100,200);i.visit.release_at='2026-10-02T10:00:00+09:00';i.visit.release_source='https://example.com/event';const s=settings();s.travel={'base>a@600':0};assert.equal(plan([i],s).items.length,0);
});

test('watchlist export uses the same remaining quantities and trip cash as the map',()=>{
 const i=item('x','a',1000,1300,3);i.selected=true;
 const s=settings();s.extra_cny=50;s.records=[{item_id:'x',status:'bought',units:1,cost_cny:1200,expected_net_cny:1300}];
 const b=deskBasket([i],[s],now);assert.equal(b.selected[0].quote.units,2);assert.equal(b.committed,1250);assert.equal(b.remaining,3750);assert.equal(b.ready,true);
 s.records[0].cost_cny=6000;assert.equal(deskBasket([i],[s],now).ready,false);
});
