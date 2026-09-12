const money = n => Math.round(n * 100) / 100;
const valid = (n, zero = false) => typeof n === 'number' && Number.isFinite(n) && (zero ? n >= 0 : n > 0);
export function recent(date, now) {
  if (!date || !/^\d{4}-\d{2}-\d{2}$/.test(date)) return false;
  const at = new Date(`${date}T00:00:00+08:00`);
  const age = now - at;
  return Number.isFinite(age) && age >= 0 && age <= 72 * 3600000;
}
export function purchaseQuote(item) {
  const q={...item.quote},a=item.deal;
  if(a?.kind==='auction'){
    q.buy_jpy=valid(a.current_jpy,true)&&valid(a.increment_jpy)&&valid(a.fee_pct,true)&&valid(a.fixed_jpy,true)
      ?money((a.current_jpy+a.increment_jpy)*(1+a.fee_pct/100)+a.fixed_jpy):null;
  }
  return q;
}
export function invalidateQuote(q) {
  return {...q, stock:false, delivery:false, tax:false, seller:false,
    checked_at:null, evidence_at:null, evidence_kind:'unknown', evidence:''};
}
export function diagnose(item, now = new Date()) {
  const q = purchaseQuote(item), blockers = [];
  if (![item.code, item.color, item.size].every(x => x?.trim())) blockers.push('补全货号、配色和尺码');
  if (!item.source_url || !item.source_name) blockers.push('补全具体采购链接和店名');
  const costsKnown = valid(q.buy_jpy) && valid(q.fx) && valid(q.extra_cny, true);
  const cost = costsKnown ? money(q.buy_jpy * q.fx + q.extra_cny) : null;
  const netKnown = valid(q.net_cny);
  const profit = cost !== null && netKnown ? money(q.net_cny - cost) : null;
  const maxBuyJPY = netKnown && valid(q.extra_cny, true) && valid(q.fx) && valid(q.target_profit)
    ? Math.floor((q.net_cny - q.extra_cny - q.target_profit) / q.fx) : null;
  if (!costsKnown) blockers.push('补全实际买价、汇率和其余成本');
  if (!netKnown) blockers.push('核实国内卖出净收入');
  if (!recent(q.checked_at, now)) blockers.push('更新近 72 小时的采购核价');
  if (!['sold', 'offer', 'order'].includes(q.evidence_kind) || !q.evidence?.trim()) blockers.push('补充同规格成交或真实需求依据');
  if (!recent(q.evidence_at, now)) blockers.push('更新近 72 小时的销售依据');
  if (!q.stock) blockers.push('确认同规格可买库存');
  if (!q.delivery) blockers.push('确认东京取货和回国发货期限');
  if (!q.tax) blockers.push('核实商业转售税费并计入成本');
  if (!q.seller) blockers.push('确认当前账号可售及履约规则');
  if (!Number.isInteger(q.units) || q.units < 1) blockers.push('填写有效采购数量');
  if (!valid(q.target_profit)) blockers.push('填写每件目标利润');
  if (profit !== null && profit < q.target_profit) blockers.push('预计利润未达到目标');
  if(item.deal?.kind==='drop'&&(!item.visit?.release_at||!item.visit?.release_source))blockers.push('补全官方发售时刻与来源；补货时间未知时先观察');
  let maxBidJPY=null;
  if(item.deal?.kind==='auction'){
    const a=item.deal,age=now-new Date(a.observed_at||'');
    if(!Number.isFinite(age)||age<0||age>15*60000)blockers.push('更新近 15 分钟的竞拍价格');
    if(!a.ends_at||!(new Date(a.ends_at)>now))blockers.push('补全有效截止时间；已结束的拍卖不能参与');
    if(q.units!==1)blockers.push('每条拍卖按一个标的计价，多个拍卖须分别录入');
    if(maxBuyJPY!==null&&valid(a.fee_pct,true)&&valid(a.fixed_jpy,true))maxBidJPY=Math.floor((maxBuyJPY-a.fixed_jpy)/(1+a.fee_pct/100));
  }
  return {cost, profit, maxBuyJPY, maxBidJPY, blockers, ready: blockers.length === 0,
    stressProfit: cost !== null && netKnown ? money(q.net_cny * 0.9 - cost) : null};
}
export function basket(items, budget = 10000, reserve = 3000, now = new Date()) {
  const selected = items.filter(x => x.selected && !x.archived);
  let cost = 0, profit = 0, unknown = false, qualified = true;
  for (const item of selected) {
    const d = diagnose(item, now), units = item.quote.units;
    if (d.cost === null) unknown = true;
    else cost += d.cost * units;
    if (d.profit !== null) profit += d.profit * units;
    if (!d.ready) qualified = false;
  }
  return {selected, cost: money(cost), profit: money(profit), unknown,
    remaining: money(budget - reserve - cost),
    ready: selected.length > 0 && qualified && !unknown && cost + reserve <= budget};
}
