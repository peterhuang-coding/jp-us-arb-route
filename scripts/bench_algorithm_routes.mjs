import { performance } from 'node:perf_hooks';
import { planDay, defaultSettings } from '../web/tokyo-planner.mjs';

const now = new Date('2026-10-02T08:00:00+09:00');
const date = '2026-10-02';
const origin = { id:'origin', name:'基准起点', lat:35.68124, lng:139.76713, open:'00:00', close:'23:59' };
const base = { ...defaultSettings(), date, start:origin, end:origin, start_time:'10:00', end_time:'19:00', extra_cny:0, limit_cny:7000, travel:{}, records:[] };
const counts = [2,4,6,8,10];
const WARM = 2, RUNS = 5;

function mulberry32(seed){let a=seed>>>0;return function(){a+=0x6D2B79F5;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296};}
function place(id){return {id,name:'店铺 '+id,lat:35.681+(id.charCodeAt(1)%17)*0.00055,lng:139.767+(id.charCodeAt(2)%19)*0.0006,open:'09:00',close:'21:00'};}
function evidence(id, net){return {id:'ev-'+id,kind:'sold',channel:'得物',amount_cny:net,amount_basis:'net',fees_cny:null,observed_at:'2026-10-02T06:00:00+08:00',source_ref:'固定基准成交',source_url:'https://example.invalid/evidence/'+id,note:'',code:'C'+id,color:'黑',size:'27'};}
function item(id, pid, cost, net){
 return {id,name:'商品 '+id,code:'C'+id,color:'黑',size:'27',source_url:'https://example.invalid/item/'+id,source_name:'店铺 '+pid,channel:'得物',
  quote:{buy_jpy:cost*20,fx:.05,extra_cny:0,net_cny:net,target_profit:1,units:1,checked_at:date,evidence_at:date,evidence_kind:'sold',evidence:'固定有效成交摘要',evidence_records:[evidence(id,net)],stock:true,delivery:true,tax:true,seller:true},
  visit:{place_id:pid,mode:'store',duration_min:30}};
}
function makeShape(shape,n){
 const rnd=mulberry32(9137+n*(shape==='same'?17:41));
 const places=[origin], ids=[];
 const pids=[];
 for(let i=0;i<n;i++){
  const pid=shape==='same'?'S00':('P'+String(i).padStart(2,'0'));
  if(!pids.includes(pid)){pids.push(pid);places.push(place(pid));}
  ids.push('I'+String(i).padStart(2,'0'));
 }
 const items=ids.map((id,i)=>{
  const cost=100+Math.floor(rnd()*401);
  const net=cost+50+Math.floor(rnd()*101);
  return item(id,shape==='same'?'S00':('P'+String(i).padStart(2,'0')),cost,net);
 });
 if(shape==='same'&&!places.some(p=>p.id==='S00'))places.push(place('S00'));
 const travel={};
 if(shape==='distinct'){
  const rr=mulberry32(2291+n);
  const nodes=['origin',...pids];
  for(const a of nodes)for(const b of nodes)if(a!==b)travel[a+'>'+b]=3+Math.floor(rr()*5);
 }
 return {items,places,settings:{...base,travel}};
}
function stopKey(st){return st.id+':'+(st.items||[]).map(x=>x.id).join('|');}
function fingerprint(r){
 return JSON.stringify({
  ids:r.items.map(x=>x.id),
  stops:r.route.stops.map(stopKey),
  finish:r.route.finish,
  plannedCost:r.forecast.plannedCost,
  profit:r.forecast.profit
 });
}
function pct(xs,q){const a=[...xs].sort((x,y)=>x-y);const idx=Math.min(a.length-1,Math.max(0,Math.ceil(q*a.length)-1));return a[idx];}
function median(xs){const a=[...xs].sort((x,y)=>x-y),m=a.length>>1;return a.length%2?a[m]:(a[m-1]+a[m])/2;}
function round3(n){return Math.round(n*1000)/1000;}
function runOne(shape,n){
 const fixture=makeShape(shape,n), times=[];
 let first=null;
 for(let i=0;i<WARM+RUNS;i++){
  const t0=performance.now();
  const r=planDay(fixture.items,fixture.settings,[],fixture.places,'buy',now);
  const dt=performance.now()-t0;
  if(r.error)throw new Error(shape+'/'+n+' unexpectedly rejected: '+r.error);
  if(r.items.length!==n)throw new Error(shape+'/'+n+' expected all feasible candidates, selected '+r.items.length);
  const fp=fingerprint(r);
  if(first&&fp!==first.fp)throw new Error('nondeterministic result for '+shape+'/'+n);
  if(i===0)first={fp,r};else if(i>=WARM)times.push(dt);
 }
 const r=first.r;
 return {shape,count:n,median_ms:round3(median(times)),p95_ms:round3(pct(times,.95)),selected_count:r.items.length,objective_profit:r.forecast.profit,finish:r.route.finish,deterministic_result:true};
}
function verifyCap(){
 const f=makeShape('distinct',11);
 let r;
 try{r=planDay(f.items,f.settings,[],f.places,'buy',now);}
 catch(e){throw new Error('existing 11-candidate guard did not return its normal rejection: '+e.message);}
 if(!r.error||!r.error.includes('10'))throw new Error('missing existing rejection mentioning 10 for 11 candidates');
 if((r.items||[]).length!==0)throw new Error('rejected 11-candidate plan must have no selected items');
 return r.error;
}
const capError=verifyCap();
const results=[];
for(const shape of ['same','distinct'])for(const n of counts)results.push(runOne(shape,n));
console.log(JSON.stringify({
 benchmark:'observational algorithm route planning benchmark',
 fixed_now:now.toISOString(),
 generated_at:'fixed fixture; no current-date sampling',
 warmups_per_case:WARM,
 measured_repeats_per_case:RUNS,
 existing_11_candidate_rejection:{error_mentions_10:true,selected_items:0,error:capError},
 results
},null,2));
