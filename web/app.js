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

    // ---- form state ----
    selected: null,

    // ---- flight lookup (Round 16) ----
    flightOrigin: 'PVG',
    flightDest: 'LAX',
    flightDate: new Date().toISOString().slice(0, 10),
    flightLoading: false,
    flightResult: null,
    flightHint: '',
    filter: '',
    filterCategory: '',
    filterStatus: '',
    routeName: '',            // current route (e.g. "PVG-NRT-LAX-2N")
    numUnits: 50,
    origin: '上海 PVG',
    dest: '洛杉矶 LAX',

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
        if (health) this.dbPath = health.db || '';
        this.snapshotAt = health ? 'API live' : (EMBEDDED_DATA?.snapshot_at || '');
        this.setStatus(`API 在线 · ${opps.length} 商机 · ${routes.length} 路线`);
      } catch (e) {
        this.hydrateFromSnapshot();
        this.serverOnline = false;
        this.setStatus('API 离线 · 使用本地快照 ' + (EMBEDDED_DATA?.snapshot_at || ''));
      }

      // Attach freshness verdicts if missing (snapshot doesn't include them).
      this.opportunities = this.opportunities.map(o => {
        if (o.freshness) return o;
        return { ...o, freshness: this.computeFreshness(o.data_freshness_ts, o.sku) };
      });

      // Hydrate detailCache from snapshot for offline-friendly PICK rendering.
      this.hydrateDetailCacheFromSnapshot();

      // Default route selection.
      if (this.routes.length) {
        this.routeName = this.routes[0].name;
        this.origin = this.routes[0].origin_city;
        this.dest = this.routes[0].dest_city;
      }

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