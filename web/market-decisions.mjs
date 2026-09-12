import {diagnose,recent} from './sourcing-model.mjs';
const cash=n=>Math.round(n*100)/100;
export function buyDecision(item,remaining,now=new Date()){
 const d=diagnose(item,now),kind=item.deal?.kind||'retail';
 const result={item,kind,...d,state:'watch',reason:d.blockers.slice(0,2).join('；')};
 if(item.quote.units===0)return {...result,state:'pass',reason:'全趟目标件数已购齐；需要补货时先调整目标件数'};
 if(kind==='auction'&&item.deal.ends_at&&new Date(item.deal.ends_at)<=now)return {...result,state:'pass',reason:'拍卖已经截止'};
 if(d.profit!==null&&d.profit<item.quote.target_profit)return {...result,state:'pass',reason:kind==='auction'?'再加价后利润已低于目标，不建议追价':'现价未达到每件利润目标'};
 if(!d.ready)return result;
 if(item.visit?.release_at&&new Date(item.visit.release_at)>now)return {...result,reason:'等待官方发售时点；参与前重新核价与资格'};
 if(remaining===null||d.cost*item.quote.units>remaining)return {...result,reason:'全趟剩余资金不足或费用尚未核齐'};
 return {...result,state:'buy',reason:kind==='auction'?'下一次最低出价仍有利润空间，超过上限就停止':'报价与履约已核齐，达到每件利润目标'};
}
export function sellDecisions(items,days,now=new Date()){
 const results=[];
 for(const day of days)for(const r of day.records||[]){
  if(r.status!=='bought'||r.actual_net_cny!==null&&r.actual_net_cny!==undefined||/^(TEST[-_]|DEMO[-_])/i.test(r.code||''))continue;
  const item=items.find(i=>i.id===r.item_id),q=item?.quote;
  const base={record:r,date:day.date,item,state:'review',proceeds:null,profit:null,targetNet:null,reason:'核对库存规格与可用销售报价'};
  if(!item||!['code','color','size','channel'].every(k=>r[k]&&r[k]===item[k])){results.push(base);continue;}
  base.targetNet=cash(r.cost_cny+q.target_profit*r.units);
  if(!q.seller||!recent(q.evidence_at,now)||!['sold','offer','order'].includes(q.evidence_kind)||!q.evidence?.trim()||!(q.net_cny>0)){
   results.push({...base,reason:'补充近 72 小时的同款成交/有效需求和卖家费用，挂牌价不足以建议出手'});continue;
  }
  const proceeds=cash(q.net_cny*r.units),profit=cash(proceeds-r.cost_cny);
  results.push({...base,proceeds,profit,state:profit>=q.target_profit*r.units?'sell':'review',reason:profit>=q.target_profit*r.units?'当前保守净收入已达到每件利润目标，可考虑出手':profit<0?'当前报价低于成本，先确定可接受的止损线':'当前净收入低于目标，需重新判断售价或利润目标'});
 }
 return results.sort((a,b)=>(a.state==='sell'?-1:1)-(b.state==='sell'?-1:1)||(b.profit??-Infinity)-(a.profit??-Infinity));
}
