import {planDay,defaultSettings,resolveVisit,estimateMinutes,navURL,clock,japanDate} from './tokyo-planner.mjs';
import {diagnose} from './sourcing-model.mjs';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const money=v=>v===null?'待核':`¥${v.toLocaleString('zh-CN',{maximumFractionDigits:2})}`;
const link=(url,text)=>`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${text} ↗</a>`;
let places=[],days=[],s=defaultSettings(),mode='buy',getItems=()=>[],editItem=()=>{},result,map,layers,pick=null,busy=false,connected=false,dirty=false,recordDraft=null,initialPlan=true;
const location=p=>({id:p.id,name:p.name,lat:p.lat,lng:p.lng,...(p.address?{address:p.address}:{})});
const field=(name,label,value,type='text',extra='')=>`<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${extra}></label>`;
async function api(path,method='GET',body){
 const r=await fetch(path,{method,headers:{'Content-Type':'application/json'},cache:'no-store',signal:AbortSignal.timeout(12000),...(body?{body:JSON.stringify(body)}:{})});
 const v=await r.json();if(!r.ok)throw new Error(Array.isArray(v.detail)?v.detail.map(x=>x.msg).join('；'):v.detail||'本地服务未连接');return v;
}
function error(text=''){ $('#planner-error').textContent=text; }
function selectPlace(name,label){return `<label class="field">${label}<select name="${name}">${places.map(p=>`<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('')}<option value="custom">地图选点 / 自定义</option></select></label>`;}
function settingsHTML(){return `<div class="planner-heading"><div><p class="eyebrow">TOKYO / DAILY BUYING ROUTE</p><h2 id="day-heading">今天，该买什么？</h2><p>店铺落在地图上，商品排进时间表。<br>先看预算内的预计净利润，再决定值不值得跑这一趟。</p></div><span class="badge">10.02—10.07 · 日本时间</span></div>
<form id="planner-settings" class="planner-controls"><div class="form-grid">${field('date','采购日期 · 日本时间',s.date,'date','required min="2026-10-02" max="2026-10-07"')}${field('start_time','出发 / 继续采购时间',s.start_time,'time','required')}${field('end_time','最晚返回时间',s.end_time,'time','required')}${field('limit_cny','今天采购全成本上限 · CNY',s.limit_cny,'number','required min="0" max="10000" step="0.01"')}${selectPlace('start_place','从哪里出发 / 当前所在')}${selectPlace('end_place','最后回到哪里')}${field('extra_cny','今天额外费用 · CNY（无则填 0）',s.extra_cny,'number','min="0" step="0.01" placeholder="交通等，未计入商品的部分"')}<div class="field"><span>优化目标</span><strong>预算内净利润最高</strong><small>同收益优先更早返回</small></div></div>
<details id="endpoint-details"><summary>修改具体起终点 / 酒店，或在地图上点选</summary><div class="endpoint-grid">${['start','end'].map(k=>`<div><div class="form-grid">${field(k+'_name',k==='start'?'起点名':'终点名',s[k].name)}${field(k+'_lat','纬度',s[k].lat,'number','required min="35" max="36.5" step="any"')}${field(k+'_lng','经度',s[k].lng,'number','required min="138.5" max="140.5" step="any"')}</div><button type="button" class="text-button" data-pick="${k}">在地图上选择${k==='start'?'起点':'终点'}</button></div>`).join('')}</div></details>
<p class="planner-note">起终点未确认，初始用东京站往返 10:00—19:00；每天可修改。单件报价已包含税费、运费、包材等，当日额外费用只填未分摊部分。总资金 10,000 元，另预留 3,000 元；机酒另计。</p>
<div class="planner-actions"><button type="submit" class="primary" id="make-buy-plan">今天该买什么 ↗</button><button type="button" class="secondary" id="make-research-plan">先排核价路线</button><span id="planner-save-state" class="planner-save-state"></span><button type="button" class="text-button" id="reload-plans">重新读取已保存日计划</button></div></form>
<div class="planner-body"><div class="planner-map-column"><div id="tokyo-map" class="tokyo-map" aria-label="东京采购点互动地图"></div><div class="map-caption"><div class="map-key"><span><b></b>采购日程</span><span><b class="lead"></b>待核线索</span><span><b class="base"></b>起终点</span></div><p id="map-status">点位是地址附近参考位置，楼层与入口看门店资料；虚线仅表示访问顺序。</p><div class="map-tools"><button type="button" class="text-button" id="fit-map">显示全部采购点</button>${link('https://www.openstreetmap.org/fixthemap','反馈地图问题')}</div></div></div><div id="planner-itinerary" class="planner-itinerary" aria-live="polite"></div></div>
<div id="day-money" class="day-money"></div><div id="trip-money" class="trip-money"></div><div id="planner-error" class="planner-error" role="alert"></div>
<div class="planner-bottom"><div><details open><summary>参与规划的商品 · 最多 10 项</summary><div id="planner-candidates"></div></details><details><summary>校准交通耗时 · 分钟</summary><p class="planner-note">默认仅粗估步行：直线距离 × 1.35，以 4 km/h 计算，上调到 5 分钟。点导航查真实路线，按当天结果填写；去程与返程分开记录。校准后点击上方按钮保存重排。</p><div id="planner-travel"></div></details></div><div><details open><summary>今天实购 / 跳过记录</summary><div id="planner-records"></div></details><details><summary>其他日期与全趟资金</summary><div id="planner-other-days"></div></details><details><summary>这条方案怎么算出来</summary><p class="planner-note">比较勾选商品的整组件数（不自动拆单），合并同店普通商品，以填写的交通耗时、营业时间、停留时长和官方发售时点计算可行组合。最多 10 项；结果仅在这些候选和估计内最优。排队、临时休店、实时交通及旅行当天库存需要重新核对。线上下单任务暂安排在当天起点完成。</p><p class="planner-note">业务 ROI =（卖出净收入 − 采购及履约全成本 − 额外费用）÷ 全部投入成本。未售显示预期收入；已结算单独记录。不使用旧行程机酒估价，也不把预留资金算作费用。</p></details></div></div>`;}
export async function initPlanner(get,edit){
 getItems=get;editItem=edit;
 try{
  [places,days]=await Promise.all([api('/tokyo-places.json'),api('/api/day-plans')]);connected=true;
  const today=japanDate(),date=today>='2026-10-02'&&today<='2026-10-07'?today:'2026-10-02';
  s=structuredClone(days.find(d=>d.date===date)||{...defaultSettings(),date});
  $('#day-planner').innerHTML=settingsHTML();syncForm();
  $('#planner-settings').addEventListener('submit',async e=>{e.preventDefault();await generate('buy');});
  $('#make-research-plan').addEventListener('click',()=>generate('research'));
  $('#reload-plans').addEventListener('click',async()=>{
   if(busy)return;setBusy(true);
   try{days=await api('/api/day-plans');s=structuredClone(days.find(d=>d.date===s.date)||{...defaultSettings(),date:s.date});dirty=false;connected=true;syncForm();error();render();}
   catch(e){error('读取失败：'+e.message);connected=false;}
   finally{setBusy(false);}
  });
  $('#planner-settings').addEventListener('change',changeSettings);
  $('#day-planner').addEventListener('click',actions);
  $('#planner-candidates').addEventListener('change',e=>{if(!e.target.matches('[data-candidate]'))return;s.candidate_ids=[...document.querySelectorAll('[data-candidate]:checked')].map(x=>x.dataset.candidate);dirty=true;render();});
  $('#planner-travel').addEventListener('change',e=>{const key=e.target.dataset.leg;if(!key)return;if(!e.target.checkValidity())return e.target.reportValidity();if(e.target.value==='')delete s.travel[key];else s.travel[key]=Number(e.target.value);dirty=true;render();});
  document.addEventListener('sourcing:updated',render);
  setupMap();setupRecordDialog();render();
 }catch(e){$('#day-planner').innerHTML=`<div class="empty"><h2>日计划暂未连接</h2><p>${esc(e.message)}。启动最新服务后刷新页面，已有资料仍保存在本地。</p></div>`;}
}
function syncForm(){
 const f=$('#planner-settings');for(const key of ['date','start_time','end_time','extra_cny','limit_cny'])f.elements[key].value=s[key]??'';
 for(const key of ['start','end']){
  const p=s[key];f.elements[key+'_place'].value=places.some(x=>x.id===p.id)?p.id:'custom';
  for(const part of ['name','lat','lng'])f.elements[key+'_'+part].value=p[part];
 }
}
function changeSettings(e){
 if(busy)return;
 const f=$('#planner-settings'),key=e.target.name;
 if(!e.target.checkValidity()){e.target.reportValidity();return;}
 if(key==='date'){
  s=structuredClone(days.find(d=>d.date===e.target.value)||{...defaultSettings(),date:e.target.value,start:s.start,end:s.end});dirty=false;syncForm();render();return;
 }
 if(['start_time','end_time'].includes(key))s[key]=e.target.value;
 if(['extra_cny','limit_cny'].includes(key))s[key]=e.target.value===''?null:Number(e.target.value);
 for(const endpoint of ['start','end']){
  if(key===endpoint+'_place'){
   const p=places.find(p=>p.id===e.target.value);if(p)s[endpoint]=location(p);else s[endpoint]={...s[endpoint],id:endpoint+'-custom',address:''};
   s.travel={};syncForm();$('#endpoint-details').open=e.target.value==='custom';
  }else if(key.startsWith(endpoint+'_')&&!key.endsWith('_time')){
   s[endpoint]={id:`${endpoint}:${f.elements[endpoint+'_lat'].value},${f.elements[endpoint+'_lng'].value}`,name:f.elements[endpoint+'_name'].value||'自定义位置',lat:Number(f.elements[endpoint+'_lat'].value),lng:Number(f.elements[endpoint+'_lng'].value)};s.travel={};syncForm();
  }
 }
 dirty=true;render();
}
function setBusy(value){busy=value;document.querySelectorAll('#planner-settings input,#planner-settings select,#planner-settings button,#planner-candidates input,#planner-travel input,#planner-itinerary button,#planner-records button,#execution-form input,#execution-form button').forEach(x=>x.disabled=value);}
async function persist(){
 if(busy)return false;setBusy(true);error();let written=false;
 try{
  const snapshot=structuredClone(s),saved=await api('/api/day-plans/'+snapshot.date,'PUT',snapshot);
  days=days.filter(d=>d.date!==saved.date);days.push(saved);s=saved;dirty=false;written=true;
  days=await api('/api/day-plans');s=structuredClone(days.find(d=>d.date===saved.date)||saved);syncForm();connected=true;return true;
 }catch(e){error(written?'记录已保存，但全趟账暂未核对：'+e.message+'。请重新读取日计划后再安排采购。':'保存失败：'+e.message+'。当前输入还在页面中，请重试。');connected=false;return false;}
 finally{setBusy(false);$('#planner-save-state').textContent=dirty?'修改尚未保存':'已保存到本地';}
}
async function generate(nextMode){
 if(!$('#planner-settings').reportValidity()||busy)return;
 if(await persist()){mode=nextMode;render();}
}
function render(){
 if(!$('#planner-itinerary'))return;
 if(initialPlan&&getItems().length){mode=getItems().some(i=>!i.archived&&diagnose(i).ready)?'buy':'research';initialPlan=false;}
 result=planDay(getItems(),s,days,places,mode);
 const f=result.forecast;
 $('#planner-save-state').textContent=!connected?'服务未连接':dirty?'修改尚未保存':days.some(d=>d.date===s.date)?'本地日计划 · '+s.date:'默认草案 · 尚未保存';
 $('#make-buy-plan').setAttribute('aria-pressed',String(mode==='buy'));$('#make-research-plan').setAttribute('aria-pressed',String(mode==='research'));
 const state=`${result.future?'旅行日期预测 · 当天重新核验价格与库存。':'执行前确认即时库存与到店条件。'} ${mode==='research'?'本轮只核价，不建议按路线直接买入。':'按已核实报价估计，尚未下单。'}`;
 $('#planner-itinerary').innerHTML=`<p class="eyebrow">${esc(s.date)} / JST</p><h3>${mode==='research'?'先核价，再决定买不买':result.items.length?`今天安排 ${result.items.length} 款 · ${result.route.stops.length} 站`:'今天暂没有可执行买单'}</h3><div class="route-state ${!result.items.length?'warning':''}">${esc(result.error||state)}</div>${result.route.stops.length?itinerary():`<div class="route-empty"><strong>${mode==='research'?'当天尚未排出可走路线':'先把买价和销路核齐'}</strong>${mode==='research'?'检查地图点、营业时间与当天时段；也可减少候选。':'可以先点“先排核价路线”，去对应店铺询货。补齐同款同码、库存与销售依据后，再生成购买方案。'}</div>`}`;
 const values=[['今日全部投入',f.cost,'实购 + 待购 + 当日额外费用'],['预计卖出净收入',f.net,'已扣平台费；预期不等于结算'],['预计净利润',f.profit,'收入 − 全部投入'],['今日业务 ROI',f.roi===null?null:f.roi+'%','机票和酒店另计']];
 $('#day-money').innerHTML=values.map(([label,v,note])=>`<div><small>${label}</small><strong>${typeof v==='string'?esc(v):money(v)}</strong><em>${note}</em></div>`).join('');
 $('#trip-money').innerHTML=`全趟已记录实购 <strong>${money(f.recordedCost)}</strong> · 已结算净收入 <strong>${money(f.settled)}</strong> · 扣除全部已填额外费用、今日方案及 3,000 元预留后，可继续安排 <strong>${money(f.remaining)}</strong>${!f.extraKnown?'（另有未知费用）':''}<br>已记录全趟 + 今日购买方案：总投入 ${money(f.tripCost)} · 预计净利润 ${money(f.tripProfit)} · 业务 ROI ${f.tripROI===null?'待核':f.tripROI+'%'}。${mode==='research'?'核价路线不生成采购收益预测。':''}`;
 renderCandidates();renderRecords();renderTravel();renderMap();
 document.dispatchEvent(new CustomEvent('planner:updated'));
}
function itinerary(){
 let prev=s.start;
 const rows=result.route.stops.map((n,k)=>{
  const from=prev;prev=n;
  return `<article class="stop-card" id="stop-${k}"><span class="stop-number">${k+1}</span><p class="stop-time">${n.release===null?'约 ':''}${clock(n.at,n.release!==null)} — ${clock(n.until)}</p><h4>${esc(n.name)}</h4><p>${esc(n.area||'线上下单 / 自定义点')} · 预留 ${n.duration} 分钟</p><p>${esc(n.address||'位置已在地图标注')}</p><div class="stop-links">${link(navURL(from,n),'这一段步行')}${link(navURL(from,n,'transit'),'查地铁')}</div><p>从上一点约 ${n.travel_mins} 分钟${s.travel[`${from.id}>${n.id}`]===undefined?' · 粗估，需核对':' · 已按填写值校准'}${n.release!==null?'；发售前到位，系统时刻不保证抢购成功':''}</p>${n.items.map(i=>skuHTML(i)).join('')}<button class="text-button" data-continue="${k}">从这一站继续重排 ↗</button></article>`;
 });
 return rows.join('')+`<div class="route-finish">约 ${clock(Math.ceil(result.route.finish))} 返回 ${esc(s.end.name)} · 交通合计约 ${Math.ceil(result.route.travel)} 分钟<div class="stop-links">${link(navURL(prev,s.end),'返回步行')}${link(navURL(prev,s.end,'transit'),'返回地铁')}</div></div>`;
}
function skuHTML(i){const d=diagnose(i);return `<div class="stop-sku"><strong>${esc(i.name)} × ${i.quote.units}</strong><p>${esc(i.code)} · ${esc(i.color)} · ${esc(i.size||'尺码待核')}<br>买：${esc(i.source_name)} → 卖：${esc(i.channel)}，收件点由真实订单生成</p><p>${mode==='buy'?`${i.deal?.kind==='auction'?'最高含税出价':'最高买价'} ¥${i.deal?.kind==='auction'?d.maxBidJPY:d.maxBuyJPY} JPY / 件${i.deal?.kind==='auction'?'（另收拍卖费另计）':''} · 全成本 ${money(d.cost)} / 件 · 预计净赚 ${money(d.profit)} / 件`:'本轮仅核价；买价、库存与国内净收入需复核'}</p>${i.visit?.release_at&&i.visit?.release_source?link(i.visit.release_source,'发售时间来源'):''}<div class="stop-sku-actions">${link(i.source_url,'购买页面')}<button class="text-button" data-edit-sku="${esc(i.id)}">核价 / 改地图点</button><button class="text-button" data-record="${esc(i.id)}">记录实购</button><button class="text-button" data-skip="${esc(i.id)}">今天跳过</button></div></div>`;}
function renderCandidates(){
 const active=getItems().filter(i=>!i.archived);
 $('#planner-candidates').innerHTML=active.map(i=>{
  const ex=result.exclusions.find(x=>x.item.id===i.id),d=diagnose(i);
  return `<label class="candidate-row"><input type="checkbox" data-candidate="${esc(i.id)}" ${!s.candidate_ids||s.candidate_ids.includes(i.id)?'checked':''}><span>${esc(i.name)}<small>${esc(i.code)} · ${esc(ex?.reason||(d.ready?'核价已齐，可参与购买比较':'先补齐核价与采购点'))}</small></span></label>`;
 }).join('')||'<p class="planner-note">先在下方观察池添加准确商品。</p>';
}
function renderRecords(){
 $('#planner-records').innerHTML=(s.records||[]).map(r=>`<div class="record-row"><strong>${esc(r.name||r.item_id)}</strong><br>${r.status==='skipped'?'今天跳过':`实购 ${r.units} 件 · 全成本 ${money(r.cost_cny)}<br>预期净收入 ${money(r.expected_net_cny??null)} · ${r.actual_net_cny===null||r.actual_net_cny===undefined?'尚未结算':'已结算 '+money(r.actual_net_cny)}`}<br><button class="text-button" data-record="${esc(r.item_id)}">修改记录</button> · <button class="text-button" data-remove-record="${esc(r.item_id)}">撤回记录</button></div>`).join('')||'<p class="planner-note">到店后在商品旁记录实购或跳过。实购记录采用当时的成本快照，改报价不会回写过去。</p>';
 $('#planner-other-days').innerHTML=days.filter(d=>d.date!==s.date).map(d=>`<div class="record-row"><button class="text-button" data-date="${esc(d.date)}">${esc(d.date)} ↗</button> · ${(d.records||[]).filter(r=>r.status==='bought').length} 条实购<br>额外费用 ${money(d.extra_cny)}</div>`).join('')||'<p class="planner-note">其他日期的实购与已填额外费用会一起占用全趟资金。未来计划也会预留已填费用。</p>';
}
function renderTravel(){
 const nodes=[s.start,...result.nodes,s.end],pairs=new Map();
 for(const a of nodes)for(const b of nodes)if(a.id!==b.id&&!pairs.has(`${a.id}>${b.id}`))pairs.set(`${a.id}>${b.id}`,[a,b]);
 $('#planner-travel').innerHTML=[...pairs].map(([key,[a,b]])=>`<label class="travel-row"><span>${esc(a.name)} → ${esc(b.name)}<br>${link(navURL(a,b,'transit'),'查交通')} · 粗估步行 ${estimateMinutes(a,b)} 分钟</span><input aria-label="${esc(a.name+' 到 '+b.name+' 分钟')}" type="number" min="0" max="1440" step="1" placeholder="${estimateMinutes(a,b)}" value="${esc(s.travel[key]??'')}" data-leg="${esc(key)}"></label>`).join('')||'<p class="planner-note">有地图采购点后，可以填写每一段耗时。</p>';
}
function setupMap(){
 if(!window.L){$('#tokyo-map').textContent='地图组件未加载；右侧地址和导航仍可使用。';return;}
 map=L.map('tokyo-map',{scrollWheelZoom:false}).setView([35.697,139.775],13);
 const tiles=L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
 tiles.on('tileerror',()=>{$('#map-status').textContent='部分底图未加载，点位与右侧地址仍可用。虚线是顺序示意，导航请打开逐段地图。';});
 layers=L.layerGroup().addTo(map);
 map.on('click',e=>{
  if(!pick||busy)return;
  const key=pick;s[key]={id:`${key}:${e.latlng.lat.toFixed(5)},${e.latlng.lng.toFixed(5)}`,name:`地图自选${key==='start'?'起点':'终点'}`,lat:Number(e.latlng.lat.toFixed(5)),lng:Number(e.latlng.lng.toFixed(5))};s.travel={};pick=null;dirty=true;syncForm();render();$('#map-status').textContent=`已选择 ${s[key].lat}, ${s[key].lng}；可在起终点设置中改名。`;
 });
 $('#fit-map').addEventListener('click',()=>{const points=[s.start,s.end,...getItems().filter(i=>!i.archived).map(i=>resolveVisit(i,places,s.start,s.date)).filter(v=>!v.error)];map.fitBounds(points.map(p=>[p.lat,p.lng]),{padding:[35,35],maxZoom:15});});
}
function renderMap(){
 if(!map)return;layers.clearLayers();const groups=new Map();
 for(const i of getItems().filter(x=>!x.archived)){
  const v=resolveVisit(i,places,s.start,s.date);if(v.error)continue;if(!groups.has(v.id))groups.set(v.id,{...v,items:[]});groups.get(v.id).items.push(i);
 }
 const marker=(p,text,cls,popup)=>{
  const m=L.marker([p.lat,p.lng],{icon:L.divIcon({className:'map-marker '+cls,html:esc(text),iconSize:[30,30],iconAnchor:[15,15]}),title:p.name}).addTo(layers);
  if(popup){const el=document.createElement('div');el.innerHTML=popup;el.addEventListener('click',e=>{const id=e.target.closest('[data-popup-edit]')?.dataset.popupEdit;if(id)editItem(getItems().find(i=>i.id===id));});m.bindPopup(el);}return m;
 };
 for(const [id,p] of groups){const idx=result.route.stops.findIndex(n=>n.id===id);marker(p,idx<0?'?':idx+1,idx<0||mode==='research'?'lead':'',`<strong>${esc(p.name)}</strong><p>${esc(p.address)}</p>${p.items.map(i=>`<button data-popup-edit="${esc(i.id)}">${esc(i.name)} · 核价 / 定位 ↗</button>`).join('<br>')}<p>${p.source?link(p.source,'门店资料'):''}</p><small>${esc(p.note||'当天库存与到店条件需核实')}</small>`);}
 marker(s.start,'起','base',`<strong>${esc(s.start.name)}</strong>`);
 if(s.end.lat!==s.start.lat||s.end.lng!==s.start.lng)marker(s.end,'终','base',`<strong>${esc(s.end.name)}</strong>`);
 if(result.route.stops.length)L.polyline([s.start,...result.route.stops,s.end].map(p=>[p.lat,p.lng]),{color:mode==='research'?'#9b641a':'#315fce',weight:3,dashArray:'6 8',interactive:false}).addTo(layers);
}
async function actions(e){
 const b=e.target.closest('button');if(!b||busy)return;
 if(b.dataset.pick){pick=b.dataset.pick;$('#map-status').textContent=`请在地图上点击${pick==='start'?'起点':'终点'}位置。`;return;}
 if(b.dataset.editSku){editItem(getItems().find(i=>i.id===b.dataset.editSku));return;}
 if(b.dataset.record){openRecord(b.dataset.record);return;}
 if(b.dataset.skip){
  const i=getItems().find(i=>i.id===b.dataset.skip);if(!i)return;
  s.records=[...(s.records||[]).filter(r=>r.item_id!==i.id),{item_id:i.id,name:i.name,code:i.code,channel:i.channel,status:'skipped',units:0,cost_cny:0,recorded_at:new Date().toISOString()}];dirty=true;await persist();render();return;
 }
 if(b.dataset.removeRecord){s.records=s.records.filter(r=>r.item_id!==b.dataset.removeRecord);dirty=true;await persist();render();return;}
 if(b.dataset.continue!==undefined){const n=result.route.stops[Number(b.dataset.continue)];s.start=n.online?s.start:{...location(n),id:`current:${n.lat},${n.lng}`,name:n.name};s.start_time=clock(Math.ceil(n.until));s.travel={};dirty=true;syncForm();render();$('#endpoint-details').open=true;error('已填入这一站与预计离店时间。请改成实际所在位置和时间，再点击上方按钮保存重排。');return;}
 if(b.dataset.date){s=structuredClone(days.find(d=>d.date===b.dataset.date));dirty=false;syncForm();render();}
}
function setupRecordDialog(){
 const el=document.createElement('dialog');el.id='execution-dialog';el.setAttribute('aria-labelledby','execution-title');el.innerHTML='<form id="execution-form" class="execution-form"></form>';document.body.append(el);el.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 $('#execution-form').addEventListener('submit',async e=>{
  e.preventDefault();if(busy)return;
  const f=new FormData(e.target),r={...recordDraft,color:String(f.get('record_color')||'').trim(),size:String(f.get('record_size')||'').trim(),status:'bought',units:Number(f.get('record_units')),cost_cny:Number(f.get('record_cost')),expected_net_cny:f.get('record_expected')===''?null:Number(f.get('record_expected')),actual_net_cny:f.get('record_actual')===''?null:Number(f.get('record_actual')),recorded_at:new Date().toISOString()};
  s.records=[...(s.records||[]).filter(x=>x.item_id!==r.item_id),r];dirty=true;
  if(await persist())$('#execution-dialog').close();else $('#execution-error').textContent=$('#planner-error').textContent;render();
 });
}
function openRecord(id){
 const existing=s.records.find(r=>r.item_id===id),i=getItems().find(i=>i.id===id);
 recordDraft=existing?{...existing}:{item_id:id,name:i.name,code:i.code,color:i.color,size:i.size,channel:i.channel};
 const d=i?diagnose(i):null;
 $('#execution-form').innerHTML=`<div class="dialog-head"><div><p class="eyebrow">${esc(s.date)} / 实际采购</p><h2 id="execution-title">${esc(recordDraft.name)}</h2></div><button class="icon-button" type="button" id="close-execution" aria-label="关闭采购记录">×</button></div><div class="form-grid">${field('record_color','实购配色 / 版本',recordDraft.color)}${field('record_size','实购尺码 / 规格',recordDraft.size)}${field('record_units','今天累计实买件数',existing?.status==='bought'?existing.units:1,'number','required min="1" max="1000" step="1"')}${field('record_cost','这几件实际全成本合计 · CNY',existing?.status==='bought'?existing.cost_cny:null,'number','required min="0.01" step="0.01"')}${field('record_expected','这几件预计卖出净收入合计 · CNY',existing?.expected_net_cny??null,'number','min="0" step="0.01"')}${field('record_actual','已全部售出并结算的净收入 · CNY',existing?.actual_net_cny??null,'number','min="0" step="0.01"')}</div><p class="planner-note">录入这几件的合计，修改时覆盖今天累计记录。成本包含采购、税费和履约；上方当日额外费用不重复填。未售或仅部分售出时，“已全部售出并结算”留空。${d?.ready?'当前报价参考：全成本 '+money(d.cost)+' / 件，预计净收入 '+money(i.quote.net_cny)+' / 件。':''}</p><p class="planner-note">保存只记账。已购商品今天不会重复推荐，剩余目标件数可以次日继续安排。</p><div class="form-error" id="execution-error" role="alert"></div><div class="dialog-actions"><button type="submit" class="primary">保存实购并重算</button></div>`;
 $('#close-execution').addEventListener('click',()=>{if(!busy)$('#execution-dialog').close();});$('#execution-dialog').showModal();
}
export function visitFields(item){
 const v=item.visit||{},p=v.place_id||places.find(p=>p.product_urls?.includes(item.source_url))?.id||'none';
 const at=v.release_at?new Date(new Date(v.release_at).getTime()+9*3600000).toISOString().slice(0,19):'';
 return `<section class="form-section"><h3>东京地图与购买时段</h3><div class="form-grid"><label class="field">购买方式<select name="visit_mode"><option value="store" ${v.mode!=='online'?'selected':''}>到店购买 / 取货</option><option value="online" ${v.mode==='online'?'selected':''}>线上下单（在当天起点完成）</option></select></label><label class="field">地图采购点<select name="visit_place"><option value="none">待定位</option>${places.filter(p=>p.id!=='tokyo-station').map(x=>`<option value="${esc(x.id)}" ${p===x.id?'selected':''}>${esc(x.name+' · '+x.area)}</option>`).join('')}<option value="custom" ${p==='custom'?'selected':''}>自定义东京店铺</option></select></label>${field('visit_lat','自定义纬度（东京范围）',v.lat,'number','min="35" max="36.5" step="any"')}${field('visit_lng','自定义经度（东京范围）',v.lng,'number','min="138.5" max="140.5" step="any"')}${field('visit_open','开店时间（空则用门店资料）',v.open_time,'time')}${field('visit_close','闭店时间（空则用门店资料）',v.close_time,'time')}${field('visit_duration','到店 / 排队预留分钟',v.duration_min||30,'number','required min="1" max="240" step="1"')}${field('visit_release','官方发售时刻 · 日本时间（无则留空）',at,'datetime-local','step="1"')}${field('visit_release_source','官方发售时间来源链接',v.release_source,'url')}</div><p>自定义门店需填写坐标、营业时间和准确地址。普通购物只估计到店时间；秒级时刻来自官方发售资料，仍需自行按时购买。</p></section>`;
}
export function readVisit(data){
 return {mode:data.get('visit_mode'),place_id:data.get('visit_place'),lat:data.get('visit_lat')===''?null:Number(data.get('visit_lat')),lng:data.get('visit_lng')===''?null:Number(data.get('visit_lng')),open_time:data.get('visit_open'),close_time:data.get('visit_close'),duration_min:Number(data.get('visit_duration')),release_at:data.get('visit_release')?data.get('visit_release')+'+09:00':null,release_source:data.get('visit_release_source')||''};
}

export function plannerLedger(){return {days:[...days.filter(d=>d.date!==s.date),s],connected:connected&&!busy};}

export function openHolding(date,id){
 if(busy)return '日计划正在保存，请完成后再核对批次。';
 if(dirty)return '日计划还有未保存的修改，请先保存再核对批次。';
 if(!connected||!$('#execution-dialog'))return '请先重新连接日计划，再核对批次。';
 const day=plannerLedger().days.find(d=>d.date===date);
 if(!day?.records?.some(r=>r.item_id===id))return '该批次已变化，请重新读取日计划。';
 s=structuredClone(day);syncForm();render();openRecord(id);return '';
}
