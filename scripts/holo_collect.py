#!/usr/bin/env python3
"""holo_collect.py — 每股全息数据采集器 v1
用法: python3 holo_collect.py --from sh600000 --to sh603999 [--limit 50]
从 stock.duckdb/wh + 实时接口采集九面数据, 每股一文件夹, 输出 local tree, 由 holo_push.py 推仓.
段位登记: 远端 REGISTRY.json (多AI协同防重复).
不构成投资建议。
"""
import json, urllib.request, duckdb, datetime, os, sys, time, argparse

BASE = "/home/agentuser/stockdb"
OUT = "/home/agentuser/stockdb/holo"
UA = {"User-Agent": "Mozilla/5.0"}

def get_json(u, headers=None, timeout=15):
    h = dict(UA)
    if headers: h.update(headers)
    return json.loads(urllib.request.urlopen(urllib.request.Request(u, headers=h), timeout=timeout).read().decode("utf-8", "ignore"))

def now():
    return datetime.datetime.now().isoformat(timespec="seconds")

def fresh_symbol_list(con):
    """主板全列表(来自daily最新日)"""
    rows = con.execute("SELECT DISTINCT symbol FROM daily WHERE symbol LIKE 'sh60%' OR symbol LIKE 'sz00%'").fetchall()
    return sorted(r[0] for r in rows)

def collect_kline(con, sym):
    """日K全史含成交量(wh parquet>duckdb), 换手率需流通股本(用成交额/价格近似或东财). 简化: volume+amount从腾讯kline"""
    return None  # kline从腾讯接口拉全史(含换手率字段更全)

def tencent_kline(sym, count=800):
    """腾讯日K(近800日, 含成交量)"""
    u = f"https://ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{count},qfq"
    try:
        d = get_json(u)
        dd = d["data"][sym]
        days = dd.get("qfqday") or dd.get("day") or []
        return [{"date": x[0], "open": float(x[1]), "close": float(x[2]), "high": float(x[3]),
                 "low": float(x[4]), "volume": float(x[5])} for x in days]
    except Exception:
        return []

def sina_moneyflow(sym, num=100):
    code = sym[2:]
    u = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_qsfx_lscjfb?page=1&num={num}&sort=opendate&asc=0&daima={sym}"
    try:
        rows = get_json(u)
        return [{"date": r["opendate"], "net_in_wan": float(r.get("netamount", 0)),
                 "r0_net_wan": float(r.get("r0_net", 0)),
                 "main_net_ratio": float(r.get("zljlr", 0)) if r.get("zljlr") else None} for r in rows]
    except Exception:
        return []

def calc_technical(kline):
    """技术面: MACD/KDJ/RSI/BOLL/MA/量比/240日位 — 纯python"""
    if len(kline) < 60:
        return None
    closes = [k["close"] for k in kline]
    vols = [k["volume"] for k in kline]
    highs = [k["high"] for k in kline]
    lows = [k["low"] for k in kline]
    # EMA/MACD
    def ema(vals, n):
        e = [vals[0]]
        k = 2 / (n + 1)
        for v in vals[1:]:
            e.append(e[-1] + k * (v - e[-1]))
        return e
    e12, e26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, 9)
    macd = [(d - m) * 2 for d, m in zip(dif, dea)]
    # MA
    def ma(vals, n):
        return [sum(vals[max(0, i - n + 1):i + 1]) / min(i + 1, n) for i in range(len(vals))]
    ma5, ma10, ma20, ma60 = ma(closes, 5), ma(closes, 10), ma(closes, 20), ma(closes, 60)
    # RSI(14)
    gains, losses = [], []
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        gains.append(max(ch, 0)); losses.append(max(-ch, 0))
    rsi = None
    if len(gains) >= 14:
        ag = sum(gains[-14:]) / 14; al = sum(losses[-14:]) / 14
        rsi = 100 * ag / (ag + al) if (ag + al) else 50
    # KDJ(9)
    kdj_k = kdj_d = None
    if len(closes) >= 9:
        hn = max(highs[-9:]); ln = min(lows[-9:])
        rsv = (closes[-1] - ln) / (hn - ln) * 100 if hn > ln else 50
        kdj_k, kdj_d = rsv, rsv  # 简化首值
    # BOLL(20)
    mid = sum(closes[-20:]) / 20
    sd = (sum((c - mid) ** 2 for c in closes[-20:]) / 20) ** 0.5
    # 240日位/量比
    hi240 = max(highs[-240:]); lo240 = min(lows[-240:])
    pos240 = (closes[-1] - lo240) / (hi240 - lo240) if hi240 > lo240 else 0.5
    vr = (sum(vols[-5:]) / 5) / (sum(vols[-65:-5]) / 60) if len(vols) > 65 and sum(vols[-65:-5]) else None
    last_n = 30
    return {
        "macd": {"dif": round(dif[-1], 4), "dea": round(dea[-1], 4), "hist": round(macd[-1], 4),
                 "hist_series": [round(x, 4) for x in macd[-last_n:]]},
        "kdj": {"k": round(kdj_k, 1) if kdj_k else None, "d": round(kdj_d, 1) if kdj_d else None},
        "rsi14": round(rsi, 1) if rsi else None,
        "boll": {"mid": round(mid, 2), "up": round(mid + 2 * sd, 2), "low": round(mid - 2 * sd, 2)},
        "ma": {"ma5": round(ma5[-1], 2), "ma10": round(ma10[-1], 2), "ma20": round(ma20[-1], 2), "ma60": round(ma60[-1], 2)},
        "pos240_pct": round(pos240 * 100, 1),
        "volume_ratio": round(vr, 2) if vr else None,
    }

def eastmoney_finance(code):
    """基本面: 东财datacenter 主要指标(年报)"""
    u = (f"https://datacenter-web.eastmoney.com/api/data/v1/get?reportName=RPT_LICO_FN_CPD&columns=ALL"
         f"&pageSize=8&pageNumber=1&filter=(SECURITY_CODE%3D%22{code}%22)&sortColumns=REPORTDATE&sortTypes=-1&source=WEB&client=WEB")
    try:
        d = get_json(u)
        rows = (d.get("result") or {}).get("data") or []
        out = []
        for r in rows:
            out.append({"report_date": str(r.get("REPORTDATE", ""))[:10],
                        "revenue_yi": round(float(r.get("TOTAL_OPERATE_INCOME") or 0) / 1e8, 2),
                        "profit_yi": round(float(r.get("PARENT_NETPROFIT") or 0) / 1e8, 2),
                        "yoy_rev": r.get("TOTAL_OPERATE_INCOME_TB"), "yoy_profit": r.get("PARENT_NETPROFIT_TB"),
                        "roe": r.get("WEIGHTAVG_ROE"), "eps": r.get("BASIC_EPS")})
        return out
    except Exception:
        return []

def stock_news(sym):
    """消息面: 东财个股公告+新闻"""
    code = sym[2:]
    out = []
    # 公告
    try:
        u = (f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=15&page_index=1"
             f"&ann_type=A&stock_list={code}")
        d = get_json(u)
        for a in (d.get("data") or {}).get("list") or []:
            out.append({"title": a.get("title"), "date": str(a.get("notice_date", ""))[:10],
                        "url": f"https://data.eastmoney.com/notices/detail/{code}/{a.get('art_code')}.html",
                        "kind": "ann"})
    except Exception:
        pass
    return out[:30]

def sentiment_hits(sym, code):
    """情绪面: em_ztpool命中 + 千股千评"""
    out = {}
    try:
        con = duckdb.connect(f"{BASE}/stock.duckdb", read_only=True)
        zt = con.execute("SELECT date, pool, lbc, zbc, fbt FROM em_ztpool WHERE code=? ORDER BY date DESC LIMIT 30", [code]).fetchall()
        con.close()
        if zt:
            out["pool_hits"] = [{"date": r[0], "pool": r[1], "lbc": r[2], "zbc": r[3], "fbt": r[4]} for r in zt]
    except Exception:
        pass
    return out

def profile_from_duckdb(con, sym):
    r = con.execute("SELECT count(*), min(date), max(date) FROM daily WHERE symbol=?", [sym]).fetchone()
    return {"db_bars": r[0], "db_from": r[1], "db_to": r[2]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="f", required=True)
    ap.add_argument("--to", dest="t", required=True)
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    con = duckdb.connect(f"{BASE}/stock.duckdb", read_only=True)
    allsyms = fresh_symbol_list(con)
    seg = [s for s in allsyms if args.f <= s <= args.t][:args.limit]
    print(f"段位 {args.f}..{args.t}: 命中{len(seg)}只(限{args.limit})")
    os.makedirs(OUT, exist_ok=True)
    for i, sym in enumerate(seg):
        code = sym[2:]
        d = f"{OUT}/{sym}"
        os.makedirs(d, exist_ok=True)
        try:
            kline = tencent_kline(sym)
            time.sleep(0.15)
            tech = calc_technical(kline)
            flow = sina_moneyflow(sym)
            time.sleep(0.3)
            fin = eastmoney_finance(code)
            time.sleep(0.2)
            news = stock_news(sym)
            senti = sentiment_hits(sym, code)
            prof = profile_from_duckdb(con, sym)
            last = kline[-1] if kline else {}
            meta = {"symbol": sym, "updated_at": now(), "db": prof,
                    "provenance": {"kline": "tencent_fqkline", "moneyflow": "sina_moneyflow",
                                   "finance": "east_datacenter", "news": "sina",
                                   "technical": "calc_local", "sentiment": "em_push2ex"},
                    "stale_hours": 0}
            json.dump(meta, open(f"{d}/meta.json", "w"), ensure_ascii=False)
            if kline:
                json.dump({"symbol": sym, "bars": len(kline), "from": kline[0]["date"], "to": kline[-1]["date"],
                           "data": kline, "ts": now()}, open(f"{d}/kline.json", "w"), ensure_ascii=False)
            if tech:
                json.dump({"symbol": sym, "ts": now(), **tech}, open(f"{d}/technical.json", "w"), ensure_ascii=False)
            if flow:
                json.dump({"symbol": sym, "days": len(flow), "data": flow, "ts": now()},
                          open(f"{d}/moneyflow.json", "w"), ensure_ascii=False)
            if fin:
                json.dump({"symbol": sym, "reports": fin, "ts": now()}, open(f"{d}/finance.json", "w"), ensure_ascii=False)
            json.dump({"symbol": sym, "items": news, "ts": now()}, open(f"{d}/news.json", "w"), ensure_ascii=False)
            json.dump({"symbol": sym, "ts": now(), **senti}, open(f"{d}/sentiment.json", "w"), ensure_ascii=False)
            # holo快照
            json.dump({"symbol": sym, "price": last.get("close"), "bars": len(kline),
                       "pos240": tech.get("pos240_pct") if tech else None,
                       "macd_hist": tech.get("macd", {}).get("hist") if tech else None,
                       "flow_days": len(flow), "reports": len(fin), "news": len(news),
                       "pool_hits": len(senti.get("pool_hits", [])), "ts": now()},
                      open(f"{d}/holo.json", "w"), ensure_ascii=False)
            print(f"[{i+1}/{len(seg)}] {sym}: kline{len(kline)} flow{len(flow)} fin{len(fin)} news{len(news)}")
        except Exception as e:
            print(f"[{i+1}/{len(seg)}] {sym} ERR {str(e)[:60]}")
    con.close()

if __name__ == "__main__":
    main()
