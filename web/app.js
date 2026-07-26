/* Alpine.js state for the jp-us-arb-route SPA.
 *
 * Single source of UI truth: pull /api/opportunities + /api/routes once,
 * then POST /api/decide on every selection (cheap, fully cached by FastAPI
 * memory if we add it later — for now, fine to recompute).
 *
 * No build step, no bundler, no framework lock-in.  CORS not needed because
 * the SPA is served from the same origin as the API.
 */
function app() {
  return {
    // ---- state ----
    loading: false,
    refreshing: false,
    verifying: false,
    status: '',
    dbPath: '',
    opportunities: [],
    routes: [],
    selected: null,
    detailCache: {},          // sku -> full decide response
    lastVerify: null,         // most-recent VerifyOutcome (for the detail pane)
    filter: '',
    origin: '上海 PVG',
    dest: '洛杉矶 LAX',
    departureDate: new Date().toISOString().slice(0, 10),
    targetRoi: 15.0,
    numUnits: 5,
    errorMsg: '',

    // ---- derived ----
    get currentDetail() { return this.selected ? this.detailCache[this.selected] : null; },
    filtered() {
      const q = this.filter.trim().toLowerCase();
      if (!q) return this.opportunities;
      return this.opportunities.filter(o =>
        (o.sku || '').toLowerCase().includes(q) ||
        (o.name || '').toLowerCase().includes(q) ||
        (o.category || '').toLowerCase().includes(q));
    },

    // ---- lifecycle ----
    async init() {
      this.setStatus('加载商机与路线…');
      try {
        const [opps, routes, health] = await Promise.all([
          fetch('/api/opportunities').then(r => r.json()),
          fetch('/api/routes').then(r => r.json()),
          fetch('/api/health').then(r => r.json()),
        ]);
        this.opportunities = opps;
        this.routes = routes;
        this.dbPath = health.db || '';
        if (routes.length) {
          this.origin = routes[0].origin_city;
          this.dest = routes[0].dest_city;
        }
        this.setStatus(`就绪 · ${opps.length} 个商机 · ${routes.length} 条路线`);
      } catch (e) {
        this.setStatus('API 加载失败: ' + e.message, true);
      }
    },

    // ---- actions ----
    async select(sku) {
      this.selected = sku;
      if (this.detailCache[sku]) return;
      this.loading = true;
      try {
        const routeName = this.matchRouteName();
        const resp = await fetch('/api/decide', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sku, num_units: this.numUnits, route: routeName }),
        });
        if (!resp.ok) {
          this.setStatus('决策失败: ' + (await resp.text()), true);
          return;
        }
        this.detailCache[sku] = await resp.json();
        this.setStatus(`${sku} 决策已刷新 · ROI ${this.detailCache[sku].decision.roi_pct.toFixed(1)}%`);
      } catch (e) {
        this.setStatus('决策异常: ' + e.message, true);
      } finally {
        this.loading = false;
      }
    },

    async refetch() {
      // Re-decide all cached opps with new units / target ROI.
      this.detailCache = {};
      if (this.selected) await this.select(this.selected);
      this.setStatus(`已按 数量=${this.numUnits} 目标ROI=${this.targetRoi}% 刷新`);
    },

    matchRouteName() {
      const r = this.routes.find(r => r.origin_city === this.origin && r.dest_city === this.dest);
      return r ? r.name : (this.routes[0] && this.routes[0].name);
    },

    exportUrl(fmt) {
      if (!this.selected) return '';
      const sku = encodeURIComponent(this.selected);
      const route = encodeURIComponent(this.matchRouteName() || '');
      return `/api/report/${sku}.${fmt}?num_units=${this.numUnits}&route=${route}`;
    },

    async exportMd() {
      const url = this.exportUrl('md');
      if (!url) return;
      this.downloadFromUrl(url, this.suggestFilename('md'));
    },
    async exportHtml() {
      const url = this.exportUrl('html');
      if (!url) return;
      this.downloadFromUrl(url, this.suggestFilename('html'));
    },
    async exportPdf() {
      const url = this.exportUrl('pdf');
      if (!url) return;
      this.setStatus('PDF 渲染中…');
      this.downloadFromUrl(url, this.suggestFilename('pdf'));
      this.setStatus('PDF 已生成');
    },

    suggestFilename(ext) {
      const today = new Date().toISOString().slice(0, 10);
      const sku = (this.selected || 'report').replace(/[^A-Za-z0-9_-]/g, '_');
      const dest = (this.dest || 'dest').replace(/[^A-Za-z0-9_-]/g, '_');
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
        this.setStatus('下载失败: ' + e.message, true);
      }
    },

    // ---- formatters ----
    badgeClass(level) {
      return { '建议': 'ok', '谨慎': 'warn', '不建议': 'bad' }[level] || 'muted';
    },
    badgeText(level) {
      return { '建议': '✅ 建议', '谨慎': '⚠️ 谨慎', '不建议': '❌ 不建议' }[level] || '—';
    },
    roiClass(roi) {
      if (roi >= this.targetRoi) return 'ok';
      if (roi >= (this.targetRoi - 5)) return 'warn';
      return 'bad';
    },
    freshClass(o) {
      // Map freshness.status -> CSS class for the badge pill.
      const f = o && o.freshness;
      if (!f) return '';
      if (f.status === 'stale' || f.status === 'missing' || f.status === 'future') return 'stale';
      return f.status;  // fresh | aging
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

    // ---- refresh flow ----
    async refreshOpportunity() {
      if (!this.selected) return;
      this.refreshing = true;
      try {
        const sku = encodeURIComponent(this.selected);
        const resp = await fetch(`/api/opportunities/${sku}/refresh`, {
          method: 'POST',
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const out = await resp.json();
        if (out.updated) {
          // Bump freshness in the cached opp list so UI reflects immediately.
          const idx = this.opportunities.findIndex(o => o.sku === this.selected);
          if (idx >= 0) {
            this.opportunities[idx].data_freshness_ts = out.new_freshness_ts;
            this.opportunities[idx].freshness = out.verdict_after;
          }
          // The detail pane has its own snapshot of opp — patch it too.
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

    // ---- verify flow (Round 4) ----
    async verifyOpportunity() {
      if (!this.selected) return;
      this.verifying = true;
      try {
        const sku = encodeURIComponent(this.selected);
        const resp = await fetch(`/api/opportunities/${sku}/verify`, {
          method: 'POST',
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const out = await resp.json();
        this.lastVerify = out;
        // Patch the cached opp list with the new freshness + verified state.
        const idx = this.opportunities.findIndex(o => o.sku === this.selected);
        if (idx >= 0) {
          if (out.final_freshness_ts) {
            this.opportunities[idx].data_freshness_ts = out.final_freshness_ts;
          }
          this.opportunities[idx].verified = !!out.final_verified;
        }
        if (this.detailCache[this.selected]) {
          if (out.final_freshness_ts) {
            this.detailCache[this.selected].opp.data_freshness_ts = out.final_freshness_ts;
          }
          this.detailCache[this.selected].opp.verified = !!out.final_verified;
        }
        const proposalCount = (out.purchase.proposal_id ? 1 : 0) +
                              (out.sell.proposal_id ? 1 : 0);
        if (out.verified_now) {
          this.setStatus(`${this.selected} 已验证 ✓ (容差内)`);
        } else if (proposalCount > 0) {
          this.setStatus(`${this.selected} 漂移超出容差,已 stage ${proposalCount} 条提案`);
        } else {
          this.setStatus(`${this.selected} ${out.message}`);
        }
      } catch (e) {
        this.setStatus('验证失败: ' + e.message, true);
      } finally {
        this.verifying = false;
      }
    },

    setStatus(msg, isError = false) {
      this.status = msg;
      this.errorMsg = isError ? msg : '';
    },
  };
}