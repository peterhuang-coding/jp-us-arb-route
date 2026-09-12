import {diagnose,basket} from './sourcing-model.mjs';
const round=n=>Math.round(n*100)/100;
const known=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
export const minute=s=>s.split(':').reduce((v,n,k)=>v+Number(n)*(k===0?60:k===1?1:1/60),0);
export const clock=(m,seconds=false)=>{const s=Math.round(m*60);return [Math.floor(s/3600),Math.floor(s/60)%60,...(seconds?[s%60]:[])].map(n=>String(n).padStart(2,'0')).join(':');};
export const japanDate=(at=new Date())=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo'}).format(at);
export function defaultSettings(){
 const base={id:'tokyo-station',name:'东京站（参考起点）',lat:35.68124,lng:139.76713};
 return {date:'2026-10-02',start:{...base},end:{...base},start_time:'10:00',end_time:'19:00',extra_cny:null,limit_cny:7000,candidate_ids:null,travel:{},records:[]};
}
export function navURL(from,to,mode='walking'){
 const point=x=>x.address&&!x.online?`${x.name} ${x.address}`:Number.isFinite(x.lat)&&Number.isFinite(x.lng)?`${x.lat},${x.lng}`:x.name;
 return 'https://www.google.com/maps/dir/?'+new URLSearchParams({api:'1',origin:point(from),destination:point(to),travelmode:mode});
}
export function estimateMinutes(a,b,overrides={}){
 const override=overrides[`${a.id}>${b.id}`];if(known(override))return override;
 const rad=n=>n*Math.PI/180, dlat=rad(b.lat-a.lat),dlng=rad(b.lng-a.lng);
 const h=Math.sin(dlat/2)**2+Math.cos(rad(a.lat))*Math.cos(rad(b.lat))*Math.sin(dlng/2)**2;
 const km=6371*2*Math.asin(Math.sqrt(Math.min(1,h)));
 return km<.015?0:Math.ceil((km*1.35/4*60)/5)*5;
}
export function resolveVisit(item,places,start,date){
 const v={...(item.visit||{}),...(item.deal?.kind==='auction'?{mode:'online'}:{})};
 let place=v.mode==='online'?{...start,id:`online:${item.id}`,name:`线上 · ${item.source_name}`,online:true,address:`在 ${start.name} 完成下单`,open:'00:00',close:'23:59'}
   :v.place_id==='custom'?{id:`custom:${v.lat},${v.lng}`,name:item.source_name,address:item.address,lat:v.lat,lng:v.lng,open:v.open_time,close:v.close_time}
   :places.find(p=>p.id===v.place_id)||(!v.place_id?places.find(p=>p.product_urls?.includes(item.source_url)):null);
 if(!place||!known(place.lat)||!known(place.lng))return {error:'补全地图采购点'};
 const weekday=new Date(date+'T12:00:00+09:00').getUTCDay();
 const open=v.open_time||((weekday===0||weekday===6)&&place.weekend_open)||place.open;
 const close=v.close_time||place.close;
 if(!open||!close)return {error:'补全营业时间'};
 let release=null;
 if(v.release_at){
  if(!v.release_source)return {error:'发售时间缺少官方来源'};
  release=(new Date(v.release_at)-new Date(date+'T00:00:00+09:00'))/60000;
  if(!Number.isFinite(release)||release<0||release>=1440)return {error:'发售不在所选日期'};
 }
 let deadline=minute(close);
 if(item.deal?.kind==='auction'){
  const end=(new Date(item.deal.ends_at||'')-new Date(date+'T00:00:00+09:00'))/60000;
  if(!Number.isFinite(end)||end<=0)return {error:'拍卖截止时间不在可参与的行程内'};
  deadline=Math.min(deadline,end);
 }
 // Timed releases at one shop are separate tasks; ordinary SKUs share a single visit.
 return {...place,id:release===null?place.id:`${place.id}@${release}`,open:minute(open),close:deadline,release,duration:v.duration_min||30,items:[item]};
}
export function routeTable(nodes,s){
 const size=1<<nodes.length,states=Array.from({length:size},()=>new Map()), routes=new Array(size).fill(null);
 routes[0]={stops:[],finish:minute(s.start_time),travel:0};
 const step=(prev,next,leave)=>{
  const travel=estimateMinutes(prev,next,s.travel),arrival=leave+travel;
  if(next.release!==null && (arrival>next.release+1e-8 || next.release<next.open))return null;
  const at=Math.max(arrival,next.open,next.release??0),until=at+next.duration;
  if(until>next.close+1e-8)return null;
  return {at,until,travel_mins:travel};
 };
 for(let j=0;j<nodes.length;j++){
  const stop=step(s.start,nodes[j],minute(s.start_time));
  if(stop)states[1<<j].set(j,{time:stop.until,path:[{...nodes[j],...stop}],travel:stop.travel_mins});
 }
 for(let mask=1;mask<size;mask++)for(const [last,state] of states[mask]){
  const back=estimateMinutes(nodes[last],s.end,s.travel),finish=state.time+back;
  if(finish<=minute(s.end_time)&&(!routes[mask]||finish<routes[mask].finish))routes[mask]={stops:state.path,finish,travel:state.travel+back,return_mins:back};
  for(let j=0;j<nodes.length;j++)if(!(mask&(1<<j))){
   const stop=step(nodes[last],nodes[j],state.time);if(!stop)continue;
   const nextMask=mask|(1<<j),old=states[nextMask].get(j);
   if(!old||stop.until<old.time)states[nextMask].set(j,{time:stop.until,path:[...state.path,{...nodes[j],...stop}],travel:state.travel+stop.travel_mins});
  }
 }
 return routes;
}
function allDays(s,days){return [...days.filter(d=>d.date!==s.date),s];}
function recordNet(r){return known(r.actual_net_cny)?r.actual_net_cny:known(r.expected_net_cny)?r.expected_net_cny:null;}
export function remainingPurchase(item,records){
 const bought=records.filter(r=>r.item_id===item.id&&r.status==='bought').reduce((n,r)=>n+r.units,0);
 const units=Math.max(0,item.quote.units-bought);
 return {...item,selected:item.selected&&units>0,quote:{...item.quote,units}};
}
export function deskBasket(items,days,now=new Date()){
 const records=days.flatMap(d=>(d.records||[]).filter(r=>r.status==='bought'));
 const committed=round(records.reduce((n,r)=>n+r.cost_cny,0)+days.reduce((n,d)=>n+(d.extra_cny||0),0));
 const remaining=items.map(i=>remainingPurchase(i,records));
 const b=basket(remaining,10000-committed,3000,now),extraKnown=days.every(d=>known(d.extra_cny));
 return {...b,committed,ready:b.ready&&extraKnown,unknown:b.unknown||!extraKnown};
}
export function totals(s,days,planned,research=false){
 const merged=allDays(s,days),today=(s.records||[]).filter(r=>r.status==='bought'),records=merged.flatMap(d=>(d.records||[]).filter(r=>r.status==='bought'));
 const costs=rs=>rs.reduce((n,r)=>n+r.cost_cny,0),nets=rs=>rs.every(r=>recordNet(r)!==null)?rs.reduce((n,r)=>n+recordNet(r),0):null;
 const plannedCost=planned.reduce((n,i)=>n+diagnose(i).cost*i.quote.units,0),plannedNet=planned.reduce((n,i)=>n+i.quote.net_cny*i.quote.units,0);
 const extraKnown=known(s.extra_cny),allExtraKnown=merged.every(d=>known(d.extra_cny));
 const tripExtra=merged.reduce((n,d)=>n+(d.extra_cny||0),0);
 const cost=extraKnown&&!research?round(costs(today)+s.extra_cny+plannedCost):null;
 const net=nets(today)!==null&&!research?round(nets(today)+plannedNet):null;
 const tripCost=allExtraKnown&&!research?round(costs(records)+tripExtra+plannedCost):null;
 const tripNet=nets(records)!==null&&!research?round(nets(records)+plannedNet):null;
 const profit=cost!==null&&net!==null?round(net-cost):null,tripProfit=tripCost!==null&&tripNet!==null?round(tripNet-tripCost):null;
 return {cost,net,profit,roi:cost>0&&profit!==null?round(profit/cost*100):null,tripCost,tripNet,tripProfit,tripROI:tripCost>0&&tripProfit!==null?round(tripProfit/tripCost*100):null,
  recordedCost:round(costs(records)),todayRecordedCost:round(costs(today)),settled:round(records.reduce((n,r)=>n+(r.actual_net_cny||0),0)),
  remaining:round(10000-3000-costs(records)-tripExtra-plannedCost),plannedCost:round(plannedCost),extraKnown:allExtraKnown};
}
export function planDay(items,s,days,places,mode='buy',now=new Date()){
 const exclusions=[],allRecords=allDays(s,days).flatMap(d=>d.records||[]),closedToday=new Set((s.records||[]).map(r=>r.item_id));
 const active=items.filter(i=>!i.archived&&(!s.candidate_ids||s.candidate_ids.includes(i.id))&&!closedToday.has(i.id));
 const base={items:[],route:{stops:[],finish:minute(s.start_time),travel:0},nodes:[],exclusions,forecast:totals(s,days,[],mode==='research'),error:'',mode,future:s.date>japanDate(now)};
 if(minute(s.end_time)<=minute(s.start_time))return {...base,error:'结束时间需要晚于开始时间'};
 if(active.length>10)return {...base,error:'最多同时比较 10 个商品，请在“参与规划”中减少候选。'};
 const eligible=[];
 for(const raw of active){
  const item=remainingPurchase(raw,allRecords);
  if(!item.quote.units){exclusions.push({item,reason:'全趟目标件数已购齐'});continue;}
  const d=diagnose(item,now),v=resolveVisit(item,places,s.start,s.date);
  if(v.error || (mode==='buy'&&!d.ready)){exclusions.push({item,reason:v.error||d.blockers.slice(0,2).join('；')});continue;}
  eligible.push({item,d,v});
 }
 const group=subset=>{
  const byPlace=new Map();
  for(const e of subset){
   if(!byPlace.has(e.v.id))byPlace.set(e.v.id,{...e.v,items:[]});
   const n=byPlace.get(e.v.id);n.items.push(e.item);n.open=Math.max(n.open,e.v.open);n.close=Math.min(n.close,e.v.close);n.duration=Math.max(n.duration,e.v.duration);
  }
  return [...byPlace.values()];
 };
 const nodes=group(eligible),cache=new Map();
 const cash=base.forecast.remaining,extra=known(s.extra_cny)?s.extra_cny:0;
 if(mode==='buy'&&!base.forecast.extraKnown)return {...base,nodes,error:'请补全已保存日期的额外费用；确实没有才填 0。'};
 let best={score:0,finish:Infinity,mask:0,route:base.route};
 for(let mask=1;mask<(1<<eligible.length);mask++){
  let cost=0,profit=0,count=0;
  const subset=[];
  for(let j=0;j<eligible.length;j++)if(mask&(1<<j)){
   const {item,d}=eligible[j];subset.push(eligible[j]);count++;
   if(mode==='buy'){cost+=d.cost*item.quote.units;profit+=d.profit*item.quote.units;}
  }
  if(mode==='buy'&&(cost>cash+.001||cost>Math.max(0,s.limit_cny-base.forecast.todayRecordedCost-extra)+.001))continue;
  const currentNodes=group(subset);
  // Only selected SKUs constrain the visit. Cache timing independently of SKU contents.
  const key=JSON.stringify(currentNodes.map(n=>[n.id,n.open,n.close,n.duration]));
  if(!cache.has(key)){const routes=routeTable(currentNodes,s);cache.set(key,routes[(1<<currentNodes.length)-1]);}
  const cached=cache.get(key);if(!cached)continue;
  const route={...cached,stops:cached.stops.map(n=>({...n,items:currentNodes.find(v=>v.id===n.id).items}))};
  const score=mode==='research'?count:round(profit-extra);
  if(score>best.score||(score>0&&score===best.score&&route.finish<best.finish))best={score,finish:route.finish,mask,route};
 }
 const selected=eligible.filter((_,j)=>best.mask&(1<<j)).map(e=>e.item),selectedIds=new Set(selected.map(i=>i.id));
 const route=best.route;
 const stops=route.stops.map(n=>({...n,items:n.items.filter(i=>selectedIds.has(i.id))}));
 for(const e of eligible)if(!selectedIds.has(e.item.id))exclusions.push({item:e.item,reason:mode==='buy'?'预算、时窗或净利润组合不占优':'当天时间内未排入'});
 return {...base,items:selected,nodes,route:{...route,stops},exclusions,forecast:totals(s,days,mode==='research'?[]:selected,mode==='research')};
}
