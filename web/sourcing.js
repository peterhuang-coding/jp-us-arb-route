import {diagnose, invalidateQuote, purchaseQuote} from './sourcing-model.mjs';
import {initPlanner, visitFields, readVisit, plannerLedger} from './tokyo-planner.js?v=20260912-1';
import {deskBasket} from './tokyo-planner.mjs';
import {initMarket, dealFields, readDeal} from './market-board.js?v=20260912-1';
const basket = list => deskBasket(list, plannerLedger().days);
const $ = s => document.querySelector(s);
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const cny = v => v === null ? '待核价' : '¥' + v.toLocaleString('zh-CN', {maximumFractionDigits:2});
const jpy = v => v === null ? '待核价' : '¥' + v.toLocaleString('ja-JP', {maximumFractionDigits:0});
let items = [], tab = 'all', query = '', draft = null, online = false, tripKnown = false;
let opener = null, editorSession = 0;
const descriptions = {
  all:'常卖款候选也需要成交验证；观察不等于建议购买。',
  stable:'盯同款同码的持续需求与买价；经典款也可能没有价差。',
  hot:'盯发售、联名与补货；核实资格、库存和实际成交后再判断。',
  selected:'只有核价条件齐全且不超预算，才可导出执行清单。',
  archived:'暂时放下的候选保留记录，随时可以恢复观察。',
};
function notice(message = '') { $('#notice').textContent = message; $('#notice').hidden = !message; }
async function api(path, method = 'GET', body) {
  const r = await fetch(path, {method, headers:{'Content-Type':'application/json'}, cache:'no-store',
    signal:AbortSignal.timeout(12000), ...(body ? {body:JSON.stringify(body)} : {})});
  const data = await r.json();
  if (!r.ok) throw new Error(Array.isArray(data.detail) ? data.detail.map(x => x.msg).join('；') : data.detail || '服务暂时不可用');
  return data;
}
async function load() {
  $('#refresh').disabled = true;
  const results = await Promise.allSettled([api('/api/sourcing'), api('/api/trips/1')]);
  online = results[0].status === 'fulfilled';
  tripKnown = results[1].status === 'fulfilled';
  if (online) items = results[0].value;
  $('#connection').textContent = online ? '本地资料已连接' : '本地服务未连接';
  $('#connection').classList.toggle('online', online);
  if (tripKnown) {
    const t = results[1].value.trip;
    $('#trip-city').innerHTML = `${esc(t.destination)} <span>→ 中国</span>`;
    $('#trip-dates').innerHTML = `${esc(t.start_date.slice(5).replace('-','.'))} <span>—</span> ${esc(t.end_date.slice(5).replace('-','.'))}`;
    $('#trip-status').textContent = `${t.start_date.slice(0,4)} · 行程已确认`;
    // This workbench's pickup checks refer specifically to the approved Tokyo window.
    tripKnown = t.destination === '东京' && t.start_date === '2026-10-02' && t.end_date === '2026-10-07';
  } else $('#trip-status').textContent = '行程读取失败 · 日期为上次确认';
  notice(!online ? '观察池读取失败，暂不能保存或导出。请确认本地服务运行后点“刷新资料”。' : !tripKnown ? '行程与本页东京采购窗口未能核对，暂不能导出。请核实当前行程。' : '');
  render();
  $('#refresh').disabled = false;
}
function setTab(value) { tab = value; render(); }
function render(notifyPlanner = true) {
  if(notifyPlanner) document.dispatchEvent(new CustomEvent('sourcing:updated'));
  const active = items.filter(x => !x.archived), plan = basket(items);
  $('#total-count').textContent = String(active.length).padStart(2,'0');
  $('#stable-count').textContent = active.filter(x => x.pool === 'stable').length;
  $('#hot-count').textContent = active.filter(x => x.pool === 'hot').length;
  $('#nav-count').textContent = plan.selected.length;
  $('#catalog-heading').childNodes[0].textContent = tab === 'selected' ? '东京采购清单 ' : tab === 'archived' ? '已搁置的候选 ' : '选品观察池 ';
  $('#pool-description').textContent = descriptions[tab];
  document.querySelectorAll('[data-tab]').forEach(b => {b.classList.toggle('active',b.dataset.tab === tab); b.classList.toggle('nav-on',b.dataset.tab === tab);b.setAttribute('aria-pressed',String(b.dataset.tab === tab));});
  const visible = items.filter(x => (tab === 'archived' ? x.archived : !x.archived)
    && (!['stable','hot'].includes(tab) || x.pool === tab)
    && (tab !== 'selected' || x.selected)
    && [x.name,x.brand,x.code,x.source_name,x.color].join(' ').toLowerCase().includes(query.toLowerCase()));
  $('#items').innerHTML = visible.length ? visible.map(card).join('') : empty();
  $('#budget-used').textContent = cny(plan.cost + plan.committed) + (plan.unknown ? ' + 未知费用' : '');
  $('#budget-left').textContent = plan.unknown ? '待补全成本' : cny(plan.remaining);
  $('#budget-left').classList.toggle('negative',plan.remaining < 0);
  $('#budget-fill').style.width = Math.min((plan.cost + plan.committed) / 10000 * 100,100) + '%';
  $('#budget-note').textContent = plan.remaining < 0 ? '采购单加额外预留已超预算，请减少数量或移出商品。' : plan.selected.length && !plan.ready ? '采购单中仍有未通过核验的商品，先补全或移出。' : '已扣日计划实购、已填额外费用与待购清单；商品件数按全趟剩余目标计算。未知费用在上方日计划补全。';
  $('#export').disabled = !plan.ready || !online || !tripKnown || !plannerLedger().connected;
  $('#add-item').disabled = !online;
  $('#purchase-summary').hidden = tab !== 'selected' || !plan.selected.length;
  $('#purchase-summary').innerHTML = `<div class="purchase-note"><strong>${plan.ready ? '核价条件齐全 · 仍需按实际订单执行' : '清单待复核 · 暂不能导出执行'}</strong>采购占用 ${esc(cny(plan.cost))}${plan.unknown ? ' + 未知费用' : ''} · ${plan.ready ? '预计合计净利润 ' + esc(cny(plan.profit)) : '未核齐的收入不计为确定利润'}。收件地址以真实订单为准。</div>`;
}
function card(i) {
  const d = diagnose(i), source = i.source_name || '采购点待补充';
  return `<article class="product" data-id="${esc(i.id)}">
    <div class="product-main"><div class="product-image">${i.image_url ? `<img src="${esc(i.image_url)}" alt="${esc(i.name + ' ' + i.color)}" loading="lazy" referrerpolicy="no-referrer">` : '<span aria-hidden="true">◇</span>'}</div><div><p class="brand-name">${esc(i.brand || (i.pool === 'hot' ? '热点款候选' : '常卖款候选'))}</p><h3>${esc(i.name)}</h3><p class="variant">${esc(i.color || '配色待核')} · ${esc(i.size || '尺码待核')}</p><p class="code">${esc(i.code || '货号待补充')}</p></div><div class="product-state"><span class="badge ${d.ready ? 'ready' : ''}">${i.archived ? '已搁置' : d.ready ? '核价通过' : '待核价'}</span><p class="price-label">官网含税参考价</p><p class="price">${esc(jpy(i.reference_jpy))} <small>JPY</small></p></div></div>
    <div class="route"><div><div class="route-label">在哪里买 · ${i.pool === 'hot' ? '热点款观察' : '常卖款观察'}</div><strong>${esc(source)}</strong><p>${esc(i.address || '日本收货点 / 门店地址待确认')}</p>${i.source_url ? `<a class="route-link" href="${esc(i.source_url)}" target="_blank" rel="noopener noreferrer">商品页 ↗</a>` : ''}${i.store_url ? `<a class="route-link" href="${esc(i.store_url)}" target="_blank" rel="noopener noreferrer">门店资料 ↗</a>` : ''}</div><span class="route-arrow">→</span><div><div class="route-label">带回国内卖</div><strong>${esc(i.channel)}</strong><p>${i.quote.evidence_kind === 'order' ? '订单依据待执行核对' : '买家未确定'}</p><p>地址由订单生成</p></div></div>
    <div class="reference-note">${esc(i.reference_at || '尚未')} 核查：${esc(i.stock_note)}。参考价不代表旅行当天可买价。</div>
    <div class="decision"><div class="decision-line"><p>${d.profit === null ? `<strong>最高买价 / 净利润待核</strong><br>${esc(d.blockers.slice(0,2).join(' · '))}` : `<strong>预计净赚 ${esc(cny(d.profit))} / 件</strong> · 最高买价 ${esc(jpy(i.deal?.kind==='auction'?d.maxBidJPY:d.maxBuyJPY))} JPY${i.deal?.kind==='auction'?'（含税出价，另收拍卖费另计）':''}<br>${d.ready ? '销售净收入下降 10% 后：' + esc(cny(d.stressProfit)) + ' / 件' : esc(d.blockers.slice(0,2).join(' · '))}`}</p><div class="card-actions"><button class="text-button" data-action="archive">${i.archived ? '恢复观察' : '搁置'}</button>${!i.archived ? `<button class="text-button" data-action="select" ${!i.selected && !d.ready ? 'disabled title="先补全核价条件"' : ''}>${i.selected ? '移出清单' : '加入采购单'}</button>` : ''}<button class="secondary" data-action="edit">核价与判断 ↗</button></div></div></div>
  </article>`;
}
function empty() {
  if (!online) return '<div class="empty"><h3>暂时读不到观察池</h3><p>资料未被清空。恢复服务后点击“刷新资料”。</p></div>';
  if (query) return '<div class="empty"><h3>没有匹配的商品</h3><p>试试其他货号、商品名，或清空搜索。</p><button class="secondary" data-action="clear-search">清空搜索</button></div>';
  const content = tab === 'hot' ? ['还没有经过核实的热点款','从盯潮拿到发售或补货线索后，添加具体商品链接。先核实购买资格、准确规格和国内需求。','添加热点款'] : tab === 'selected' ? ['采购清单先留空','在观察池补全核价与履约条件，通过后才能加入。宁可少买，也不靠未知利润凑满行李箱。','回到观察池'] : tab === 'archived' ? ['暂时没有搁置项','不合适的候选可以搁置，已有核价记录会保留。','回到观察池'] : ['从一件准确商品开始','添加商品名与采购链接，再逐步补全规格、成本和销路。','添加商品'];
  return `<div class="empty"><span class="empty-icon" aria-hidden="true">${tab === 'hot' ? '⌁' : '↗'}</span><h3>${content[0]}</h3><p>${content[1]}</p><button class="secondary" data-action="${['selected','archived'].includes(tab) ? 'back' : 'add'}">${content[2]}</button></div>`;
}
const field = (name,label,value,type='text',wide=false) => `<label class="field ${wide ? 'wide' : ''}">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${type === 'number' ? 'min="0" step="any"' : ''} ${name === 'name' ? 'required maxlength="200"' : ''}></label>`;
function select(name,label,value,options) {return `<label class="field">${label}<select name="${name}">${options.map(([v,t])=>`<option value="${esc(v)}" ${v===value?'selected':''}>${t}</option>`).join('')}</select></label>`;}
function openEditor(item = null) {
  editorSession += 1;
  opener = document.activeElement;
  draft = item ? structuredClone(item) : {name:'',brand:'',pool:tab === 'hot'?'hot':'stable',code:'',color:'',size:'',source_name:'',source_url:'',address:'',channel:'得物',quote:{target_profit:100,units:1,evidence_kind:'unknown'}};
  const i=draft,q=i.quote;
  $('#editor-title').textContent = i.name ? i.name + ' · 核价' : '添加观察商品';
  $('#editor-fields').innerHTML = `<section class="form-section"><h3>商品与采购点</h3><div class="form-grid">${field('name','商品名',i.name)}${select('pool','观察类型',i.pool,[['stable','常卖款候选'],['hot','热点款候选']])}${field('code','准确货号',i.code)}${field('color','配色 / 版本',i.color)}${field('size','准确尺码 / 规格',i.size)}${select('channel','国内销售渠道',i.channel,[['得物','得物'],['闲鱼','闲鱼']])}${field('source_name','采购网站 / 门店名',i.source_name)}${field('source_url','具体商品页链接',i.source_url,'url')}${field('address','东京取货点 / 收货安排（勿填买家隐私）',i.address,'text',true)}</div><p>${esc(i.reason || '从准确商品开始；抽签、补货或联名信息还需逐项核实。')}</p></section>
    ${dealFields(i)}${visitFields(i)}<section class="form-section"><h3>每件赚多少</h3><div class="form-grid">${field('buy_jpy','含税采购价 · JPY（竞拍含另收费用，自动计算）',q.buy_jpy,'number')}${field('fx','1 JPY 兑换 CNY（含换汇成本）',q.fx,'number')}${field('net_cny','保守卖出净收入 · CNY（已扣平台费）',q.net_cny,'number')}${field('extra_cny','其余每件成本 · CNY',q.extra_cny,'number')}${field('target_profit','每件目标利润 · CNY（初始建议 100）',q.target_profit,'number')}${field('units','计划件数',q.units,'number')}${field('checked_at','实际采购价 / 库存核验日期',q.checked_at,'date')}</div><p>其余成本包含商业转售税费、日本与国内运费、包材、额外行李及分摊费用。已在净收入扣除的平台费不重复扣；未知项留空，确实为零才填 0。</p></section>
    <section class="form-section"><h3>国内销售依据</h3><div class="form-grid">${select('evidence_kind','依据类型',q.evidence_kind,[['unknown','尚未核实'],['ask','仅他人挂牌 / 平台展示价'],['sold','可核对的同规格成交记录'],['offer','真实买家询价 / 有效报价'],['order','自己的真实订单']])}${field('evidence_at','销售依据核验日期',q.evidence_at,'date')}<label class="field wide">依据摘要 / 来源链接（不含姓名、电话和地址）<textarea name="evidence" maxlength="2000">${esc(q.evidence)}</textarea></label></div><p>询价和历史成交用于估算，不是保证成交；当前报价与销售依据超过 72 小时，须重新核验。</p></section>
    <section class="form-section"><h3>这趟能否执行</h3><div class="check-grid">${[['stock','确认同款同码可买，含补货 / 抽签资格'],['delivery','确认 10 月 2—7 日东京取货及回国发货时限'],['tax','已核实商业转售手续、税费并计入成本'],['seller','已核实当前账号可售、费用及履约规则']].map(([key,label])=>`<label><input type="checkbox" name="${key}" ${q[key]?'checked':''}>${label}</label>`).join('')}</div></section>`;
  $('#form-error').textContent = '';
  $('#save-item').disabled = false;
  $('#editor').showModal();
  $('#editor').scrollTop = 0;
  liveDiagnosis();
}
function readForm() {
  const data = new FormData($('#item-form'));
  const item = structuredClone(draft);
  for(const key of ['name','pool','code','color','size','channel','source_name','source_url','address']) item[key] = String(data.get(key) || '').trim();
  for(const key of ['buy_jpy','fx','net_cny','extra_cny','target_profit','units']) item.quote[key] = data.get(key) === '' ? null : Number(data.get(key));
  for(const key of ['checked_at','evidence_at']) item.quote[key] = data.get(key) || null;
  for(const key of ['evidence_kind','evidence']) item.quote[key] = String(data.get(key) || '').trim();
  for(const key of ['stock','delivery','tax','seller']) item.quote[key] = data.has(key);
  item.visit = readVisit(data);
  item.deal = readDeal(data);
  if(item.deal.kind === 'auction') item.visit.mode = 'online';
  item.quote = purchaseQuote(item);
  return item;
}
function liveDiagnosis() {
  const item=readForm(),d=diagnose(item),auction=item.deal.kind==='auction';
  $('#auction-fields').hidden=!auction;
  $('#item-form').elements.buy_jpy.readOnly=auction;
  if(auction)$('#item-form').elements.buy_jpy.value=item.quote.buy_jpy??'';
  $('#live-diagnosis').innerHTML = `<div class="calc-grid"><div><small>含全部成本 / 件</small><strong>${esc(cny(d.cost))}</strong></div><div><small>预计净赚 / 件</small><strong>${esc(cny(d.profit))}</strong></div><div><small>${auction?'最高含税出价':'最高采购价'} · JPY</small><strong>${esc(jpy(auction?d.maxBidJPY:d.maxBuyJPY))}</strong></div></div><p>${d.stressProfit === null ? '填入有效成本和卖出净收入后计算。' : '净收入下降 10% 后，预计每件利润 ' + esc(cny(d.stressProfit)) + '。'}</p>${d.ready ? '<p><strong>核价条件齐全。保存后可加入采购单，合计仍受预算限制。</strong></p>' : `<ul>${d.blockers.map(b=>`<li>${esc(b)}</li>`).join('')}</ul>`}`;
}
function replaceItem(item) { const idx=items.findIndex(x=>x.id===item.id); if(idx<0)items.push(item);else items[idx]=item;render(); }
function closeEditor() { $('#editor').close(); if(opener?.isConnected)opener.focus(); }
async function save(event) {
  event.preventDefault();
  if ($('#save-item').disabled) return;
  const session = editorSession;
  const item=readForm();
  $('#save-item').disabled=true;
  $('#form-error').textContent='';
  try {
    const saved = await api('/api/sourcing' + (item.id ? '/' + encodeURIComponent(item.id) : ''), item.id?'PUT':'POST',item);
    replaceItem(saved);
    if (session === editorSession && $('#editor').open) closeEditor();
    notice('已保存「'+saved.name+'」到本地服务。核价通过仅用于采购判断，不代表已经下单或保证成交。');
  } catch(e) {
    if (session === editorSession && $('#editor').open) $('#form-error').textContent='保存失败：'+e.message+'。输入仍保留，可重试。';
    else notice('「'+item.name+'」保存失败：'+e.message+'。请重新打开该商品核对。');
  }
  finally { if (session === editorSession) $('#save-item').disabled=false; }
}
async function itemAction(event) {
  const button = event.target.closest('[data-action]');
  if(!button)return;
  const action=button.dataset.action;
  if(action==='add')return openEditor();
  if(action==='back')return setTab('all');
  if(action==='clear-search'){query='';$('#search').value='';return render();}
  const i=items.find(x=>x.id===button.closest('[data-id]')?.dataset.id);
  if(!i)return;
  if(action==='edit')return openEditor(i);
  const next=structuredClone(i);
  if(action==='archive'){next.archived=!next.archived;next.selected=false;}
  if(action==='select'){
    if(!i.selected && !diagnose(i).ready)return notice('核价条件已变化，请重新核实后加入采购单。');
    next.selected=!next.selected;
    if(next.selected){const trial=basket(items.map(x=>x.id===i.id?next:x));if(trial.unknown||trial.remaining<0)return notice('加入后会超过预算或存在未知成本，请先调整数量和采购单。');}
  }
  button.disabled=true;
  try{replaceItem(await api('/api/sourcing/'+encodeURIComponent(i.id),'PUT',next));notice();}
  catch(e){notice('保存失败：'+e.message);button.disabled=false;}
}
function exportCSV() {
  const plan=basket(items);
  if(!plan.ready || !online || !tripKnown || !plannerLedger().connected)return notice('清单条件已变化，请重新核价后导出。');
  const rows=[['东京采购清单（估算，非已下单）','2026-10-02 至 2026-10-07'],['商品','货号','配色','尺码','采购点','具体商品页','东京取货安排','销售渠道','数量','采购价 JPY/件（竞拍按下一加价且含另收拍卖费）','最高买价 JPY/件（竞拍为含税出价，另收拍卖费另计）','全部成本 CNY/件','预计净利 CNY/件','销售依据类型','销售依据','采购核验日期','销售核验日期','收件节点']];
  for(const i of plan.selected){const q=purchaseQuote(i),d=diagnose(i);rows.push([i.name,i.code,i.color,i.size,i.source_name,i.source_url,i.address,i.channel,q.units,q.buy_jpy,i.deal?.kind==='auction'?d.maxBidJPY:d.maxBuyJPY,d.cost,d.profit,q.evidence_kind,q.evidence,q.checked_at,q.evidence_at,'待真实订单生成；按订单寄平台指定点或买家']);}
  rows.push(['预算 CNY',10000],['本清单剩余采购全成本 CNY',plan.cost],['全趟已购与已填额外费用 CNY',plan.committed],['额外售后预留 CNY',3000],['预计利润合计 CNY',plan.profit]);
  const cell=v=>{let s=String(v??'');if(/^[=+\-@\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
  const blob=new Blob(['\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='东京采购清单-2026-10-02.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
}
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
$('#search').addEventListener('input',e=>{query=e.target.value;render();});
$('#items').addEventListener('click',itemAction);
$('#add-item').addEventListener('click',()=>openEditor());
$('#refresh').addEventListener('click',load);
$('#close-editor').addEventListener('click',closeEditor);
$('#item-form').addEventListener('submit',save);
$('#item-form').addEventListener('input',liveDiagnosis);
$('#item-form').addEventListener('change',event=>{
  const key=event.target.name;
  if(['visit_mode','visit_place','deal_kind'].includes(key)){
    if(key==='deal_kind' && event.target.value==='auction')$('#item-form').elements.visit_mode.value='online';
    for(const name of ['stock','delivery']) $('#item-form').elements[name].checked=false;
    $('#item-form').elements.checked_at.value='';
    liveDiagnosis();
    return;
  }
  if(!['name','code','color','size','source_url','source_name','address','channel'].includes(key)
    || event.target.value === draft[key]) return;
  const q=invalidateQuote(readForm().quote);
  for(const name of ['stock','delivery','tax','seller']) $('#item-form').elements[name].checked=q[name];
  for(const name of ['checked_at','evidence_at','evidence_kind','evidence']) $('#item-form').elements[name].value=q[name]??'';
  if(['source_name','source_url','address'].includes(key)){
    $('#item-form').elements.visit_place.value='none';
    for(const name of ['visit_lat','visit_lng','visit_release','visit_release_source']) $('#item-form').elements[name].value='';
  }
  draft[key]=event.target.value;
  if(key!=='channel')for(const name of ['deal_observed','deal_ends'])$('#item-form').elements[name].value='';
  liveDiagnosis();
});
$('#export').addEventListener('click',exportCSV);
// Broken remote product photos retain the item's name and link, rather than a broken image.
$('#items').addEventListener('error',event=>{if(event.target.tagName==='IMG')event.target.parentElement.innerHTML='<span aria-hidden="true">◇</span>';},true);
document.addEventListener('planner:updated',()=>render(false));
await initPlanner(()=>items,openEditor);
initMarket(()=>({items,online}),openEditor);
await load();
