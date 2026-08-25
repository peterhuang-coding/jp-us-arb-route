/* Alpine.js state for the jp-us-arb-route Dashboard SPA.
 *
 * 4 sections on one screen:
 *   1. Status bar  — counts + server dot
 *   2. Picks       — top-4 recommendations pre-computed from /api/decide at num_units=50
 *   3a. Alerts     — data-anomaly / unverified / pending side-bar
 *   3b. List       — searchable opportunity table
 *   4. Detail      — selected opp with ROI bar + scenarios + legs + sources
 *
 * Offline fallback:
 *   If /api/opportunities is unreachable we hydrate from EMBEDDED_DATA
 *   (a snapshot baked at build time from the same DB / judge() function).
 *   Decisions for unselected opps come from EMBEDDED_DATA.reports too, so
 *   PICK ranking + alerts + badges render identically without the server.
 */

// ---------- Round 20: 个人机会成本常量 ----------
// These are the user's own time/hotel convenience benchmarks. They are
// SUBTRACTED from resale net to give a "true take-home" feel. They are NOT
// the trip's real flight+hotel+other costs (those live on routes).
const PERSONAL_COST = {
  leaveHalfDayCny: 500,    // 请假半天 500 元(用户自定)
  hotelPerNightCny: 500,   // 住宿每晚 500 元(用户自定)
};

function app() {
  return {
    // ---- bootstrap state ----
    loading: false,
    refreshing: false,
    verifying: false,
    serverOnline: false,
    loaded: false,
    status: '',
    dbPath: '',
    snapshotAt: '',
    todayLabel: new Date().toISOString().slice(0, 10),

    // ---- data ----
    opportunities: [],
    routes: [],
    detailCache: {},          // sku -> full decide response
    baskets: {},              // routeName -> BasketResponse
    lastVerify: null,
    pendingProposals: 0,
    evidence: [],             // Round 21: 全量 evidence_log 行 (sku, side, channel_name) → row
    evidenceOpen: {},         // Round 21: {sku+side+idx: bool} 决策卷宗折叠状态

    // ---- form state ----
    selected: null,

    // ---- flight lookup (Round 16) ----
    flightOrigin: 'PEK',
    flightDest: 'NRT',
    flightDate: '2026-09-18', // default to weekend route's outbound Fri
    flightLoading: false,
    flightResult: null,
    flightHint: '',
    filter: '',
    filterCategory: '',
    filterStatus: '',
    routeName: 'PEK-NRT-WEEKEND',  // Round 18+19: default to Beijing→Tokyo weekend
    weekendOnly: true,             // Round 18+19: ON by default — only weekend routes shown
    numUnits: 6,            // Round 21: 50 件太离谱 — 箱子容量 ¥5,000 海关额度 + 重量 = 6 件上限
    origin: '北京 PEK',
    dest: '东京 NRT',

    // ---- Round 20: 搬运工偏好 ----
    asyncMode: false,         // false = 现场同步买优先(sync → async → ship)
    shopStopsOpen: false,     // trip banner 采购行的 Day-by-Day stops 折叠/展开

    // ---- M1 panel: 行程状态卡(首页决策入口) ----
    tripMode: 'none',         // 'none' 还没定行程 | 'booked' 已定好行程
    tripCostCny: 6000,        // 已定行程时: 一个人交通成本(CNY), 覆盖路线表固定成本

    // ---- derived ----
    get currentDetail() {
      return this.selected ? (this.detailCache[this.selected] || null) : null;
    },
    get currentBasket() {
      return this.routeName ? (this.baskets[this.routeName] || null) : null;
    },

    filtered() {
      const q = this.filter.trim().toLowerCase();
      const cat = this.filterCategory;
      const st = this.filterStatus;
      return this.opportunities.filter(o => {
        if (q && !((o.sku || '').toLowerCase().includes(q) ||
                   (o.name || '').toLowerCase().includes(q) ||
                   (o.category || '').toLowerCase().includes(q))) return false;
        if (cat && o.category !== cat) return false;
        if (st) {
          const lvl = this.detailCache[o.sku]?.decision?.level;
          if (lvl !== st) return false;
        }
        return true;
      });
    },

    uniqueCategories() {
      const set = new Set(this.opportunities.map(o => o.category).filter(Boolean));
      return Array.from(set).sort();
    },

    // ---- PICK computation (Top 4 by payback_rate_pct, Round 13 model) ----
    get picks() {
      if (!this.opportunities.length) return [];
      const route = this.currentRoute();
      const scored = this.opportunities.map(o => {
        const cached = this.detailCache[o.sku]?.decision;
        if (cached) {
          return { o, d: cached };
        }
        // Fall back to embedded snapshot if user hasn't clicked this opp yet.
        const snap = (typeof EMBEDDED_DATA !== 'undefined' &&
                      EMBEDDED_DATA.reports &&
                      EMBEDDED_DATA.reports[o.sku] &&
                      EMBEDDED_DATA.reports[o.sku]['50']);
        if (snap) return { o, d: snap.decision };
        return null;
      }).filter(x => x !== null);

      // Sort: highest payback_rate_pct first. Infinity > finite.
      scored.sort((a, b) => {
        const ar = a.d.payback_rate_pct ?? a.d.roi_pct;
        const br = b.d.payback_rate_pct ?? b.d.roi_pct;
        const aInf = !isFinite(ar), bInf = !isFinite(br);
        if (aInf && !bInf) return -1;
        if (!aInf && bInf) return 1;
        if (aInf && bInf) return 0;
        return br - ar;
      });

      const top = scored.slice(0, 4);
      return top.map((x, i) => this.formatPick(x.o, x.d, route, i + 1));
    },

    formatPick(opp, decision, route, rank) {
      // Round 13: thresholds are payback-based, not ROI-based.
      // GO if payback >= 100%, WATCH if >= 50%, else SKIP.
      const payback = decision.payback_rate_pct ?? decision.roi_pct;
      const tier = !isFinite(payback) || payback >= 100
        ? 'go'
        : (payback >= 50 ? 'watch' : 'skip');
      const tierLabel = tier === 'go' ? '🟢 GO' : tier === 'watch' ? '🟡 WATCH' : '🔴 SKIP';
      return {
        rank,
        sku: opp.sku,
        name: opp.name,
        purchasePrice: opp.purchase_price_usd,
        sellPrice: opp.sell_price_usd,
        roi: decision.roi_pct,
        payback,
        net: decision.net_profit_usd,
        units: this.numUnits,
        routeShort: route ? `${route.origin_city.split(' ')[0]}→${route.dest_city.split(' ')[0]}` : '',
        tier,
        tierLabel,
        reason: decision.reason,
      };
    },

    // ---- Payback badge color (reused by metric tile + basket summary) ----
    paybackClass(pct) {
      if (pct === undefined || pct === null) return '';
      if (!isFinite(pct) || pct >= 100) return 'payback-go';
      if (pct >= 50) return 'payback-watch';
      return 'payback-skip';
    },

    // ---- ALERTS computation ----
    get alerts() {
      const out = [];
      for (const o of this.opportunities) {
        // 倒赔: 售价 < 采购价 → 失真或订错
        if (o.sell_price_usd < o.purchase_price_usd) {
          out.push({
            id: 'inverted-' + o.sku,
            severity: 'danger',
            icon: '❌',
            title: `${o.name} 售价 $${o.sell_price_usd.toFixed(0)} < 采购 $${o.purchase_price_usd.toFixed(0)} → 倒赔`,
            detail: `可能原因:数据失真 / 成本漏算 / 品牌方限购导致 eBay 实际成交 < 标价。点击下方查看。`,
            sku: o.sku,
          });
        }
        // 未验证 + 高单价 → confidence=low
        if (!o.verified && o.purchase_price_usd >= 200) {
          out.push({
            id: 'unverified-' + o.sku,
            severity: 'warn',
            icon: '⚠️',
            title: `${o.name} 未验证 (confidence=low)`,
            detail: `采购价 $${o.purchase_price_usd.toFixed(0)} · 建议先点 "✓ 验证" 跑一轮抓取比对。`,
            sku: o.sku,
          });
        }
        // 产量受限
        if (/限购|限本人|限买/.test(o.notes || '')) {
          out.push({
            id: 'limited-' + o.sku,
            severity: 'info',
            icon: 'ℹ️',
            title: `${o.name} 有产量 / 限购限制`,
            detail: (o.notes || '').slice(0, 60),
            sku: o.sku,
          });
        }
      }
      // pending proposals
      if (this.pendingProposals > 0) {
        out.push({
          id: 'pending-proposals',
          severity: 'warn',
          icon: '📋',
          title: `${this.pendingProposals} 条 pending 提案待人工核对`,
          detail: '提案来自 verify 流程的 ±5% 漂移检测,不会自动覆盖。',
          sku: null,
        });
      } else {
        out.push({
          id: 'pending-proposals',
          severity: 'info',
          icon: '📋',
          title: '0 pending proposals',
          detail: '所有 verify 漂移提案已处理。',
          sku: null,
        });
      }
      // 数据日期
      const tsSet = new Set(this.opportunities.map(o => o.data_freshness_ts));
      const uniqueDates = Array.from(tsSet).filter(Boolean);
      out.push({
        id: 'data-date',
        severity: 'info',
        icon: 'ℹ️',
        title: `数据日期: ${uniqueDates.join(' / ')}`,
        detail: `${this.opportunities.length} 条商机 · ${this.routes.length} 条路线 · 决策引擎 ${this.snapshotAt || 'v0.2'}`,
        sku: null,
      });
      return out;
    },

    alertCount() {
      return this.alerts.filter(a => a.severity !== 'info').length;
    },

    goCount() {
      return this.opportunities.filter(o => {
        const d = this.detailCache[o.sku]?.decision;
        const r = (d ? d.roi_pct :
                   (EMBEDDED_DATA?.reports?.[o.sku]?.['50']?.decision?.roi_pct));
        return r !== undefined && r >= 15;
      }).length;
    },

    // ---- lifecycle ----
    async init() {
      this.setStatus('加载商机与路线…');
      // T4: row status badges
      this.bindRowStatusClicks();
      this.$nextTick(() => { this.rowStatusSetup(); });
      // Try API first; fall back to embedded snapshot if unreachable.
      try {
        const [opps, routes, health] = await Promise.all([
          fetch('/api/opportunities').then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
          fetch('/api/routes').then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
          fetch('/api/health').then(r => r.json()).catch(() => null),
        ]);
        this.opportunities = opps;
        this.routes = routes;
        this.serverOnline = true;
        if (health && typeof health === 'object') this.dbPath = health.db || '';
        this.snapshotAt = health ? 'API live' : (EMBEDDED_DATA?.snapshot_at || '');
        this.setStatus(`API 在线 · ${opps.length} 商机 · ${routes.length} 路线`);
      } catch (e) {
        this.hydrateFromSnapshot();
        this.serverOnline = false;
        this.setStatus('API 离线 · 使用本地快照 ' + (EMBEDDED_DATA?.snapshot_at || ''));
      }
      // Round 21: load evidence_log (separate fetch so the SPA still works
      // when this endpoint is unavailable — it just shows no 卷宗 per channel).
      if (this.serverOnline) {
        fetch('/api/evidence')
          .then(r => r.ok ? r.json() : [])
          .then(rows => { this.evidence = Array.isArray(rows) ? rows : []; })
          .catch(() => {});
      }

      // Attach freshness verdicts if missing (snapshot doesn't include them).
      this.opportunities = this.opportunities.map(o => {
        if (o.freshness) return o;
        return { ...o, freshness: this.computeFreshness(o.data_freshness_ts, o.sku) };
      });

      // Hydrate detailCache from snapshot for offline-friendly PICK rendering.
      this.hydrateDetailCacheFromSnapshot();

      // Default route selection — prefer PEK-NRT-WEEKEND (Friday→Sunday).
      // Falls back to the first route alphabetically if it isn't seeded.
      if (this.routes.length) {
        const preferred = this.routes.find(r => r.name === 'PEK-NRT-WEEKEND') || this.routes[0];
        this.routeName = preferred.name;
        this.origin = preferred.origin_city;
        this.dest = preferred.dest_city;
        // Keep the real-time flight lookup aligned with the selected route so the
        // user can hit "实查去程" without re-typing airport codes.
        this.flightOrigin = this.airportCode(preferred.origin_city);
        this.flightDest = this.airportCode(preferred.dest_city);
      }
      // Auto-sync flight lookup whenever the user picks a different route/city.
      this.$watch('origin', () => this.syncFlightFromCurrentRoute());
      this.$watch('dest',   () => this.syncFlightFromCurrentRoute());
      this.$watch('routeName', () => this.syncFlightFromCurrentRoute());

      this.pendingProposals = (typeof EMBEDDED_DATA !== 'undefined')
        ? (EMBEDDED_DATA.pending_proposals_count || 0)
        : 0;

      // Fetch pending proposal count from API if online.
      if (this.serverOnline) {
        fetch('/api/proposals?status=pending')
          .then(r => r.json())
          .then(rows => { this.pendingProposals = Array.isArray(rows) ? rows.length : 0; })
          .catch(() => {});
      }

      this.loaded = true;

      // Pre-decide top 4 at numUnits=50 in background so PICK + ROI badges render fast.
      this.warmupDecisions();

      // Load the 5000元 basket for the default route. Round 13.
      if (this.serverOnline) {
        this.loadBasket(this.routeName);
      }
    },

    // ---- Round 13: 5000元 optimal basket (POST /api/basket) ----
    async loadBasket(routeName) {
      if (!routeName) return;
      try {
        const r = await fetch('/api/basket', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            budget_cny: 5000,
            customs_limit_cny: 5000,
            route: routeName,
          }),
        });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const body = await r.json();
        this.baskets = { ...this.baskets, [routeName]: body };
        this.setStatus(`🛒 购物清单已更新 (${body.picks.length} 条 SKU, 回本率 ${isFinite(body.payback_rate_pct) ? body.payback_rate_pct.toFixed(0) : '∞'}%)`);
      } catch (e) {
        // Silently skip — basket is a nice-to-have, not critical.
      }
    },

    // Route dropdown changed — refresh basket and re-warmup.
    async onRouteChange() {
      this.refetch();
      if (this.serverOnline) this.loadBasket(this.routeName);
    },

    hydrateFromSnapshot() {
      if (typeof EMBEDDED_DATA === 'undefined') {
        this.setStatus('快照不可用,无法渲染', true);
        return;
      }
      this.opportunities = JSON.parse(JSON.stringify(EMBEDDED_DATA.opportunities || []));
      this.routes = JSON.parse(JSON.stringify(EMBEDDED_DATA.routes || []));
      this.snapshotAt = EMBEDDED_DATA.snapshot_at || '';
      this.dbPath = 'snapshot (offline)';
    },

    hydrateDetailCacheFromSnapshot() {
      if (typeof EMBEDDED_DATA === 'undefined' || !EMBEDDED_DATA.reports) return;
      const route = this.currentRoute();
      for (const sku in EMBEDDED_DATA.reports) {
        const r50 = EMBEDDED_DATA.reports[sku]['50'];
        if (!r50) continue;
        const opp = this.opportunities.find(o => o.sku === sku);
        if (!opp) continue;
        this.detailCache[sku] = {
          opp: opp,
          route: route,
          legs: r50.legs || [],
          num_units: 50,
          decision: r50.decision,
          scenarios: r50.scenarios || [],
        };
      }
    },

    computeFreshness(ts, sku) {
      // Mirrors arb.freshness.classify so the SPA can show the badge even
      // when the API's `freshness` block isn't present (snapshot path).
      const today = new Date().toISOString().slice(0, 10);
      if (!ts) return { status: 'missing', badge: '⛔ 缺失', age_days: null, is_stale: true };
      const age = Math.floor((new Date(today) - new Date(ts)) / 86400000);
      if (age < 0) return { status: 'future', badge: '⚠️ 未来', age_days: age, is_stale: true };
      if (age >= 30) return { status: 'stale', badge: '⚠️ 陈旧待复核', age_days: age, is_stale: true };
      if (age >= 15) return { status: 'aging', badge: '🟡 老化', age_days: age, is_stale: false };
      return { status: 'fresh', badge: '🟢 新鲜', age_days: age, is_stale: false };
    },

    async warmupDecisions() {
      // Run /api/decide for the top opportunities so list badges update with
      // real numbers. If API is offline, snapshot already covers this.
      if (!this.serverOnline) return;
      const routeName = this.routeName;
      const units = this.numUnits;
      const opps = [...this.opportunities].slice(0, 10);
      for (const o of opps) {
        if (this.detailCache[o.sku]) continue;  // already populated from snapshot
        try {
          const resp = await fetch('/api/decide', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sku: o.sku, num_units: units, route: routeName }),
          });
          if (resp.ok) {
            this.detailCache[o.sku] = await resp.json();
          }
        } catch (e) { /* keep snapshot */ }
      }
      this.setStatus(`已用 API 决策 ${Object.keys(this.detailCache).length} 条商机`);
    },

    currentRoute() {
      // Prefer the explicit topbar origin/dest pair (legacy Round 12 contract).
      // Fall back to the explicit routeName select.
      const matched = this.routes.find(r => r.origin_city === this.origin && r.dest_city === this.dest);
      if (matched) return matched;
      return this.routes.find(r => r.name === this.routeName) || this.routes[0] || null;
    },

    weekendMatch(route) {
      // True when outbound flight departs Fri/Sat AND return flight arrives Sun/Mon.
      // Used for the "� 周末 only" toggle in the trip banner.
      if (!route || !route.legs || !route.legs.length) return false;
      const firstFlight = route.legs.find(l => l.kind === 'flight' && l.depart_at);
      const lastFlight = [...route.legs].reverse().find(l => l.kind === 'flight' && l.arrive_at);
      if (!firstFlight || !lastFlight) return false;
      const outDay = new Date(firstFlight.depart_at).getDay();   // 0=Sun..6=Sat
      const backDay = new Date(lastFlight.arrive_at).getDay();
      return (outDay === 5 || outDay === 6) && (backDay === 0 || backDay === 1);
    },

    visibleRoutes() {
      // All routes when weekendOnly is off; weekend-matching only when on.
      if (!this.weekendOnly) return this.routes;
      return this.routes.filter(r => this.weekendMatch(r));
    },

    // Extract the 3-letter IATA code from a city string like "北京 PEK" / "东京 NRT".
    // Falls back to upper-cased input if no uppercase word is found.
    airportCode(cityLabel) {
      if (!cityLabel) return '';
      const m = String(cityLabel).match(/[A-Z]{3}/);
      return m ? m[0] : String(cityLabel).trim().toUpperCase().slice(0, 3);
    },

    // When the user changes route/origin/dest, mirror the airports into the
    // topbar "实时机票" lookup so "🔄 实查去程" hits the right market.
    syncFlightFromCurrentRoute() {
      const r = this.routes.find(x => x.name === this.routeName)
             || this.routes.find(x => x.origin_city === this.origin && x.dest_city === this.dest)
             || null;
      if (!r) return;
      const oc = this.airportCode(r.origin_city);
      const dc = this.airportCode(r.dest_city);
      if (oc) this.flightOrigin = oc;
      if (dc) this.flightDest = dc;
    },

    get tripBanner() {
      // Derived from currentRoute.legs — splits into outbound / shop / return
      // and parses hand-written flight numbers from leg.notes ("NH 920 / JL 870").
      // Implemented as a getter (not method) so Alpine tracks `routes`/`origin`/
      // `dest`/`routeName` deps even when early-returning null.
      const r = this.routes.find(x => x.name === this.routeName) || this.routes[0] || null;
      if (!r || !r.legs) return null;
      const legs = r.legs;
      const idxShop = legs.findIndex(l => l.kind === 'shop');
      const outbound = idxShop >= 0 ? legs.slice(0, idxShop).filter(l => l.kind === 'flight') : [];
      const ret = idxShop >= 0 ? legs.slice(idxShop + 1).filter(l => l.kind === 'flight') : [];
      const shopLeg = idxShop >= 0 ? legs[idxShop] : null;
      const parseNos = (ls) => {
        const nos = [];
        for (const l of ls) {
          const m = (l.notes || '').match(/[A-Z]{2,3}\s*\d{2,4}/g);
          if (m) nos.push(...m);
        }
        return nos;
      };
      const fmtDate = (iso) => iso ? iso.split('T')[0].slice(5) : '—';
      const fmtTime = (iso) => iso ? iso.split('T')[1] : '—';
      // 周几 (中文短词) — 用户一眼看出哪天走 / 哪天回
      const CN_WEEK = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
      const fmtWeekday = (iso) => iso ? CN_WEEK[new Date(iso).getDay()] : '—';
      const dur = (a, b) => (a && b) ? Math.round((new Date(b) - new Date(a)) / 3600000) : 0;
      const firstDepart = legs[0]?.depart_at;
      const lastArrive = legs[legs.length - 1]?.arrive_at;
      const fixed = (r.flight_cost_usd || 0) + (r.hotel_cost_usd || 0) + (r.other_cost_usd || 0);
      // 美元 → 人民币 (route 自带 cn_to_usd_fx, 即 1 CNY = X USD, 反向得 1 USD = 1/X CNY)
      const cnyPerUsd = r.cn_to_usd_fx ? (1 / r.cn_to_usd_fx) : null;
      const fixedCny = cnyPerUsd ? fixed * cnyPerUsd : null;
      const fxLabel = cnyPerUsd ? ('汇率 1 USD ≈ ' + cnyPerUsd.toFixed(2) + ' CNY') : '';
      return {
        hasData: !!(firstDepart && lastArrive),
        routeName: r.name,
        originCity: r.origin_city,
        destCity: r.dest_city,
        outbound: outbound.map(l => ({
          label: l.label,
          from: (l.label || '').split('→')[0]?.trim(),
          to: (l.label || '').split('→')[1]?.trim(),
          depart: l.depart_at,
          arrive: l.arrive_at,
          flightNo: parseNos([l])[0] || '',
        })),
        shop: shopLeg ? {
          label: shopLeg.label,
          location: shopLeg.location,
          depart: shopLeg.depart_at,
          arrive: shopLeg.arrive_at,
          hours: dur(shopLeg.depart_at, shopLeg.arrive_at),
          stops: Array.isArray(shopLeg.stops) ? shopLeg.stops : [],
        } : null,
        return: ret.map(l => ({
          label: l.label,
          from: (l.label || '').split('→')[0]?.trim(),
          to: (l.label || '').split('→')[1]?.trim(),
          depart: l.depart_at,
          arrive: l.arrive_at,
          flightNo: parseNos([l])[0] || '',
        })),
        totalHours: dur(firstDepart, lastArrive),
        fixed,
        fixedCny,
        fxLabel,
        leave: this.leaveNeed(r),
        hotel: this.hotelNeed(r),
        leaveSummary: this.leaveNeed(r).summary,
        fmtDate, fmtTime, fmtWeekday,
      };
    },

    // ---- Round 20: 个人机会成本(请假 ¥500/半天 + 住宿 ¥500/晚) ------
    // Reads leaveNeed()/hotelNeed() severities and turns them into a CNY sum
    // that the SPA subtracts from resale net. Edits to PERSONAL_COST const
    // at the top of this file — backend stays untouched.
    get personalCostCny() {
      const route = this.routes.find(x => x.name === this.routeName);
      if (!route) {
        return { halfDays: 0, nights: 0, leaveCny: 0, hotelCny: 0, totalCny: 0 };
      }
      const leave = this.leaveNeed(route);
      const hotel = this.hotelNeed(route);
      const halfDays =
          (leave.outbound.severity >= 2 ? 1 : 0)
        + (leave.outbound.severity === 1 ? 0.5 : 0)
        + (leave.return.severity >= 2 ? 1 : 0)
        + (leave.return.severity === 1 ? 0.5 : 0);
      const nights = hotel.nights || 0;
      const leaveCny = halfDays * PERSONAL_COST.leaveHalfDayCny;
      const hotelCny = nights  * PERSONAL_COST.hotelPerNightCny;
      return { halfDays, nights, leaveCny, hotelCny, totalCny: leaveCny + hotelCny };
    },

    // ---- Round 19: 搬运工清单 (转售口径净利) -----------------------
    get dpsPicks() {
      // 每条 SKU 用转售口径算单件净利:
      //   unitNet = sell_price × (1 - 平台费) - 采购 × (1+关税) - 物流
      // ROI = unitNet / unitCost × 100
      // 按 ROI 倒序,返回 top 6 (含渠道且 ROI > 0)。
      const opps = this.opportunities || [];
      if (!opps.length) return [];
      const cap = Math.max(1, Math.min(this.numUnits || 50, 50));
      const scored = opps.map(o => {
        const sell = Number(o.sell_price_usd || 0);
        const buy  = Number(o.purchase_price_usd || 0);
        const fee  = Number(o.platform_fee_rate || 0);
        const tar  = Number(o.tariff_rate || 0);
        const ship = Number(o.shipping_per_unit_usd || 0);
        const unitCost = buy * (1 + tar) + ship;
        const unitNet  = sell * (1 - fee) - unitCost;
        const roiPct   = unitCost > 0 ? (unitNet / unitCost * 100) : 0;
        const maxUnits = Number(o.max_units_per_trip || 50);
        const numUnits = Math.min(cap, maxUnits);
        return {
          sku: o.sku,
          name: o.name,
          category: o.category || '',
          numUnits,
          purchasePrice: buy,
          sellPrice: sell,
          unitCost,
          unitNet,
          roiPct,
          tier: roiPct >= 30 ? 'go' : (roiPct >= 15 ? 'watch' : 'skip'),
          purchaseChannels: Array.isArray(o.purchase_channels) ? o.purchase_channels : [],
          sellChannels:     Array.isArray(o.sell_channels)     ? o.sell_channels     : [],
        };
      }).filter(p => p.roiPct > 0 && p.purchaseChannels.length && p.sellChannels.length);
      scored.sort((a, b) => b.roiPct - a.roiPct);
      return scored.slice(0, 6);
    },

    // 行程状态卡: 已定行程时用用户填的交通成本(CNY×fx)覆盖路线表固定成本
    tripCostUsd() {
      const fx = this.routes.find(x => x.name === this.routeName)?.cn_to_usd_fx || 0.14;
      return (Number(this.tripCostCny) || 0) * fx;
    },

    // ---- 面板简化: 站内锚点先展开「更多工具」, 再让浏览器跳转 ----
    openTools() {
      const d = this.$refs.moreTools;
      if (d) d.open = true;
    },

    // ---- 面板简化: 一键点开 — 把按钮所在 h3/h4 后面那张表的所有外链全打开 ----
    openAllLinks(btn) {
      let node = btn.parentElement.nextElementSibling;
      let guard = 0;
      while (node && node.tagName !== 'TABLE' && guard++ < 4) node = node.nextElementSibling;
      if (!node || node.tagName !== 'TABLE') return;
      const hrefs = new Set();
      node.querySelectorAll('a[href]').forEach(a => {
        const raw = a.getAttribute('href') || '';
        if (raw.startsWith('http')) hrefs.add(raw);  // 站内锚点(#开头)不打开新标签
      });
      hrefs.forEach(url => window.open(url, '_blank'));
    },

    get dpsTripFixed() {
      if (this.tripMode === 'booked' && Number(this.tripCostCny) > 0) return this.tripCostUsd();
      const r = this.routes.find(x => x.name === this.routeName);
      if (!r) return 0;
      return (Number(r.flight_cost_usd || 0)
            + Number(r.hotel_cost_usd  || 0)
            + Number(r.other_cost_usd  || 0));
    },

    get dpsTotalNet() {
      return this.dpsPicks.reduce((s, p) => s + p.unitNet * p.numUnits, 0);
    },

    get dpsPayback() {
      return this.dpsTripFixed > 0 ? (this.dpsTotalNet / this.dpsTripFixed * 100) : 0;
    },

    // Round 20: 真净赚 = 搬运净赚 - 个人成本(美元口径,先转 CNY 再 ÷ fx)
    get dpsTrueNet() {
      const r = this.routes.find(x => x.name === this.routeName);
      const fx = r?.cn_to_usd_fx || 0.14;
      const personalUsd = this.personalCostCny.totalCny * fx;
      return this.dpsTotalNet - personalUsd;
    },

    get dpsPaybackTrue() {
      return this.dpsTripFixed > 0 ? (this.dpsTrueNet / this.dpsTripFixed * 100) : 0;
    },

    dpsTierLabel(tier) {
      return tier === 'go' ? '🟢 GO' : tier === 'watch' ? '🟡 WATCH' : '🔴 SKIP';
    },

    // Round 20: fulfillment icon — sync=🏬现场 / async=📦异步 / ship=🚚转运
    fulfillmentIcon(f) {
      if (f === 'async') return '📦';
      if (f === 'ship')  return '🚚';
      return '🏬';  // default = sync
    },

    // Round 20: anchor badge — 📌 when this channel is the price source
    anchorBadge(ch) {
      return (ch && ch.anchor) ? '📌 ' : '';
    },

    fulfillmentClass(f) {
      if (f === 'async') return 'ful-async';
      if (f === 'ship')  return 'ful-ship';
      return 'ful-sync';
    },

    // Round 20: chip label = anchor badge + fulfillment icon + name
    dpsChannelLabel(ch) {
      if (!ch) return '';
      return this.anchorBadge(ch) + this.fulfillmentIcon(ch.fulfillment) + ' ' + (ch.name || '渠道');
    },

    // Round 21: 决策卷宗 — 取 (sku, side, channel_name) 命中的所有 evidence 行
    // A channel may have multiple evidence rows (different observed_at).
    // Returns array of evidence dicts, possibly empty.
    evidenceFor(sku, side, channelName) {
      if (!this.evidence.length || !sku || !side || !channelName) return [];
      return this.evidence.filter(e =>
        e.sku === sku && e.side === side && e.channel_name === channelName
      );
    },

    // Round 21: 是否有任何 evidence (决定是否显示卷宗折叠)
    sideHasEvidence(sku, side) {
      if (!this.evidence.length || !sku) return false;
      return this.evidence.some(e => e.sku === sku && e.side === side);
    },

    // Round 21: 折叠开关 key — sku+'·'+side
    evidenceToggleKey(sku, side) { return sku + '·' + side; },
    isEvidenceOpen(sku, side) { return !!this.evidenceOpen[this.evidenceToggleKey(sku, side)]; },
    toggleEvidence(sku, side) {
      this.evidenceOpen[this.evidenceToggleKey(sku, side)] = !this.isEvidenceOpen(sku, side);
    },

    // Round 21: 折 CNY 价格显示用 (¥995 / ¥1,850 等)
    fmtCny(n) {
      if (n === null || n === undefined) return '—';
      return '¥' + Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 0 });
    },
    fmtUsd(n) {
      if (n === null || n === undefined) return '—';
      return '$' + Number(n).toLocaleString('en-US', { maximumFractionDigits: 0 });
    },

    // Round 20: channel sort driven by asyncMode toggle.
    //   asyncMode=false (default): sync first → async → ship
    //   asyncMode=true :           async first → ship → sync
    // Returns a fresh sorted copy — doesn't mutate the original channels.
    sortedChannels(channels) {
      if (!channels || !channels.length) return [];
      const order = this.asyncMode
        ? { async: 0, ship: 1, sync: 2 }
        : { sync: 0, async: 1, ship: 2 };
      return [...channels].sort((a, b) =>
        (order[a.fulfillment] ?? 9) - (order[b.fulfillment] ?? 9));
    },

    // 请假判断 — 边界: 周五 19:30 出发 / 周一 10:00 到北京
    // 用户偏好: 周五晚 19:30 之后起飞当周没事;周一上午 10:00 之后到北京算请假
    leaveNeed(route) {
      const empty = { outbound: { text: '—', severity: 0 }, return: { text: '—', severity: 0 }, summary: '—' };
      if (!route?.legs?.length) return empty;
      const firstFlight = route.legs.find(l => l.kind === 'flight' && l.depart_at);
      const lastFlight  = [...route.legs].reverse().find(l => l.kind === 'flight' && l.arrive_at);
      if (!firstFlight || !lastFlight) return empty;
      const CN_WEEK = ['日','一','二','三','四','五','六'];
      const out  = new Date(firstFlight.depart_at);
      const back = new Date(lastFlight.arrive_at);
      const outHour  = out.getHours() + out.getMinutes() / 60;
      const backHour = back.getHours() + back.getMinutes() / 60;
      const outDay  = out.getDay();
      const backDay = back.getDay();

      // 出发侧
      const o = { text: '', severity: 0 };
      if (outDay === 5) {                                    // 周五
        if (outHour < 12)       { o.text = '⚠️ 周五全天请假'; o.severity = 2; }
        else if (outHour < 14)  { o.text = '⚠️ 周五请假 (含午饭)'; o.severity = 2; }
        else if (outHour < 19.5){ o.text = '🟡 周五下午请假 ~半天'; o.severity = 1; }
        else                    { o.text = '✅ 周五晚直飞 无需请假'; o.severity = 0; }
      } else if (outDay === 6) {                              // 周六
        o.text = '✅ 周六出发 无需请假'; o.severity = 0;
      } else if (outDay === 4) {                              // 周四晚
        o.text = '🟡 周四晚出发 提前 ~半天'; o.severity = 1;
      } else {
        o.text = '⚠️ 周' + CN_WEEK[outDay] + '出发 需请假'; o.severity = 2;
      }

      // 回程侧
      const b = { text: '', severity: 0 };
      if (backDay === 0) {                                   // 周日
        if (backHour < 19.5) { b.text = '✅ 周日' + (backHour < 12 ? '上午' : '下午') + '到 无需请假'; b.severity = 0; }
        else                 { b.text = '🟡 周日深夜到 周一略疲'; b.severity = 1; }
      } else if (backDay === 1) {                            // 周一
        if (backHour < 10)     { b.text = '✅ 周一早到 无需请假'; b.severity = 0; }
        else if (backHour < 14){ b.text = '🟡 周一上午请假 ~半天'; b.severity = 1; }
        else                   { b.text = '⚠️ 周一全天请假'; b.severity = 2; }
      } else if (backDay === 2) {
        b.text = '⚠️ 周二到 需请假'; b.severity = 2;
      } else {
        b.text = '⚠️ 周' + CN_WEEK[backDay] + '到 需请假'; b.severity = 2;
      }

      const parts = [];
      if (o.severity > 0) parts.push(o.text.replace(/^[🟡⚠️✅]\s*/, ''));
      if (b.severity > 0) parts.push(b.text.replace(/^[🟡⚠️✅]\s*/, ''));
      const summary = parts.length === 0 ? '✅ 全程无需请假' : parts.join(' · ');
      return { outbound: o, return: b, summary };
    },

    // 住宿判断 — 用户偏好: ≤ 1 晚最佳; 当天往返 / 红眼不睡 也接受
    hotelNeed(route) {
      if (!route?.legs?.length) return { nights: 0, text: '—', severity: 0 };
      const hotelLegs = route.legs.filter(l => l.kind === 'hotel');
      let totalNights = 0;
      for (const l of hotelLegs) {
        const arrive = l.arrive_at ? new Date(l.arrive_at) : null;
        const depart = l.depart_at ? new Date(l.depart_at) : null;
        if (arrive && depart) {
          const hours = (depart - arrive) / 3600000;
          totalNights += Math.max(0, Math.round(hours / 24));
        } else if (arrive) {
          totalNights += 1;   // 兜底:有 arrive 没 depart 算 1 晚
        }
      }
      let text, severity;
      if (totalNights === 0) {
        text = '🛫 不住宿 (当天往返 / 红眼硬撑) — 可行';
        severity = 0;
      } else if (totalNights === 1) {
        text = '🛏 住 1 晚 — 最合适';
        severity = 0;
      } else if (totalNights === 2) {
        text = '🛏 住 2 晚 — 偏长,可考虑改硬撑不睡';
        severity = 1;
      } else {
        text = '🛏 住 ' + totalNights + ' 晚 — 过长,建议重排';
        severity = 2;
      }
      return { nights: totalNights, text, severity };
    },

    async lookupLiveOutbound() {
      // Hit /api/flight with the banner's outbound origin/dest/date so the
      // user can sanity-check the hand-written flight numbers against Amadeus.
      const b = this.tripBanner;
      if (!b || !b.outbound.length) {
        this.flightResult = { ok: false, hint: '行程无数据,先选路线' };
        return;
      }
      const first = b.outbound[0];
      const last = b.outbound[b.outbound.length - 1];
      const origin = (first.from || '').match(/[A-Z]{3}/)?.[0];
      const dest = (last.to || '').match(/[A-Z]{3}/)?.[0];
      const date = (first.depart || '').split('T')[0];
      if (!origin || !dest || !date) {
        this.flightResult = { ok: false, hint: '无法从行程提取 IATA 或日期' };
        return;
      }
      this.flightOrigin = origin;
      this.flightDest = dest;
      this.flightDate = date;
      await this.searchFlight();
    },

    matchRouteName() {
      const matched = this.routes.find(r => r.origin_city === this.origin && r.dest_city === this.dest);
      if (matched) return matched.name;
      return this.routeName || (this.routes[0] && this.routes[0].name);
    },

    syncRouteFromPickers() {
      // Keep routeName aligned with the topbar origin/dest picks so the
      // quick-decide select and the topbar stay in sync.
      const matched = this.routes.find(r => r.origin_city === this.origin && r.dest_city === this.dest);
      if (matched) this.routeName = matched.name;
    },

    // ---- actions ----
    async select(sku) {
      this.selected = sku;
      // Scroll detail into view on small screens.
      this.$nextTick(() => {
        const el = document.getElementById('detailSection');
        if (el && window.innerWidth < 1200) el.scrollIntoView({ behavior: 'smooth' });
      });
      if (this.detailCache[sku] && this.detailCache[sku].num_units === this.numUnits
          && this.detailCache[sku].route.name === this.routeName) return;
      await this.decideOne(sku, this.numUnits, this.routeName);
    },

    async decideOne(sku, units, routeName) {
      // Prefer API when online; else use snapshot.
      if (this.serverOnline) {
        try {
          const resp = await fetch('/api/decide', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sku, num_units: units, route: routeName }),
          });
          if (resp.ok) {
            this.detailCache[sku] = await resp.json();
            return;
          }
        } catch (e) { /* fall through */ }
      }
      // Fallback: build detail from snapshot decision + current route legs.
      if (typeof EMBEDDED_DATA !== 'undefined' && EMBEDDED_DATA.reports?.[sku]) {
        const rep = EMBEDDED_DATA.reports[sku][String(units)] ||
                    EMBEDDED_DATA.reports[sku]['50'];
        const route = this.routes.find(r => r.name === routeName) || this.routes[0];
        const opp = this.opportunities.find(o => o.sku === sku);
        if (rep && route && opp) {
          this.detailCache[sku] = {
            opp, route,
            legs: rep.legs || [],
            num_units: units,
            decision: rep.decision,
            scenarios: rep.scenarios || [],
          };
        }
      }
    },

    async refetch() {
      // Re-decide all cached opps with new units / route.
      const cache = { ...this.detailCache };
      this.detailCache = {};
      this.loading = true;
      try {
        // Update snapshot-derived entries to match new units/route.
        for (const sku in cache) {
          await this.decideOne(sku, this.numUnits, this.routeName);
        }
        // Also warm top picks that weren't selected yet.
        await this.warmupDecisions();
        // Re-select current opp to refresh banner.
        if (this.selected) {
          this.detailCache[this.selected] = await this.buildDetailFromCache(this.selected);
        }
        this.setStatus(`已按 数量=${this.numUnits} 路线=${this.routeName} 重新决策`);
      } finally {
        this.loading = false;
      }
    },

    async buildDetailFromCache(sku) {
      // No-op: decideOne() already writes into detailCache.
      return this.detailCache[sku];
    },

    // ---- export ----
    exportUrl(fmt) {
      if (!this.selected) return '';
      const sku = encodeURIComponent(this.selected);
      const route = encodeURIComponent(this.routeName || '');
      return `/api/report/${sku}.${fmt}?num_units=${this.numUnits}&route=${route}`;
    },

    async exportMd() { const u = this.exportUrl('md'); if (u) this.downloadFromUrl(u, this.suggestFilename('md')); },
    async exportHtml() { const u = this.exportUrl('html'); if (u) this.downloadFromUrl(u, this.suggestFilename('html')); },
    async exportPdf() {
      const u = this.exportUrl('pdf');
      if (!u) return;
      this.setStatus('PDF 渲染中…');
      this.downloadFromUrl(u, this.suggestFilename('pdf'));
      this.setStatus('PDF 已生成');
    },

    suggestFilename(ext) {
      const today = new Date().toISOString().slice(0, 10);
      const sku = (this.selected || 'report').replace(/[^A-Za-z0-9_-]/g, '_');
      const dest = (this.currentRoute()?.dest_city || 'dest').replace(/[^A-Za-z0-9_-]/g, '_');
      return `jp-us-arb_${today}_${sku}_${dest}.${ext}`;
    },

    async downloadFromUrl(url, filename) {
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(a.href);
      } catch (e) {
        this.setStatus('下载失败: ' + e.message + ' (可能 API 已离线)', true);
      }
    },

    // ---- formatters ----
    badgeClass(level) {
      return { '建议': 'ok', '谨慎': 'warn', '不建议': 'bad' }[level] || 'muted';
    },
    badgeText(level) {
      return { '建议': '✅ 建议', '谨慎': '⚠️ 谨慎', '不建议': '❌ 不建议' }[level] || '—';
    },
    bannerTier(level) {
      return { '建议': 'ok', '谨慎': 'warn', '不建议': 'bad' }[level] || 'muted';
    },
    bannerLabel(level) {
      return { '建议': '✅ 建议', '谨慎': '⚠️ 谨慎', '不建议': '❌ 不建议' }[level] || '—';
    },
    routeFixed(r) {
      const total = (r.flight_cost_usd || 0) + (r.hotel_cost_usd || 0) + (r.other_cost_usd || 0);
      return '$' + total.toFixed(0);
    },
    routeFixedBreakdown(r) {
      const parts = [`机票 $${(r.flight_cost_usd || 0).toFixed(0)}`,
                     `酒店 $${(r.hotel_cost_usd || 0).toFixed(0)}`];
      if ((r.other_cost_usd || 0) > 0) parts.push(`其它 $${(r.other_cost_usd || 0).toFixed(0)}`);
      return parts.join(' + ');
    },
    roiClass(roi) {
      const r = this.currentRoute();
      const target = r?.target_roi_pct || 15;
      const min = r?.min_roi_pct || 10;
      if (roi == null) return '';
      if (roi >= target) return 'ok';
      if (roi >= min) return 'warn';
      return 'bad';
    },
    freshClass(o) {
      const f = o && o.freshness;
      if (!f) return '';
      if (f.status === 'stale' || f.status === 'missing' || f.status === 'future') return 'stale';
      return f.status;
    },
    scenarioRowClass(s) {
      return s.name === '中性' ? 'neutral-band' : '';
    },
    freshAge(f) {
      if (!f || f.age_days === null || f.age_days === undefined) return '未知';
      const d = f.age_days;
      if (d < 0) return `未来 ${-d} 天`;
      if (d === 0) return '今天';
      if (d === 1) return '昨天';
      if (d < 30) return `${d} 天前`;
      if (d < 365) return `${Math.floor(d/30)} 个月前`;
      return `${Math.floor(d/365)} 年前`;
    },

    // ---- verify / refresh (Round 4) ----
    async refreshOpportunity() {
      if (!this.selected) return;
      this.refreshing = true;
      try {
        const sku = encodeURIComponent(this.selected);
        const resp = await fetch(`/api/opportunities/${sku}/refresh`, { method: 'POST' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const out = await resp.json();
        if (out.updated) {
          const idx = this.opportunities.findIndex(o => o.sku === this.selected);
          if (idx >= 0) {
            this.opportunities[idx].data_freshness_ts = out.new_freshness_ts;
            this.opportunities[idx].freshness = out.verdict_after;
          }
          if (this.detailCache[this.selected]) {
            this.detailCache[this.selected].opp.data_freshness_ts = out.new_freshness_ts;
            this.detailCache[this.selected].opp.freshness = out.verdict_after;
          }
          this.setStatus(`${this.selected} freshness_ts 已刷新 → ${out.new_freshness_ts}`);
        } else {
          this.setStatus(`刷新未生效: ${out.message}`, true);
        }
      } catch (e) {
        this.setStatus('刷新失败: ' + e.message, true);
      } finally {
        this.refreshing = false;
      }
    },

    async verifyOpportunity() {
      if (!this.selected) return;
      this.verifying = true;
      try {
        const sku = encodeURIComponent(this.selected);
        const resp = await fetch(`/api/opportunities/${sku}/verify`, { method: 'POST' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const out = await resp.json();
        this.lastVerify = out;
        const idx = this.opportunities.findIndex(o => o.sku === this.selected);
        if (idx >= 0) {
          if (out.final_freshness_ts) this.opportunities[idx].data_freshness_ts = out.final_freshness_ts;
          this.opportunities[idx].verified = !!out.final_verified;
        }
        if (this.detailCache[this.selected]) {
          if (out.final_freshness_ts) this.detailCache[this.selected].opp.data_freshness_ts = out.final_freshness_ts;
          this.detailCache[this.selected].opp.verified = !!out.final_verified;
        }
        const proposalCount = (out.purchase.proposal_id ? 1 : 0) + (out.sell.proposal_id ? 1 : 0);
        if (out.verified_now) this.setStatus(`${this.selected} 已验证 ✓ (容差内)`);
        else if (proposalCount > 0) this.setStatus(`${this.selected} 漂移超出容差,已 stage ${proposalCount} 条提案`);
        else this.setStatus(`${this.selected} ${out.message}`);
      } catch (e) {
        this.setStatus('验证失败: ' + e.message, true);
      } finally {
        this.verifying = false;
      }
    },

    setStatus(msg, isError = false) {
      this.status = msg;
    },

    legTimeLabel(leg) {
      // Format leg.depart_at / arrive_at ('YYYY-MM-DDTHH:MM' or null) into a
      // compact "[09-15 09:00 → 12:20]" label.  Falls back gracefully when
      // either timestamp is missing (e.g. pre-Round-17 snapshots, hotel legs).
      if (leg.depart_at && leg.arrive_at) {
        const dDay = leg.depart_at.split('T')[0];
        const aDay = leg.arrive_at.split('T')[0];
        const dTime = leg.depart_at.split('T')[1];
        const aTime = leg.arrive_at.split('T')[1];
        if (dDay === aDay) {
          return `[${dDay.slice(5)} ${dTime} → ${aTime}]`;
        }
        return `[${dDay.slice(5)} ${dTime} → ${aDay.slice(5)} ${aTime}]`;
      }
      if (leg.arrive_at) {
        return `[→ ${leg.arrive_at.split('T')[1] || leg.arrive_at}]`;
      }
      return '';
    },

    // ── T4: row status (订单状态 badge 嵌进 simple-section 每行) ──
    rowStatusCache: {},
    _rowSkuMap: {},

    rowStatusSetup() {
      const tables = document.querySelectorAll('.simple-section .simple-table');
      tables.forEach(table => {
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        const thead = table.querySelector('thead tr');
        if (thead && !thead.querySelector('.th-status')) {
          const th = document.createElement('th');
          th.className = 'th-status';
          th.textContent = '📦 状态';
          thead.appendChild(th);
        }
        Array.from(tbody.querySelectorAll('tr')).forEach(tr => {
          if (tr.querySelector('.row-status-cell')) return;
          const firstTd = tr.querySelector('td');
          if (!firstTd) return;
          const rawText = firstTd.textContent.trim().replace(/^[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]\s*/u, '');
          const slug = this._slugify(rawText);
          this._rowSkuMap[slug] = rawText;
          const td = document.createElement('td');
          td.className = 'row-status-cell';
          td.innerHTML = `<button type="button" class="row-status-btn" data-slug="${slug}" data-status="待下单">待下单</button>`;
          tr.appendChild(td);
        });
      });
      this.fetchAllRowStatuses();
    },

    _slugify(text) {
      const cleaned = text
        .replace(/[\(\)\uff08\uff09]/g, ' ')
        .replace(/[^\u4e00-\u9fff\u3040-\u309f\u30a0-\u30ffa-zA-Z0-9 ]/g, '')
        .trim()
        .split(/\s+/)
        .slice(0, 4)
        .join('-')
        .toLowerCase();
      return cleaned || 'unknown';
    },

    async fetchAllRowStatuses() {
      try {
        const stored = JSON.parse(localStorage.getItem('rowStatusCache') || '{}');
        this.rowStatusCache = stored;
        for (const [slug, status] of Object.entries(stored)) {
          const btn = document.querySelector('.row-status-btn[data-slug="' + CSS.escape(slug) + '"]');
          if (btn) {
            btn.setAttribute('data-status', status);
            btn.textContent = status;
            btn.style.background = this.rowStatusColor(status);
            btn.style.color = '#fff';
          }
        }
      } catch (e) { console.warn('fetchAllRowStatuses failed:', e); }
    },

    rowStatus(slug) {
      if (!slug) return '待下单';
      return this.rowStatusCache[slug] || '待下单';
    },

    rowStatusColor(status) {
      return {
        '待下单':  '#9ca3af', '已下单':  '#3b82f6', '在途':    '#f59e0b',
        '已到货':  '#10b981', '已上架':  '#8b5cf6', '已售出':  '#059669',
        '已退货':  '#dc2626',
      }[status] || '#9ca3af';
    },

    VALID_ROW_STATUSES: ['待下单','已下单','在途','已到货','已上架','已售出','已退货'],

    async cycleRowStatus(slug, btn) {
      const current = this.rowStatus(slug);
      const idx = this.VALID_ROW_STATUSES.indexOf(current);
      const next = this.VALID_ROW_STATUSES[(idx + 1) % this.VALID_ROW_STATUSES.length];
      this.rowStatusCache[slug] = next;
      localStorage.setItem('rowStatusCache', JSON.stringify(this.rowStatusCache));
      if (btn) {
        btn.setAttribute('data-status', next);
        btn.textContent = next;
        btn.style.background = this.rowStatusColor(next);
        btn.style.color = '#fff';
      }
      try {
        await fetch('/api/orders/' + encodeURIComponent(slug), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status: next, notes: '从 simple-section 行点击标记' }),
        });
      } catch (e) { console.warn('cycleRowStatus sync failed:', e); }
    },

    bindRowStatusClicks() {
      document.addEventListener('click', (e) => {
        const btn = e.target.closest && e.target.closest('.row-status-btn');
        if (!btn) return;
        e.preventDefault();
        const slug = btn.getAttribute('data-slug');
        this.cycleRowStatus(slug, btn);
      });
    },

        async searchFlight() {
      if (!this.serverOnline) {
        this.flightResult = { ok: false, hint: 'API 离线,无法查机票' };
        return;
      }
      if (!this.flightOrigin || !this.flightDest || !this.flightDate) {
        this.flightResult = { ok: false, hint: '请填 IATA 机场三字码和日期' };
        return;
      }
      this.flightLoading = true;
      this.flightResult = null;
      try {
        const url = `/api/flight?origin=${encodeURIComponent(this.flightOrigin)}`
          + `&dest=${encodeURIComponent(this.flightDest)}`
          + `&date=${encodeURIComponent(this.flightDate)}`;
        const resp = await fetch(url);
        const body = await resp.json();
        this.flightResult = body;
      } catch (e) {
        this.flightResult = { ok: false, hint: '网络错误: ' + (e.message || e) };
      } finally {
        this.flightLoading = false;
      }
    },
  };
}
// ───────────────────────────────────────────────────────────────────
// invManager() — 库存管理组件 (Round 25, T5)
// Round 26: 整合 order_status badges 进 simple-section
// ───────────────────────────────────────────────────────────────────
function invManager() {
  return {
    invAddOpen: false,
    invItems: [],
    invSummary: { by_location: {}, total_qty: 0, total_value_cny: 0 },
    invForm: {
      sku: '',
      quantity: 1,
      location: '哥们仓(JP)',
      acquired_at: new Date().toISOString().slice(0, 10),
      acquired_cny: 0,
      listing_url: '',
    },

    async invInit() {
      await this.invRefresh();
    },

    async invRefresh() {
      try {
        const [itemsResp, sumResp] = await Promise.all([
          fetch('/api/inventory').then(r => r.json()),
          fetch('/api/inventory/summary').then(r => r.json()),
        ]);
        this.invItems = itemsResp.items || [];
        this.invSummary = sumResp || { by_location: {}, total_qty: 0, total_value_cny: 0 };
      } catch (e) {
        console.error('invRefresh failed:', e);
      }
    },

    invSummaryText() {
      const s = this.invSummary;
      if (!s.total_qty) return '(空)';
      return `(共 ${s.total_qty} 件 / ¥${(s.total_value_cny || 0).toFixed(0)})`;
    },

    invGroupedByLocation() {
      const groups = {};
      const order = ['哥们仓(JP)', '在途', '我家', '已上架-闲鱼', '已上架-eBay', '已上架-小红书'];
      for (const loc of order) groups[loc] = [];
      for (const it of this.invItems) {
        const k = it.location || '其他';
        if (!groups[k]) groups[k] = [];
        groups[k].push(it);
      }
      // drop empty groups
      return Object.entries(groups).filter(([_, arr]) => arr.length > 0);
    },

    async invAdd() {
      const f = this.invForm;
      if (!f.sku) { alert('请填 SKU'); return; }
      if (!f.acquired_cny || f.acquired_cny <= 0) { alert('请填成本'); return; }
      try {
        const resp = await fetch('/api/inventory', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sku: f.sku,
            quantity: f.quantity,
            location: f.location,
            acquired_at: f.acquired_at,
            acquired_cny: f.acquired_cny,
            total_cny: f.acquired_cny * f.quantity,
            listing_url: f.listing_url || null,
          }),
        });
        if (!resp.ok) throw new Error(await resp.text());
        // reset form
        this.invForm = {
          sku: '', quantity: 1, location: '哥们仓(JP)',
          acquired_at: new Date().toISOString().slice(0, 10),
          acquired_cny: 0, listing_url: '',
        };
        this.invAddOpen = false;
        await this.invRefresh();
      } catch (e) {
        alert('保存失败: ' + e.message);
      }
    },

    async invDelete(id) {
      if (!confirm('确认删除该项?')) return;
      try {
        await fetch(`/api/inventory/${id}`, { method: 'DELETE' });
        await this.invRefresh();
      } catch (e) {
        alert('删除失败: ' + e.message);
      }
    },

    async invMarkSold(id) {
      const priceStr = prompt('售出金额 (CNY)?', '0');
      if (priceStr === null) return;
      const soldPrice = parseFloat(priceStr);
      if (isNaN(soldPrice) || soldPrice < 0) { alert('金额无效'); return; }
      const channel = prompt('售出渠道?', '闲鱼') || '闲鱼';
      try {
        await fetch(`/api/inventory/${id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sold_at: new Date().toISOString().slice(0, 10),
            sold_price_cny: soldPrice,
            sold_channel: channel,
          }),
        });
        await this.invRefresh();
      } catch (e) {
        alert('标记售出失败: ' + e.message);
      }
    },
  };
}

// Register components with Alpine.js
document.addEventListener('alpine:init', () => {
  // app() and invManager() are defined globally for Alpine to find via x-data
});

// ───────────────────────────────────────────────────────────────────
// tripPlanner() — T9: 行程规划组件
// ───────────────────────────────────────────────────────────────────
function tripPlanner() {
  return {
    trips: [],
    quota: { remaining_cny: 5000, next_entry_cny: 5000, window_active: false, entries: [] },
    tripFormOpen: false,
    tripTab: 'all',
    tripForm: {
      destination: '大阪',
      start_date: new Date().toISOString().slice(0, 10),
      end_date: new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10),
      flight_out_cny: 0,
      flight_back_cny: 0,
      hotel_total_cny: 0,
    },
    itemForm: {
      channel: '线下',
      day_index: 1,
      sku_label: '',
      est_cny: 0,
      location_label: '',
    },
    tripItems: {},

    async tripInit() {
      await Promise.all([this.tripRefresh(), this.quotaRefresh()]);
    },

    async tripRefresh() {
      try {
        const resp = await fetch('/api/trips');
        this.trips = await resp.json();
        for (const trip of this.trips) {
          const r = await fetch(`/api/trips/${trip.id}`);
          const data = await r.json();
          this.tripItems[trip.id] = data.items || [];
        }
      } catch (e) { console.warn('tripRefresh failed:', e); }
    },

    async quotaRefresh() {
      try {
        const resp = await fetch('/api/quota');
        this.quota = await resp.json();
      } catch (e) { console.warn('quotaRefresh failed:', e); }
    },

    tripSummary() {
      if (!this.trips.length) return '(无行程)';
      const offlineTotal = this.trips.reduce((s, t) => s + this.tripOfflineTotal(t), 0);
      return `(${this.trips.length} 个行程 / 线下累计 ¥${offlineTotal.toFixed(0)})`;
    },

    tripIcon(dest) {
      return { '大阪': '🌸', '东京': '🗼', '京都': '⛩️', '名古屋': '🏯', '福冈': '🌊' }[dest] || '📍';
    },

    tripOfflineTotal(trip) {
      const items = this.tripItems[trip.id] || [];
      return items.filter(i => i.channel === '线下').reduce((s, i) => s + (i.est_cny || 0), 0);
    },

    tripItemsByChannel(tripId) {
      const items = this.tripItems[tripId] || [];
      if (this.tripTab === 'all') return items;
      return items.filter(i => i.channel === (this.tripTab === 'online' ? '线上' : '线下'));
    },

    async tripCreate() {
      const f = this.tripForm;
      try {
        await fetch('/api/trips', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(f),
        });
        this.tripFormOpen = false;
        await this.tripRefresh();
      } catch (e) { alert('创建失败: ' + e.message); }
    },

    async tripItemAdd(tripId) {
      const f = this.itemForm;
      if (!f.sku_label) { alert('请填 SKU 名'); return; }
      try {
        await fetch(`/api/trips/${tripId}/items`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            channel: f.channel,
            day_index: f.day_index,
            sku_label: f.sku_label,
            est_cny: f.est_cny,
            location_label: f.location_label || null,
            sku_slug: f.sku_label.replace(/\s+/g, '-').toLowerCase().slice(0, 30),
          }),
        });
        this.itemForm = { channel: '线下', day_index: 1, sku_label: '', est_cny: 0, location_label: '' };
        await this.tripRefresh();
      } catch (e) { alert('添加失败: ' + e.message); }
    },

    async tripItemDelete(itemId) {
      if (!confirm('删除该项?')) return;
      try {
        await fetch(`/api/trip-items/${itemId}`, { method: 'DELETE' });
        await this.tripRefresh();
      } catch (e) { alert('删除失败: ' + e.message); }
    },

    async quotaRecordEntry() {
      const today = new Date().toISOString().slice(0, 10);
      const entryCny = prompt(`记录今日入境 ¥ 额度? (默认 ¥${this.quota.next_entry_cny})`, this.quota.next_entry_cny.toString());
      if (entryCny === null) return;
      const cny = parseFloat(entryCny);
      if (isNaN(cny) || cny <= 0) { alert('金额无效'); return; }
      try {
        await fetch('/api/quota-window', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entry_date: today,
            entry_cny: cny,
            trip_id: this.trips[0]?.id || null,
            notes: '大阪 trip 入境',
          }),
        });
        await this.quotaRefresh();
      } catch (e) { alert('记录失败: ' + e.message); }
    },
  };
}



// ───────────────────────────────────────────────────────────────────
// T6: price alerts (±20% over 7d)
// ───────────────────────────────────────────────────────────────────
function priceAlertsManager() {
  return {
    priceAlerts: [],

    async priceAlertsRefresh() {
      try {
        const resp = await fetch('/api/alerts?window_days=7');
        const data = await resp.json();
        this.priceAlerts = data.alerts || data || [];
      } catch (e) { console.warn('priceAlertsRefresh failed:', e); }
    },

    alertBadgeFor(sku) {
      const a = this.priceAlerts.find(x => x.sku === sku);
      if (!a) return null;
      const dir = a.change_pct > 0 ? 'up' : 'down';
      const arrow = a.change_pct > 0 ? '↑' : '↓';
      return {
        class: dir,
        text: arrow + Math.abs(a.change_pct).toFixed(0) + '%',
        title: (a.field || 'price') + ': ¥' + a.old_price + ' → ¥' + a.new_price,
      };
    },

    topAlerts(limit) {
      const lim = limit || 3;
      return this.priceAlerts.slice(0, lim);
    },
  };
}



// ───────────────────────────────────────────────────────────────────
// T3: 价格缓存 + 自动算 spread
// ───────────────────────────────────────────────────────────────────
function priceSpreadCache() {
  return {
    cache: {},  // {sku: {buy_jpy, sell_cny, fetched_at}}
    spreadList: [],

    async priceSpreadRefresh() {
      try {
        const resp = await fetch('/api/prices/latest?limit=200');
        const data = await resp.json();
        this.cache = {};
        for (const r of (data.rows || data || [])) {
          this.cache[r.sku] = r;
        }
        this.computeSpreads();
      } catch (e) { console.warn('priceSpreadRefresh failed:', e); }
    },

    computeSpreads() {
      const out = [];
      for (const [sku, p] of Object.entries(this.cache)) {
        const buyJpy = p.buy_jpy || p.buy_price_jpy || 0;
        const sellCny = p.sell_cny || p.sell_price_cny || 0;
        if (!buyJpy || !sellCny) continue;
        // Spread = sellCny - buyJpy*0.05 (JPY→CNY 0.05)
        const buyCny = buyJpy * 0.05;
        const spread = sellCny - buyCny;
        const spreadPct = buyCny > 0 ? (spread / buyCny) * 100 : 0;
        out.push({ sku, buyJpy, buyCny, sellCny, spread, spreadPct });
      }
      this.spreadList = out.sort((a, b) => b.spreadPct - a.spreadPct);
    },

    spreadBadge(sku) {
      const item = this.spreadList.find(x => x.sku === sku);
      if (!item) return null;
      const pct = item.spreadPct;
      if (pct < 0) return { color: '#dc2626', text: '倒赔 ' + pct.toFixed(0) + '%' };
      if (pct >= 50) return { color: '#059669', text: '高利 +' + pct.toFixed(0) + '%' };
      if (pct >= 20) return { color: '#10b981', text: '+' + pct.toFixed(0) + '%' };
      return { color: '#6b7280', text: '+' + pct.toFixed(0) + '%' };
    },

    topBySpread(limit) {
      const lim = limit || 5;
      return this.spreadList.slice(0, lim);
    },
  };
}



// ───────────────────────────────────────────────────────────────────
// T2: liveSearch() — 实时多源搜索
// ───────────────────────────────────────────────────────────────────
function liveSearch() {
  return {
    lsQuery: '',
    lsLoading: false,
    lsResults: {},
    lsPasteHtml: '',
    lsPasteSource: 'auto',
    lsPasteResult: null,
    lsPasteLoading: false,

    async lsInit() {},

    async lsSearch() {
      if (!this.lsQuery.trim()) { alert('请输入搜索关键字'); return; }
      this.lsLoading = true;
      this.lsResults = {};
      try {
        const resp = await fetch('/api/live-search?q=' + encodeURIComponent(this.lsQuery));
        this.lsResults = await resp.json();
      } catch (e) {
        this.lsResults = { error: e.message };
      } finally {
        this.lsLoading = false;
      }
    },

    hasBlocked() {
      const r = this.lsResults;
      if (!r) return false;
      return (r.buyee && r.buyee.blocked) || (r.ebay_sold && r.ebay_sold.blocked) || (r.amazon_jp && r.amazon_jp.blocked);
    },

    async lsExtract() {
      if (!this.lsPasteHtml.trim()) { alert('请粘贴 HTML 源码'); return; }
      this.lsPasteLoading = true;
      try {
        const resp = await fetch('/api/live-extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ html: this.lsPasteHtml, source: this.lsPasteSource }),
        });
        this.lsPasteResult = await resp.json();
      } catch (e) {
        this.lsPasteResult = { reason: e.message };
      } finally {
        this.lsPasteLoading = false;
      }
    },
  };
}

