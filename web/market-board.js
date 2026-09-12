import {buyDecision,sellDecisions} from './market-decisions.mjs';
import {deskBasket,remainingPurchase} from './tokyo-planner.mjs';
import {plannerLedger,openHolding} from './tokyo-planner.js?v=20260912-1';
const $=s=>document.querySelector(s),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v===null?'待核':`¥${v.toLocaleString('zh-CN',{maximumFractionDigits:2})}`;
const time=v=>v?new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Tokyo',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(v))+' JST':'时间待核';
const link=(url,text)=>url?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text} ↗</a>`:'';
let get=()=>({items:[],online:false}),edit=()=>{};
export function initMarket(read,openEditor){
 get=read;edit=openEditor;
 $('#market-board').innerHTML=`<div class="market-heading"><div><p class="eyebrow">BUY / SELL DECISIONS</p><h2>有什么值得抢，<br>什么现在适合卖。</h2><p>先看商品和价格门槛，再决定要不要出手。</p></div><button class="primary" data-market-add>＋ 添加拍卖 / 商品</button></div><div id="market-status" class="market-status" role="status"></div><div class="market-columns"><section class="market-lane"><div class="market-lane-title"><h3>值得买 / 抢</h3><span id="buy-count"></span></div><p class="market-explain">普通购买、发售和竞拍放一起判断。拍卖按下一次最低出价估算成本。每条单独判断，合并采购由日计划限制总预算。</p><div id="buy-decisions"></div><div class="market-source-links">找机会：${link('https://auctions.yahoo.co.jp/','Yahoo! 拍卖')}${link('https://blog.mita-sneakers.co.jp/','mita 官方发售')}${link('https://snkrdunk.com/','SNKRDUNK 行情')}</div></section><section class="market-lane"><div class="market-lane-title"><h3>建议卖</h3><span id="sell-count"></span></div><p class="market-explain">对照已购批次成本和当前可用净收入，达到设置的利润目标再提示出手。</p><div id="sell-decisions"></div></section></div><details class="market-example"><summary>一条已核实的排除案例 · KEEN × DOE</summary><p>2026-09-12 人工核验：JASPER ZIONIC “DOE”，货号 1032650，含税 ¥22,000 JPY。店头抽签取货期为 9 月 17—21 日，要求日本国内居住，且公告有限制转售条款。与 10 月 2—7 日东京行程不匹配，未加入采购池。</p>${link('https://blog.mita-sneakers.co.jp/%E3%80%90%E5%BA%97%E9%A0%AD%E6%8A%BD%E9%81%B8%E8%B2%A9%E5%A3%B2%E5%91%8A%E7%9F%A5%E3%80%91-249-39836.html','核对官方原文')}</details><p class="market-footnote">当前依据本地录入的报价与实购记录判断，尚未自动抓取拍卖、成交或库存。平台最终报价、资格和收件要求需下单前核实。</p>`;
 $('#market-board').addEventListener('click',e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-market-add'))return edit();
  if(b.dataset.marketEdit)return edit(get().items.find(i=>i.id===b.dataset.marketEdit));
  if(b.dataset.marketSettle){const message=openHolding(b.dataset.date,b.dataset.marketSettle);if(message)$('#market-status').textContent=message;}
 });
 document.addEventListener('planner:updated',renderMarket);document.addEventListener('sourcing:updated',renderMarket);
 setInterval(renderMarket,30000);renderMarket();
}
function renderMarket(){
 const {items,online}=get(),ledger=plannerLedger(),funds=deskBasket([],ledger.days),connected=online&&ledger.connected;
 const records=ledger.days.flatMap(d=>d.records||[]);
 const buy=items.filter(i=>!i.archived).map(i=>buyDecision(remainingPurchase(i,records),funds.unknown||!connected?null:funds.remaining));
 buy.sort((a,b)=>({buy:0,watch:1,pass:2}[a.state]-{buy:0,watch:1,pass:2}[b.state])||(b.profit??-Infinity)-(a.profit??-Infinity));
 const sell=sellDecisions(items,ledger.days);
 $('#market-status').textContent=connected?'按已录入证据判断 · 剩余可安排 '+money(funds.remaining)+(funds.unknown?'（尚有未知费用）':''):'资料未连接完整，以下仅供核对；请刷新本地服务。';
 $('#buy-count').textContent=`${buy.filter(d=>d.state==='buy').length} 条可考虑 · ${buy.length} 条候选`;
 $('#sell-count').textContent=`${connected?sell.filter(d=>d.state==='sell').length:0} 批达到目标 · ${sell.length} 批未结算`;
 $('#buy-decisions').innerHTML=buy.map(d=>{
  const i=d.item,a=i.deal||{},auction=d.kind==='auction',label={buy:'可考虑参与',watch:'继续观察',pass:'暂不参与'}[d.state];
  return `<article class="market-card"><div class="market-card-top"><small>${{retail:'常规购买',auction:'竞拍',drop:'发售 / 补货'}[d.kind]} · ${esc(i.source_name||'平台待填')}</small><span class="market-badge ${d.state}">${label}</span></div><h4>${esc(i.name)}</h4><p class="market-spec">${esc(i.code||'货号待填')} · ${esc(i.color||'版本待核')} · ${esc(i.size||'规格待核')}</p><div class="market-prices"><div><small>${auction?'最高含税出价':'最高采购价'} · JPY</small><strong>${money(auction?d.maxBidJPY:d.maxBuyJPY)}</strong></div><div><small>预计净赚 / ${auction?'标的':'件'} · CNY</small><strong>${money(d.profit)}</strong></div></div>${auction?`<p class="market-timing">已记录当前竞价 ${money(a.current_jpy??null)} JPY · 截止 ${time(a.ends_at)}<br>竞价观察：${time(a.observed_at)}；可能自动延时，参与前重核。</p>`:i.visit?.release_at?`<p class="market-timing">发售 ${time(i.visit.release_at)}</p>`:''}<p class="market-reason">${esc(d.reason||'补齐准确规格、库存与销售依据')}</p><p class="market-exit">计划卖到 ${esc(i.channel)} · 国内保守净收入 ${money(i.quote.net_cny??null)} CNY / 件</p><div class="market-actions">${link(i.source_url,auction?'打开拍卖':'查看商品')}<button class="text-button" data-market-edit="${esc(i.id)}">${auction?'更新竞价 / 费用':'核价与理由'}</button>${d.state==='buy'?'<a href="#day-planner">排进日计划 ↗</a>':''}</div></article>`;
 }).join('')||'<div class="market-empty"><strong>先添加一条具体商品或拍卖链接</strong><p>填准确规格与买卖依据后，这里给出价格门槛和判断。</p></div>';
 $('#sell-decisions').innerHTML=sell.map(d=>{
  const r=d.record,state=connected?d.state:'review';
  return `<article class="market-card"><div class="market-card-top"><small>${esc(d.date)} 购入 · ${r.units} 件</small><span class="market-badge ${state}">${state==='sell'?'可考虑卖出':'先核对'}</span></div><h4>${esc(r.name||r.code)}</h4><p class="market-spec">${esc(r.code)} · ${esc(r.color||'配色待核')} · ${esc(r.size||'规格待核')}</p><div class="market-prices"><div><small>该批预计净回款 · CNY</small><strong>${money(d.proceeds)}</strong></div><div><small>按实际成本预计净利 · CNY</small><strong>${money(d.profit)}</strong></div></div><p class="market-exit">实购全成本 ${money(r.cost_cny)} · 达标净回款 ${money(d.targetNet)}<br>销售渠道：${esc(r.channel||'待核')}</p><p class="market-reason">${esc(connected?d.reason:'资料未核对完整，暂不作卖出建议')}</p><div class="market-actions">${d.item?`<button class="text-button" data-market-edit="${esc(d.item.id)}">核对当前卖价</button>`:''}<button class="text-button" data-market-settle="${esc(r.item_id)}" data-date="${esc(d.date)}">核对批次 / 记录结算</button></div></article>`;
 }).join('')||'<div class="market-empty"><span aria-hidden="true">↗</span><strong>还没有可确认的待售批次</strong><p>在日计划的商品旁记录实购后，这里会按实际成本判断卖出。已整批结算的货会自动移出。</p><a href="#day-planner">去记录采购 ↗</a></div>';
}
const input=(name,label,value,type='number',attrs='')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${type==='number'?'min="0" step="any"':''} ${attrs}></label>`;
export function dealFields(i){const a=i.deal||{},local=v=>v?new Date(new Date(v).getTime()+9*3600000).toISOString().slice(0,19):'';return `<section class="form-section"><h3>普通买，还是竞拍 / 抢发售</h3><div class="form-grid"><label class="field">机会类型<select name="deal_kind"><option value="retail" ${!a.kind||a.kind==='retail'?'selected':''}>普通商品</option><option value="auction" ${a.kind==='auction'?'selected':''}>竞拍标的</option><option value="drop" ${a.kind==='drop'?'selected':''}>发售 / 补货</option></select></label></div><div id="auction-fields" ${a.kind==='auction'?'':'hidden'}><div class="form-grid">${input('deal_current','当前竞价 · JPY（含商品税）',a.current_jpy)}${input('deal_increment','下一次最低加价 · JPY',a.increment_jpy)}${input('deal_fee','另收买方手续费 · %（无则 0）',a.fee_pct)}${input('deal_fixed','另收固定费用 · JPY（无则 0）',a.fixed_jpy)}${input('deal_observed','竞价核验时刻 · 日本时间',local(a.observed_at),'datetime-local','step="1"')}${input('deal_ends','拍卖截止时刻 · 日本时间',local(a.ends_at),'datetime-local','step="1"')}</div><p>按“当前竞价＋最低加价”及拍卖费用估算下一次参与价；不是成交价或已出价。超过15分钟必须重新核价。每条拍卖按一个标的计价；按平台最新规则更新最低加价、税费和延时后的截止时间。下方“其余成本”不重复填写这里的费用。</p></div></section>`;}
export function readDeal(data){const n=k=>data.get(k)===''?null:Number(data.get(k));return {kind:data.get('deal_kind'),current_jpy:n('deal_current'),increment_jpy:n('deal_increment'),fee_pct:n('deal_fee'),fixed_jpy:n('deal_fixed'),observed_at:data.get('deal_observed')?data.get('deal_observed')+'+09:00':null,ends_at:data.get('deal_ends')?data.get('deal_ends')+'+09:00':null};}
