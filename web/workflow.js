import {diagnose, recent} from './sourcing-model.mjs';
import {buyDecision} from './market-decisions.mjs';
import {deskBasket, remainingPurchase} from './tokyo-planner.mjs';

const $ = selector => document.querySelector(selector);
const steps = [
  {
    id:'demand', title:'确认销路', caption:'卖给谁，净收多少', state:'可记录销售依据',
    question:'这个准确规格，有什么可靠的销售依据？',
    result:'拿到一份可复查的销售依据。',
    input:'从一个熟悉品类开始，写清货号、配色、尺码或版本。在自己的得物或闲鱼账号里，区分挂牌、成交、有效报价和真实订单。',
    output:'准确规格 ＋ 销售渠道 ＋ 保守净收入 ＋ 证据来源与核验日期',
    ai:'读链接、截图和日文资料；提取规格，找出可比样本与缺项。',
    system:'保留销售依据、核验日期和卖家条件；过期资料需要重核。',
    person:'核对确实是同款，确认自己的账号能卖、费用扣到哪、什么时候能交付。',
    gate:'同规格成交或有效需求有出处，卖家净收入与履约条件已确认。只有热度或挂牌价时，继续核实。',
    action:'去观察池补销售依据', href:'/#catalog',
  },
  {
    id:'ceiling', title:'算收购上限', caption:'最多花多少，买几件', state:'可计算采购上限',
    question:'留出目标利润后，最多可以花多少钱收？',
    result:'得到可执行的最高采购价与数量上限。',
    input:'沿用刚核实的净收入，补上汇率、运输、税费、平台相关费用与目标利润。拍卖另算加价和买方费用。',
    output:'最高采购价 ＝ 保守净收入 − 采购以外成本 − 目标利润（统一币种后计算）',
    ai:'整理费用说明，指出漏项，解释哪一项成本吃掉了利润。',
    system:'用确定性公式计算采购上限、竞价上限和全趟剩余资金。',
    person:'确认费用，并决定最多持有多少件、能等多久、能接受多少损失。',
    gate:'费用未知时不按零计算；采购上限必须为正，数量受经营资金和售后预留约束。',
    action:'去核价表算采购上限', href:'/#catalog',
  },
  {
    id:'source', title:'定向找货', caption:'盯什么，在哪买', state:'自动监控待接入',
    question:'哪些日本来源能满足这份收购标准？',
    result:'留下少量值得跟进的商品、补货或拍卖。',
    input:'带着准确规格和采购上限，查询商品页、门店、官方发售或拍卖。区分页面有货、指定尺码有货和门店能取货。',
    output:'具体商品链接 / 门店 ＋ 准确规格 ＋ 当前采购条件 ＋ 核验时刻',
    ai:'翻译日文、匹配同款、提取发售资格；接入监测后过滤无关变化。',
    system:'现有信息源可手工查询；固定货盘的价格、补货和截止监控尚待接入。',
    person:'核实库存、品相、参与资格和取货日期，判断是否值得继续。',
    gate:'含费买价在上限内，货物与销售端完全匹配；发售和拍卖条件确实允许本次参与。',
    action:'打开货源与查询入口', href:'/#sources',
  },
  {
    id:'purchase', title:'核验采购', caption:'合格后，再排东京路线', state:'可排路线、记实购',
    question:'现在能买、来得及拿货，而且没有超预算吗？',
    result:'执行一份有数量、有上限、有交期的采购单。',
    input:'采购前重新核价。线上购买确认交付点；到店购买关联东京采购点，核对营业时间、交通和排队。',
    output:'采购地点与时段 ＋ 最高出价 ＋ 件数 ＋ 实际支付与取货记录',
    ai:'汇总参与条件和临时变化，解释需要跳过或调整的商品。',
    system:'比较输入候选的时间与预算，生成日计划；记录实际买到的数量和成本。',
    person:'在平台或店铺完成购买，核对实物与凭证；买到多少就记录多少。',
    gate:'重新确认库存、报价、资格和期限。东京地图是执行工具；交通与排队耗时需按现场校准。',
    action:'打开东京地图与日计划', href:'/#day-planner',
  },
  {
    id:'sell', title:'上架卖出', caption:'按实物描述，跟进退出', state:'可核对持货卖价',
    question:'已买到的货，怎么卖、按什么价格卖？',
    result:'把真实持货转成可履约的销售。',
    input:'对照实购物品拍照，确认配件、成色和规格；再核对当前卖家净收入、交付期限与这批货的成本。',
    output:'真实商品描述 ＋ 当前销售报价 ＋ 发货记录 ＋ 待结算批次',
    ai:'根据实物资料起草标题、描述和答复，提示缺件或版本差异。',
    system:'现有看板比较实际成本和当前销售依据，展示达到利润目标的批次。',
    person:'审核描述，在自己的平台账号刊登、沟通和发货，决定是否调价或止损。',
    gate:'商品描述与实物一致、库存数量真实、交期可履约；预计卖价仍需实际成交验证。',
    action:'查看持货与卖出建议', href:'/#market-board',
  },
  {
    id:'review', title:'回款复盘', caption:'算实赚，也看压货', state:'可记录整批结算',
    question:'实际赚了多少，钱占用了多久？',
    result:'用真实结果更新下一次的收购标准。',
    input:'记录扣费后的实际净收入，保留退款、退货和售后成本。未售库存继续计入占资，不只复盘卖掉的货。',
    output:'实际净利润 ＋ 持货 / 回款时间 ＋ 未售占资 ＋ 人工总耗时',
    ai:'整理对账资料，对比预计与实际净利润，归纳错款、漏费、降价和滞销原因。',
    system:'现有日计划保存整批结算；工时、售后与完整回款周期分析仍需补记录。',
    person:'核对最终结算凭据和未售货物，决定继续补货、调整上限或退出该品类。',
    gate:'以相同费用口径比较预计与实际净利润。少量成功交易只能验证流程，仍需持续观察未售和售后。',
    action:'去日计划记录批次结算', href:'/#day-planner',
  },
];

let selected = 0, suggested = 0, connected = false, summary = null;
const validNumber = n => typeof n === 'number' && Number.isFinite(n) && n >= 0;
const realRecord = r => r.status === 'bought' && !/^(TEST[-_]|DEMO[-_])/i.test(r.code || '');
function summarize(items, days, now = new Date()) {
  const active = items.filter(i => !i.archived);
  const sales = active.filter(i => [i.code, i.color, i.size].every(s => s?.trim())
    && i.quote.seller && i.quote.net_cny > 0 && recent(i.quote.evidence_at, now)
    && ['sold','offer','order'].includes(i.quote.evidence_kind) && i.quote.evidence?.trim());
  const ceilings = sales.filter(i => diagnose(i, now).maxBuyJPY > 0);
  const records = days.flatMap(d => d.records || []);
  const purchases = records.filter(realRecord);
  const settled = purchases.filter(r => validNumber(r.actual_net_cny));
  const funds = deskBasket([], days, now);
  const ready = active.filter(i => buyDecision(remainingPurchase(i, records), funds.unknown ? null : funds.remaining, now).state === 'buy');
  const waiting = purchases.length - settled.length;
  const next = waiting ? 4 : ready.length ? 3 : !active.length && settled.length ? 5 : !sales.length ? 0 : !ceilings.length ? 1 : 2;
  return {active:active.length, sales:sales.length, ceilings:ceilings.length, ready:ready.length, bought:purchases.length, settled:settled.length, waiting, next};
}

function renderSteps() {
  $('#workflow-steps').innerHTML = steps.map((s, index) => `<button class="workflow-step" data-step="${index}" aria-pressed="${selected === index}" aria-controls="workflow-detail"><span class="step-number">${String(index + 1).padStart(2,'0')}</span>${index < 5 ? '<span class="step-arrow" aria-hidden="true">→</span>' : ''}<strong>${s.title}</strong><span class="step-caption">${s.caption}</span><span class="step-state">${s.state}</span></button>`).join('');
}

function showStep(index, scroll = false) {
  selected = index;
  const s = steps[index];
  document.querySelectorAll('[data-step]').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.step) === index)));
  $('#workflow-detail').innerHTML = `<div class="detail-heading"><div><p class="eyebrow">步骤 ${index + 1} / 6</p><h2 id="detail-title">${s.title}</h2><p>${s.question}</p></div><span class="detail-index" aria-hidden="true">${String(index + 1).padStart(2,'0')}</span></div><div class="detail-body"><div class="detail-result"><small>这一步要得到什么</small><strong>${s.result}</strong><p>${s.input}</p><div class="detail-output">${s.output}</div></div><div class="detail-roles"><div class="detail-role"><span>AI 可辅助</span><p>${s.ai}</p></div><div class="detail-role"><span>现有工具</span><p>${s.system}</p></div><div class="detail-role"><span>你来确认</span><p>${s.person}</p></div></div></div><div class="detail-gate"><strong>通过条件</strong><p>${s.gate}</p></div><div class="detail-actions"><a class="primary" href="${s.href}">${s.action} ↗</a><div><button data-direction="-1" ${index === 0 ? 'disabled' : ''}>← 上一步</button><button data-direction="1">${index === 5 ? '回到收购标准 ↶' : '下一步 →'}</button></div></div>`;
  if (location.hash !== `#${s.id}`) history.replaceState(null, '', `#${s.id}`);
  if (scroll) {
    $('#workflow-detail').focus({preventScroll:true});
    $('#workflow-detail').scrollIntoView({block:'start', behavior:matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  }
}

function renderProgress() {
  const labels = [['候选商品', 'active', '未归档的观察项'], ['销售依据已核齐', 'sales', '按当前规格与有效期检查'], ['已记实购', 'bought', '日计划中的实际采购批次'], ['已记结算', 'settled', '含零回款；不等于盈利']];
  $('#workflow-metrics').innerHTML = labels.map(([title,key,note]) => `<div class="workflow-metric"><small>${title}</small><strong>${connected ? summary[key] : '—'}</strong><p>${note}</p></div>`).join('');
  if (!connected) {
    $('#now-title').textContent = '先确认一个具体规格的销路';
    $('#now-description').textContent = '当前资料未连接完整，无法判断经营进度。可以先看流程，再刷新资料。';
    suggested = 0;
    return;
  }
  suggested = summary.next;
  const descriptions = [
    `当前 ${summary.active} 个候选，${summary.sales} 条销售依据核齐。先取得同规格成交或真实需求、自己的净收入和履约条件。`,
    `已有 ${summary.sales} 条销售依据，先补汇率、其余成本和目标利润，形成明确收购上限。`,
    `已有 ${summary.ceilings} 个正数采购上限，${summary.ready} 条当前可考虑买入。继续核实日本货源、库存、资格和交期。`,
    `${summary.ready} 条候选通过当前买入判断。进入日计划后，仍需核对组合预算、到店时窗与临时价格变化。`,
    `已保存 ${summary.waiting} 批未结算实购。先核对实物和当前销售报价，跟进刊登、发货与回款。`,
    `已记录 ${summary.settled} 批结算。对照成本、售后和持货时间，更新下一次的收购标准。`,
  ];
  $('#now-title').textContent = steps[suggested].result;
  $('#now-description').textContent = descriptions[suggested];
}

async function loadProgress() {
  const button = $('#workflow-refresh');
  button.disabled = true;
  connected = false;
  renderProgress();
  const status = $('#workflow-connection');
  status.classList.remove('error');
  status.textContent = '正在读取已保存的观察池与日计划…';
  try {
    const results = await Promise.all(['/api/sourcing','/api/day-plans'].map(async path => {
      const r = await fetch(path, {cache:'no-store', signal:AbortSignal.timeout(12000)});
      if (!r.ok) throw new Error('read failed');
      const data = await r.json();
      if (!Array.isArray(data)) throw new Error('invalid data');
      return data;
    }));
    summary = summarize(...results);
    connected = true;
    status.textContent = `已读取本地保存资料 · ${new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date())} 更新`;
  } catch {
    summary = null;
    status.classList.add('error');
    status.textContent = '资料读取失败，进度暂不显示。确认本地服务可用后，点击“刷新已保存资料”重试。';
  } finally {
    button.disabled = false;
    renderProgress();
  }
}

renderSteps();
const initial = steps.findIndex(s => s.id === location.hash.slice(1));
showStep(initial < 0 ? 0 : initial);
$('#workflow-steps').addEventListener('click', e => {
  const b = e.target.closest('[data-step]');
  if (b) showStep(Number(b.dataset.step), matchMedia('(max-width:760px)').matches);
});
$('#workflow-detail').addEventListener('click', e => {
  const b = e.target.closest('[data-direction]');
  if (b && !b.disabled) showStep(selected === 5 && b.dataset.direction === '1' ? 1 : selected + Number(b.dataset.direction), true);
});
$('#show-next').addEventListener('click', () => showStep(suggested, true));
$('#workflow-refresh').addEventListener('click', loadProgress);
window.addEventListener('hashchange', () => {
  const index = steps.findIndex(s => s.id === location.hash.slice(1));
  if (index >= 0) showStep(index);
});
loadProgress();
