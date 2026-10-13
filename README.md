# stocks-holo — A股每股全息数据库

每股一个文件夹（`sh600000/`），内含该股九面数据 JSON，用于构建庞大股票数据库。

## 文件夹结构（每股）

```
sh600000/
  meta.json        # 代码/名称/行业/上市日期/更新时间/stale标记/provenance
  kline.json       # 日K全史: date,o,h,l,c,volume,turnover(换手率),amount
  technical.json   # 技术面: MACD/KDJ/RSI/BOLL/MA5-250/量比/240日位 (最新+近30日序列)
  moneyflow.json   # 资金面: 主力净流入/大中小单 (新浪MoneyFlow 近100日)
  finance.json     # 基本面: 营收/净利/ROE/EPS/负债率 (东财datacenter)
  news.json        # 消息面: 个股新闻/公告 (东财+新浪, 近30条, 带ts)
  sentiment.json   # 情绪面: 涨停池记录/强势池/龙虎榜/千股千评 (命中时)
  holo.json        # 全息快照: 九面一页汇总(供快速扫描)
```

## 多AI协同规则（必读）

1. **分段认领，绝不重复**：每个 AI 在 `REGISTRY.json` 登记自己负责的股票段。
   - 认领格式：`{"agent": "名字", "range": ["sh600000", "sh603999"], "ts": "..."}`
   - 写入前先拉线上 REGISTRY.json 合并，**只加自己的段，不改别人段**
2. **已存在的股票文件夹不覆盖**：更新前检查远端，只补增量字段（merge语义）
3. **每条数据带 provenance**（source/ts）和 **stale 标记**（age_hours）
4. 本库只存数据，不做算法/引擎（那些在 stocks-algo / engine-core）

## 分工现状

| Agent | 段位 | 状态 |
|---|---|---|
| (登记中) | | |

不构成投资建议。
