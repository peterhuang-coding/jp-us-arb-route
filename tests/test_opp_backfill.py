"""阶段0: legacy → opp 回填 — dry-run 零写入 / 映射正确 / 幂等 / 财务 NULL."""
from __future__ import annotations

import pytest

from arb import db
from arb.opp import backfill, sync


# ---------- legacy fixture ----------

def _seed_legacy(conn):
    """构造覆盖全部映射分支的 legacy 数据."""
    def opp(sku, name, verified=0):
        conn.execute(
            "INSERT INTO opportunities (sku,name,category,source_market,target_market,"
            "purchase_price_usd,sell_price_usd,data_freshness_ts,verified) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (sku, name, "test", "JP", "CN", 10.0, 20.0, "2026-09-01", verified),
        )

    def ev(sku, side, channel, ptype, price, observed="2026-08", url="http://x"):
        conn.execute(
            "INSERT INTO evidence_log (sku,side,channel_name,channel_url,price_cny,"
            "price_type,source_url,observed_at) VALUES (?,?,?,?,?,?,?,?)",
            (sku, side, channel, url, price, ptype, url, observed),
        )

    opp("SKU-QUAL", "合格样例", verified=1)
    ev("SKU-QUAL", "buy", "Fa-So-La 免税", "tax-free", 900)
    ev("SKU-QUAL", "buy", "日本亚马逊", "retail", 950)
    ev("SKU-QUAL", "sell", "闲鱼", "挂单", 1200)
    ev("SKU-QUAL", "sell", "得物", "成交", 1300)     # sold → 可执行退出
    ev("SKU-QUAL", "sell", "爱回收", "recycle", 1100)  # buyback
    ev("SKU-QUAL", "sell", "朋友圈 / 微商", "self-use-baseline", 1250)  # sell→ask

    opp("SKU-DISC", "仅发现样例", verified=0)
    ev("SKU-DISC", "buy", "药妆店", "retail", 300)

    opp("SKU-WEAK", "只有挂单样例", verified=1)
    ev("SKU-WEAK", "buy", "Bic Camera", "tax-free", 2000)
    ev("SKU-WEAK", "sell", "闲鱼", "挂单", 2600)
    ev("SKU-WEAK", "sell", "转转", "挂单", 2550)

    # competitor_prices → ask / buy 侧
    conn.execute(
        "INSERT INTO competitor_prices (opportunity_id,sku,source,price_jpy,price_cny,"
        "fx_rate_at_fetch,fx_source,url,fetched_at) "
        "SELECT id,'SKU-QUAL','amazon_jp',20000,960,20.8,'fawazahmed0','http://a',"
        "'2026-09-01 10:00:00' FROM opportunities WHERE sku='SKU-QUAL'",
    )

    # 候选 (无 sku → CAND-{id}) → discovered
    conn.execute(
        "INSERT INTO sku_candidates (name,category,buy_price_usd,sell_price_usd) "
        "VALUES ('候选样例','test',5,10)",
    )

    # inventory 哥们仓 → acquired
    conn.execute(
        "INSERT INTO inventory (sku,quantity,location,acquired_at,acquired_cny,total_cny) "
        "VALUES ('SKU-ACQ',1,'哥们仓(JP)','2026-08-10',120.0,120.0)",
    )
    # order_status 已上架 → listed (order_status 无 listed_at 列, 用 updated_at)
    conn.execute(
        "INSERT INTO order_status (sku,status,updated_at) VALUES ('SKU-LST','已上架','2026-08-12T00:00:00')",
    )
    # order_status 已售出 → sold
    conn.execute(
        "INSERT INTO order_status (sku,status,sold_at,sold_price_cny,sold_channel) "
        "VALUES ('SKU-SLD','已售出','2026-08-15',950.0,'闲鱼')",
    )
    # order_status 已退货 → acquired (货退回在手)
    conn.execute(
        "INSERT INTO order_status (sku,status,ordered_at,arrived_at) "
        "VALUES ('SKU-RET','已退货','2026-07-01','2026-07-05')",
    )
    # returns → settled (有 inventory 匹配 → actual net 可算)
    conn.execute(
        "INSERT INTO inventory (sku,quantity,location,acquired_at,acquired_cny,total_cny,"
        "sold_at,sold_price_cny,sold_channel) VALUES "
        "('SKU-SET',1,'已上架-闲鱼','2026-08-01',800.0,800.0,'2026-08-15',950.0,'闲鱼')",
    )
    conn.execute(
        "INSERT INTO returns (sku,sold_at,sold_price_cny,sold_channel,returned_at,"
        "return_reason,refund_cny,restocking_cost_cny) "
        "VALUES ('SKU-SET','2026-08-15',950.0,'闲鱼','2026-08-20','客户退货',950.0,0.0)",
    )
    # feedback bad 且无其他信号 → rejected
    conn.execute(
        "INSERT INTO sku_feedback (sku,status,reason) VALUES ('SKU-REJ','bad','卖不动')",
    )
    conn.commit()


@pytest.fixture
def legacy_conn():
    conn = db.connect_memory()
    _seed_legacy(conn)
    return conn


# ---------- schema ----------

def test_new_tables_exist():
    conn = db.connect_memory()
    for t in ("opp_items", "item_aliases", "opp_cases", "evidence", "opp_status_events"):
        cols = db._table_columns(conn, t)
        assert "id" in cols
    # 双币列 + 72h 过期列
    ev_cols = db._table_columns(conn, "evidence")
    assert {"original_amount", "original_currency", "fx_rate", "expires_at"} <= ev_cols
    case_cols = db._table_columns(conn, "opp_cases")
    assert {"est_exit_kind", "est_exit_sample_count"} <= case_cols
    conn.close()


# ---------- dry-run ----------

def test_dry_run_writes_nothing(legacy_conn):
    report = backfill.run(legacy_conn, dry_run=True)
    assert report["dry_run"] is True
    assert report["written"] is None
    for t in ("opp_items", "item_aliases", "evidence", "opp_cases", "opp_status_events"):
        assert legacy_conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0


def test_dry_run_preview_counts(legacy_conn):
    report = backfill.run(legacy_conn, dry_run=True)
    c = report["plan_counts"]
    # SKU-QUAL/DISC/WEAK/ACQ/LST/SLD/RET/SET/REJ + 1 CAND = 10 items
    assert c["items"] == 10
    assert c["cases"] == 10
    by = c["by_status"]
    assert by.get("qualified") == 2     # SKU-QUAL, SKU-WEAK (legacy verified=1)
    assert by.get("discovered") == 2    # SKU-DISC + CAND
    assert by.get("acquired") == 2      # SKU-ACQ + SKU-RET
    assert by.get("listed") == 1        # SKU-LST
    assert by.get("sold") == 1          # SKU-SLD
    assert by.get("settled") == 1       # SKU-SET
    assert by.get("rejected") == 1      # SKU-REJ
    # ready 永不回填
    assert "ready" not in by
    assert "participating" not in by


# ---------- apply: 映射正确性 ----------

def test_apply_maps_evidence_kinds(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    kinds = {
        (r["kind"], r["side"], r["source_ref"]): r
        for r in legacy_conn.execute("SELECT * FROM evidence")
    }
    # tax-free/retail → retail/buy
    assert ("retail", "buy", "Fa-So-La 免税") in kinds
    assert ("retail", "buy", "日本亚马逊") in kinds
    # 成交 → sold
    assert ("sold", "sell", "得物") in kinds
    # recycle → buyback
    assert ("buyback", "sell", "爱回收") in kinds
    # 挂单 → ask
    assert ("ask", "sell", "闲鱼") in kinds
    # sell 侧 self-use-baseline → ask (risk §②)
    assert ("ask", "sell", "朋友圈 / 微商") in kinds
    # competitor_prices → ask/buy
    assert ("ask", "buy", "amazon_jp") in kinds
    # 月份粒度降 confidence + observed_at 取月初
    row = kinds[("retail", "buy", "Fa-So-La 免税")]
    assert row["observed_at"] == "2026-08-01T00:00:00"
    assert row["confidence"] == 0.6
    # competitor 快照完整时间戳 + 高 confidence
    snap = kinds[("ask", "buy", "amazon_jp")]
    assert snap["observed_at"] == "2026-09-01T10:00:00"
    assert snap["confidence"] == 0.8
    # 双币列阶段0 legacy 一律 NULL (不为旧数据强行补原始币/汇率; 原始 JPY/fx
    # 仅记录在 payload_json 供追溯, 阶段1 JP 采购才正式入双币列).
    assert row["original_amount"] is None and row["original_currency"] is None
    assert snap["original_amount"] is None and snap["original_currency"] is None
    assert snap["fx_rate"] is None and snap["price_cny"] == 960.0
    import json as _json
    snap_payload = _json.loads(snap["payload_json"])
    assert snap_payload["price_jpy"] == 20000.0   # 原始信息保留在 payload
    # legacy 月份粒度不跟踪新鲜度: expires_at 一律 NULL (72h TTL 仅阶段1 实时证据)
    sold = kinds[("sold", "sell", "得物")]
    assert sold["expires_at"] is None
    assert kinds[("ask", "sell", "闲鱼")]["expires_at"] is None


def test_apply_statuses_and_reasons(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    cases = {r["item_key"]: r for r in
             legacy_conn.execute("SELECT * FROM opp_cases")}
    assert cases["SKU-QUAL"]["status"] == "qualified"
    assert cases["SKU-WEAK"]["status"] == "qualified"   # legacy verified 映射保留
    assert cases["SKU-SET"]["status"] == "settled"
    assert cases["SKU-SLD"]["status"] == "sold"
    assert cases["SKU-LST"]["status"] == "listed"
    assert cases["SKU-ACQ"]["status"] == "acquired"
    assert cases["SKU-RET"]["status"] == "acquired"
    assert cases["SKU-REJ"]["status"] == "rejected"
    # 每行必须有 status_reason (启发式依据可追溯)
    for c in cases.values():
        assert c["status_reason"]
        assert c["origin"] == "legacy-backfill"
    # 已退货的依据写进 reason
    assert "已退货" in cases["SKU-RET"]["status_reason"]


def test_apply_events_funnel(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    evs = list(legacy_conn.execute(
        "SELECT to_status FROM opp_status_events WHERE item_key='SKU-SET' ORDER BY id"))
    seq = [r["to_status"] for r in evs]
    # 没有 verified=1 → discovered 直接到 acquired... inventory 已上架→listed→sold→settled
    assert seq[0] == "discovered"
    assert seq[-1] == "settled"
    assert "listed" in seq and "sold" in seq
    # rejected 事件
    rej = list(legacy_conn.execute(
        "SELECT to_status FROM opp_status_events WHERE item_key='SKU-REJ'"))
    assert [r["to_status"] for r in rej] == ["discovered", "rejected"]


def test_apply_finance_nulls_and_actuals(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    cases = {r["item_key"]: r for r in
             legacy_conn.execute("SELECT * FROM opp_cases")}
    # 预计净利/利润率/资金占用/周期: legacy 无 CNY 费用口径 → 全 NULL
    for key, c in cases.items():
        assert c["est_net_profit_cny"] is None, key
        assert c["margin_pct"] is None, key
        assert c["capital_occupation_cny"] is None, key
        assert c["sell_cycle_days"] is None, key
        assert c["forecast_error_cny"] is None, key
    # est_* 阶段0 legacy 一律 NULL (缺同规格近期可执行 CNY 样本, 不强行估算;
    # 退出价口径函数 buyback>bid>sold 中位数在 finance 单测, 阶段1 使用).
    for key in ("SKU-QUAL", "SKU-WEAK"):
        assert cases[key]["est_buy_cny"] is None, key
        assert cases[key]["est_exit_cny"] is None, key
        assert cases[key]["est_exit_kind"] is None, key
        assert cases[key]["est_exit_sample_count"] is None, key
    # settled 实际值: buy=800, exit=950, refund=950 → 950-950-0-800 = -800
    sett = cases["SKU-SET"]
    assert sett["actual_buy_cny"] == 800.0
    assert sett["actual_exit_cny"] == 950.0
    assert sett["actual_net_profit_cny"] == -800.0
    assert sett["capital_days"] == 19        # 2026-08-01 → 2026-08-20
    # acquired 样例: 实际成本来自 inventory.acquired_cny
    assert cases["SKU-ACQ"]["actual_buy_cny"] == 120.0


def test_apply_gate_check_qualified_counts_weak_signals(legacy_conn):
    # qualified 计数集 = bid/buyback/sold/ask/heat/rumor (同 source_ref 去重):
    # SKU-WEAK 有闲鱼/转转 2 个独立 ask 来源 + 1 个 tax-free 供给 → qualified 过,
    # 但无 bid/buyback/sold → ready 不过 (only_weak_exit).
    # SKU-QUAL 有 ask×2/sold/buyback 四个独立来源 → qualified 过, 且含
    # sold/buyback (legacy expires_at=NULL, 不套新鲜度) → has_executable_exit
    # 为 True; ready 仍因 human_confirmed=False 不满足.
    report = backfill.run(legacy_conn, dry_run=True)
    gates = {g["item_key"]: g for g in report["gate_checks"]}
    assert gates["SKU-WEAK"]["only_weak_exit"] is True
    assert gates["SKU-WEAK"]["qualified_gate_ok"] is True
    assert gates["SKU-WEAK"]["exit_signal_count"] == 2
    assert gates["SKU-WEAK"]["ready_gate_ok"] is False
    assert gates["SKU-QUAL"]["qualified_gate_ok"] is True
    assert gates["SKU-QUAL"]["exit_signal_count"] == 4
    assert gates["SKU-QUAL"]["has_executable_exit"] is True   # sold/buyback, NULL 不惩罚
    assert gates["SKU-QUAL"]["expired_exit_count"] == 0
    assert gates["SKU-QUAL"]["ready_gate_ok"] is False        # 未人工确认
    # SKU-DISC: 只有 1 条 buy retail, 0 退出信号 → qualified 不过
    assert gates["SKU-DISC"]["qualified_gate_ok"] is False


def test_phase0_no_runtime_expiry_demotion(legacy_conn):
    """阶段0: legacy 回填证据 expires_at 一律 NULL, 不做 72h 过期降级
    (72h + ready→qualified 属阶段1 实时摄入逻辑). sync 不提供降级扫描."""
    from arb.opp import sync as sync_mod
    backfill.run(legacy_conn, dry_run=False)
    # 全部 backfill 证据 expires_at NULL
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM evidence WHERE expires_at IS NOT NULL").fetchone()[0] == 0
    # backfill 派生状态最高到 qualified, 不会因过期产生 failed/其他回退
    # (ready 不回填); sync 阶段0 不暴露降级扫描函数
    assert not hasattr(sync_mod, "find_expired_demotions")


def test_phase0_evidence_dual_currency_columns_nullable():
    """双币列存在且默认 NULL (阶段1 JP 采购才填)."""
    conn = db.connect_memory()
    conn.execute(
        "INSERT INTO evidence (item_key,kind,side,source_kind,source_ref,"
        "observed_at) VALUES ('X','sold','sell','marketplace','渠道','2026-09-01T00:00:00')")
    conn.commit()
    row = conn.execute("SELECT * FROM evidence WHERE item_key='X'").fetchone()
    assert row["original_amount"] is None
    assert row["original_currency"] is None
    assert row["fx_rate"] is None
    assert row["price_cny"] is None
    conn.close()


# ---------- 幂等 ----------

def test_apply_is_idempotent(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    n_items = legacy_conn.execute("SELECT COUNT(*) FROM opp_items").fetchone()[0]
    n_ev = legacy_conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
    n_cases = legacy_conn.execute("SELECT COUNT(*) FROM opp_cases").fetchone()[0]
    n_events = legacy_conn.execute("SELECT COUNT(*) FROM opp_status_events").fetchone()[0]

    report2 = backfill.run(legacy_conn, dry_run=False)
    w = report2["written"]
    assert w["evidence_new"] == 0          # INSERT OR IGNORE
    assert w["cases_inserted"] == 0
    assert w["cases_updated"] == n_cases
    assert legacy_conn.execute("SELECT COUNT(*) FROM opp_items").fetchone()[0] == n_items
    assert legacy_conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == n_ev
    assert legacy_conn.execute("SELECT COUNT(*) FROM opp_cases").fetchone()[0] == n_cases
    assert legacy_conn.execute(
        "SELECT COUNT(*) FROM opp_status_events").fetchone()[0] == n_events


def test_manual_case_not_clobbered(legacy_conn):
    backfill.run(legacy_conn, dry_run=False)
    # 模拟人工接管: 删掉 backfill 行, 建手工 ready case, 再重跑 backfill
    legacy_conn.execute("DELETE FROM opp_status_events WHERE item_key='SKU-DISC'")
    legacy_conn.execute("DELETE FROM opp_cases WHERE item_key='SKU-DISC'")
    legacy_conn.execute(
        "INSERT INTO opp_cases (item_key,opp_type,status,origin,status_reason) "
        "VALUES ('SKU-DISC','spread','ready','manual','人工批准')",
    )
    legacy_conn.commit()
    w = backfill.run(legacy_conn, dry_run=False)["written"]
    assert w["cases_skipped_manual"] >= 1
    rows = list(legacy_conn.execute(
        "SELECT status,origin FROM opp_cases WHERE item_key='SKU-DISC'"))
    # 手工行保留 ready/manual; backfill 没有覆盖也没有插入第二行 (UNIQUE item+type)
    assert len(rows) == 1
    assert rows[0]["status"] == "ready"
    assert rows[0]["origin"] == "manual"


def test_legacy_item_keys_union(legacy_conn):
    keys = set(sync.legacy_item_keys(legacy_conn))
    assert "SKU-REJ" in keys          # 只在 sku_feedback
    assert "SKU-ACQ" in keys          # 只在 inventory
    assert any(k.startswith("CAND-") for k in keys)  # 无 sku 候选
