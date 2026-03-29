# Backtest Logic

本文件記錄 `data/taifex_raw` 上的回測邏輯、成交假設、成本模型與後續優化方向，作為策略追蹤基準。

注意:

- 本 repo 的預設模擬與回測商品是微型臺指期貨 `TMF`
- 小型臺指期貨 `MTX` / `MXFR1` 僅保留在部分通用模組作為可擴充商品，不是本專案的預設策略標的

## 1. 資料來源

- 原始資料: `data/taifex_raw/Daily_*.rpt`
- 商品: `TMF`
- 重採樣週期:
  - `5min`
  - `15min`
  - `1h`
- 目前回測入口:
  - `python3 scripts/backtest_performance.py`

## 2. 指標計算

由 `src/squeeze_futures/engine/indicators.py` 計算:

- `sqz_on`: Squeeze 是否仍在壓縮
- `momentum`, `mom_state`: 動能方向與強弱
- `vwap`, `price_vs_vwap`: 當日 VWAP 與偏離程度
- `ema_fast`, `ema_slow`, `ema_filter`, `ema_macro`
- `is_new_high`, `is_new_low`
- `in_bull_pb_zone`, `in_bear_pb_zone`
- `opening_bullish`, `opening_bearish`

多週期分數由 `calculate_mtf_alignment()` 計算，目前權重:

- `1h`: `0.2`
- `15m`: `0.4`
- `5m`: `0.4`

## 3. 進場邏輯

目前回測同時支援兩類進場:

### A. Squeeze Breakout

做多條件:

- `sqz_on == False`
- `score >= entry_score`
- `price > vwap`
- `mom_state == 3`

做空條件:

- `sqz_on == False`
- `score <= -entry_score`
- `price < vwap`
- `mom_state == 0`

### B. Pullback Entry

做多條件:

- 最近 12 根內出現 `is_new_high`
- `in_bull_pb_zone == True`
- `price > Open`
- `bullish_align == True`

做空條件:

- 最近 12 根內出現 `is_new_low`
- `in_bear_pb_zone == True`
- `price < Open`
- `bearish_align == True`

## 4. 部位與風控

目前配置來自 `config/trade_config.yaml`:

- 每次進場口數: `2`
- 停損: `30 pts`
- 保本觸發: `30 pts`
- 分批停利:
  - TP1: `+40 pts`
  - 平倉 `1 lot`
  - 剩餘部位停損移到成本價

### 出場條件

- 觸發硬停損
- 跌破/站回 VWAP 且與 opening regime 不一致
- 動能轉弱:
  - 多單: `mom_state < 2 or score < 20`
  - 空單: `mom_state > 1 or score > -20`

## 5. 成交模型

由 `src/squeeze_futures/engine/execution.py` 控制。

### `market`

- 以參考價成交
- 額外加入 `market_slippage_pts`

### `limit`

- 買單: `reference_price - limit_offset_pts`
- 賣單: `reference_price + limit_offset_pts`
- 價格需在該 bar 的 `Low ~ High` 之間才算成交

### `range_market`

- 本質上是帶保護範圍的市價
- 若滑價超過 `range_protection_pts`，則視為拒絕成交
- 用來模擬:
  - 收盤前先給價格改善機會
  - 但不接受過差追價

## 6. 成本模型

由 `src/squeeze_futures/engine/simulator.py` 計算。

目前分成:

- `broker_fee_per_side`
- `exchange_fee_per_side`
- `tax_rate`

每筆已實現損益會拆成:

- `gross_pnl_cash`
- `broker_fee`
- `exchange_fee`
- `tax_cost`
- `total_cost`
- `pnl_cash`

### 預設值

目前 `config/trade_config.yaml` 預設:

- `order_type: market`
- `market_slippage_pts: 1.0`
- `broker_fee_per_side: 20`
- `exchange_fee_per_side: 0`
- `tax_rate: 0.00002`

注意:

- `tax_rate` 目前是股價指數期貨回測假設值
- 若要貼近實際券商帳單，應依你的成交對帳單更新 `broker_fee_per_side`
- 若券商手續費已內含交易所相關費用，可維持 `exchange_fee_per_side = 0`

## 7. 頻繁交易的成本影響

這個策略屬於高交易頻率模型，成本侵蝕明顯。

在目前成本設定下，最近一次回測顯示:

- Net Profit 由未完整計成本版本明顯下降
- 成本結構以 `broker_fee` 為主
- `tax_cost` 會隨成交次數與價格同步累積

因此之後的優化不應只看:

- `Net Profit`

也必須同步看:

- `Total Trades`
- `Average Trade`
- `Total Cost`
- `Profit Factor`
- `Max Drawdown`

## 8. 收盤與隔日改善假設

這是下一階段要驗證的重點。

### A. 收盤前當沖單

問題:

- 若大部分當沖單必須在收盤前成交，純市價會增加滑價與成本

可測方案:

1. `market`
2. `limit -> market fallback`
3. `limit -> range_market -> market`

目標:

- 降低尾盤追價成本
- 不大幅提升未成交風險

### B. 隔日開盤/夜盤開盤被迫平倉

問題:

- 若尾盤未平，是否有機會利用下一交易時段開盤流動性改善出場價格

可測方案:

1. 尾盤強制平倉
2. 留到下一盤第一根 K 平倉
3. 留到下一盤前 3 根 K，若延續有利方向則擇價出場

核心風險:

- 這不是無風險套利，而是承擔 gap risk 換取可能的價格改善

## 9. 實際執行策略

下單定價策略必須視為策略本體的一部分，不能和訊號邏輯分開。

### A. 進場定價原則

- `Squeeze Breakout`:
  - 優先使用 `range_market`
  - 原因: 突破型訊號對成交時效敏感，但仍要限制失控滑價
- `Pullback Entry`:
  - 優先使用 `limit`
  - 原因: 拉回型訊號本質上允許等價，若用市價容易把風報比吃掉

### B. 出場定價原則

- `硬停損`:
  - 使用 `market`
  - 原因: 停損重點是離場，不是價格改善
- `TP1 分批停利`:
  - 可先用 `limit`
  - 若一定時間內未成交，再轉 `range_market`
- `一般訊號出場`:
  - 預設 `range_market`
  - 若流動性正常，可兼顧成交率與價格品質
- `收盤前強制平倉`:
  - 採用三級流程:
    1. `limit`
    2. `range_market`
    3. `market`

### C. 收盤與跨盤原則

- 若策略要求「大部分當沖單在收盤前完成」:
  - 必須設明確的尾盤 fallback 流程
- 若允許隔夜/隔盤:
  - 必須將其視為獨立持倉邏輯
  - 不能把「沒平掉」和「主動留倉」混為一談

### D. 建議的基準執行方案

這是目前最適合先實作與回測的版本:

- Breakout 進場: `range_market`
- Pullback 進場: `limit`
- 停損: `market`
- TP1: `limit -> range_market`
- 收盤前平倉: `limit -> range_market -> market`
- 若允許隔盤: 下一盤開盤前 1 根 K 先 `range_market`，失敗再 `market`

## 10. 參數表格

### A. 訊號與風控參數

| 參數 | 目前值 | 用途 | 備註 |
|:---|---:|:---|:---|
| `strategy.length` | 20 | Squeeze 計算長度 | 影響訊號靈敏度 |
| `strategy.entry_score` | 70 | 多週期共振門檻 | 越高越嚴格 |
| `strategy.regime_filter` | `mid` | 環境過濾 | 目前偏 15m EMA 60 |
| `trade_mgmt.lots_per_trade` | 2 | 每次進場口數 | 配合分批停利 |
| `risk_mgmt.stop_loss_pts` | 30 | 初始停損 | 目前 2 口同步 |
| `risk_mgmt.break_even_pts` | 30 | 保本觸發 | 達標後上移停損 |
| `strategy.partial_exit.tp1_pts` | 40 | 第一階段停利 | 平 1 口 |
| `strategy.partial_exit.tp1_lots` | 1 | TP1 平倉口數 | Runner 留倉 |

### B. 執行與成本參數

| 參數 | 目前值 | 用途 | 備註 |
|:---|---:|:---|:---|
| `execution.order_type` | `market` | 回測預設下單類型 | 建議後續拆成依情境使用 |
| `execution.tick_size` | 1.0 | 最小跳動單位 | 用於成交價取整 |
| `execution.market_slippage_pts` | 1.0 | 市價滑價 | 高頻時影響明顯 |
| `execution.limit_offset_pts` | 2.0 | 限價偏移點數 | 適合 pullback 類型 |
| `execution.range_protection_pts` | 3.0 | 範圍市價容忍區間 | 超出則拒絕成交 |
| `execution.broker_fee_per_side` | 20.0 | 券商手續費 | 依你的實際帳單調整 |
| `execution.exchange_fee_per_side` | 0.0 | 交易所相關費用 | 若已含在券商手續費可為 0 |
| `execution.tax_rate` | 0.00002 | 期交稅率 | 股價指數期貨回測假設 |

### C. 建議的實際執行定價表

| 情境 | 建議下單方式 | 目的 | 失敗 fallback |
|:---|:---|:---|:---|
| Breakout 進場 | `range_market` | 兼顧成交與控滑價 | `market` |
| Pullback 進場 | `limit` | 提升風報比 | `range_market` |
| 硬停損 | `market` | 優先離場 | 無 |
| TP1 | `limit` | 改善平均出場價 | `range_market` |
| 一般訊號出場 | `range_market` | 降低追價 | `market` |
| 收盤前平倉 | `limit` | 先嘗試價格改善 | `range_market -> market` |
| 隔日/夜盤開盤平倉 | `range_market` | 觀察開盤流動性 | `market` |

## 11. 建議的下一步實驗矩陣

建議固定同一批 `data/taifex_raw`，跑以下對照:

1. `market` 基準組
2. `limit` 進場 + `market` 出場
3. `market` 進場 + 收盤前 `limit -> range_market -> market`
4. 收盤強平
5. 收盤不平，下一盤開盤平
6. 收盤不平，下一盤前 3 根 K 動態平

評估欄位:

- `Net Profit`
- `Profit Factor`
- `Max Drawdown`
- `Total Cost`
- `Trades`
- `Average Trade`
- `Unfilled rate` 或 `forced market fallback rate`

## 12. 追蹤原則

後續每次策略改善，至少記錄:

- 調整目的
- 參數變更
- 成交模型變更
- 成本模型變更
- 回測期間
- 績效變化
- 是否只是用更多風險換更多報酬
