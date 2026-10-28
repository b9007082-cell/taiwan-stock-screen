"""Screen bullish pullbacks with a first stabilization candle, without Yahoo."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.fetch_tw_stock_data import fetch_all_symbols
from src.tw_official_data import latest_reports, selected_history

SCREENING = "bull_pullback_or_ma_v13_institutional_combo"
MIN_VOLUME_LOTS = 1500
MIN_VOLUME_SHARES = MIN_VOLUME_LOTS * 1000
CRITERIA = {
    "structure": "Last 60 valid bars; strict pivots with 2 bars each side; alternating pivots; latest two highs and lows strictly rising; latest pivot low not subsequently breached",
    "trend": "The latest close (current price for intraday) must be strictly above its SMA20, plus ANY of: higher highs and higher lows; SMA5 > SMA10 > SMA20; SMA5 > SMA10 > SMA20 > SMA60. No additional MA slope gate.",
    "pullback": "previous close 3-15% below previous 10-bar high; >=2 declines in previous 5 bars",
    "pullback_volume": "In the previous 5 sessions, average down-session volume must be lower than average up-session volume and the five-session volume slope must be negative",
    "candle": "close > open and previous close; low >= 99% of previous low; close position >=0.4; close > SMA5 and previous high; volume >= 1.5 times previous day OR > prior five-day average; at least one KD or MACD entry signal",
    "waiting": "Meets trend, MA20, pullback, pullback-volume and liquidity rules, and the latest close is not above the latest open",
    "minimum_bars": 65,
    "min_volume_lots": MIN_VOLUME_LOTS,
    "entry_indicators": "KD(5,3,3): K rising OR K > D OR golden cross; MACD(6,13,9): positive histogram growing OR negative histogram shrinking OR negative-to-positive; at least one group must qualify",
    "bull_confirmation": "Two rising confirmed swing lows; red close crosses above latest confirmed swing high from yesterday; SMA5/10/20 each rising; above SMA20; entry volume and KD/MACD gate",
    "consolidation_breakout": "Prior 10 complete bars within 12% range and SMA20 rising; solid red body >= 50% of range; close above prior 10-bar high and SMA20; entry volume and KD/MACD gate",
    "kd_macd_institutional": "KD(5,3,3) golden cross AND MACD(6,13,9) histogram either strictly changes from negative to positive OR a positive histogram grows versus the prior bar; official TWSE/TPEx three-institution net buying > 0 on the same completed day (previous completed day during intraday). This is not broker-level major-player buying.",
}


def swing_pivots(frame):
    df = frame.tail(60).reset_index(drop=True)
    high = df.high.gt(df.high.shift(1)) & df.high.gt(df.high.shift(2)) & df.high.gt(df.high.shift(-1)) & df.high.gt(df.high.shift(-2))
    low = df.low.lt(df.low.shift(1)) & df.low.lt(df.low.shift(2)) & df.low.lt(df.low.shift(-1)) & df.low.lt(df.low.shift(-2))
    pivots = []
    for i in range(2, len(df) - 2):
        # An outside bar cannot determine the intraday ordering of both pivots.
        if bool(high.iloc[i]) == bool(low.iloc[i]):
            continue
        kind = 'high' if high.iloc[i] else 'low'
        point = {'kind': kind, 'price': float(df[kind].iloc[i]), 'time': int(df.time.iloc[i]), 'index': i}
        if pivots and pivots[-1]['kind'] == kind:
            better = point['price'] > pivots[-1]['price'] if kind == 'high' else point['price'] < pivots[-1]['price']
            if better:
                pivots[-1] = point
        else:
            pivots.append(point)
    return pivots


def swing_structure(frame):
    df = frame.tail(60).reset_index(drop=True)
    pivots = swing_pivots(df)
    highs = [p for p in pivots if p['kind'] == 'high'][-2:]
    lows = [p for p in pivots if p['kind'] == 'low'][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return None
    if not (highs[1]['price'] > highs[0]['price'] and lows[1]['price'] > lows[0]['price']):
        return None
    if df.low.iloc[lows[-1]['index'] + 1:].min() < lows[-1]['price']:
        return None
    return {'highs': highs, 'lows': lows}


def bullish_reasons(structure, averages):
    reasons = ['hhhl'] if structure is not None else []
    if averages[5] > averages[10] > averages[20]:
        reasons.append('ma3')
        if averages[20] > averages[60]:
            reasons.append('ma4')
    return reasons


def technical_indicators(frame):
    """Return KD(5,3,3) and MACD(6,13,9) entry signals."""
    df = frame.sort_values("time").drop_duplicates("time", keep="last").copy()
    low5 = df.low.rolling(5).min()
    high5 = df.high.rolling(5).max()
    span5 = high5 - low5
    rsv = ((df.close - low5) / span5 * 100).where(span5 > 0)
    k_values, d_values = [], []
    previous_k = previous_d = 50.0
    for value in rsv:
        if not pd.isna(value):
            previous_k = previous_k * 2 / 3 + float(value) / 3
            previous_d = previous_d * 2 / 3 + previous_k / 3
        k_values.append(previous_k)
        d_values.append(previous_d)

    close = df.close
    dif = close.ewm(span=6, adjust=False).mean() - close.ewm(span=13, adjust=False).mean()
    macd = dif.ewm(span=9, adjust=False).mean()
    histogram = dif - macd
    kd_rising = bool(k_values[-1] > k_values[-2])
    kd_bullish = bool(k_values[-1] > d_values[-1])
    kd_golden_cross = bool(kd_bullish and k_values[-2] <= d_values[-2])
    macd_red_growing = bool(histogram.iloc[-1] > 0 and histogram.iloc[-1] > histogram.iloc[-2])
    macd_green_shrinking = bool(histogram.iloc[-1] < 0 and histogram.iloc[-1] > histogram.iloc[-2])
    macd_green_to_red = bool(histogram.iloc[-2] < 0 and histogram.iloc[-1] > 0)
    return {
        "kd_k": round(k_values[-1], 3),
        "kd_d": round(d_values[-1], 3),
        "kd_rising": kd_rising,
        "kd_bullish": kd_bullish,
        "kd_golden_cross": kd_golden_cross,
        "kd_entry_signal": bool(kd_rising or kd_bullish or kd_golden_cross),
        "dif": round(float(dif.iloc[-1]), 3),
        "macd": round(float(macd.iloc[-1]), 3),
        "histogram": round(float(histogram.iloc[-1]), 3),
        "histogram_rising": bool(histogram.iloc[-1] > histogram.iloc[-2]),
        "macd_red_bar": bool(histogram.iloc[-1] > 0),
        "macd_red_growing": macd_red_growing,
        "macd_green_shrinking": macd_green_shrinking,
        "macd_green_to_red": macd_green_to_red,
        "macd_entry_signal": bool(macd_red_growing or macd_green_shrinking or macd_green_to_red),
    }


def above_ma20(close):
    """Require the latest price to be strictly above its current 20-bar mean."""
    if len(close) < 20:
        return False
    monthly = close.rolling(20).mean()
    return bool(close.iloc[-1] > monthly.iloc[-1])


def classify_rising_stage(close, averages, ma20_series, indicators):
    """Classify a rising stock by extension, MA alignment, and momentum."""
    price = float(close.iloc[-1])
    distance_ma5 = (price / averages[5] - 1) * 100
    distance_ma20 = (price / averages[20] - 1) * 100
    ma20_slope = (float(ma20_series.iloc[-1]) / float(ma20_series.iloc[-6]) - 1) * 100
    if distance_ma5 >= 8 or distance_ma20 >= 15:
        return "末升段", f"距MA5 {distance_ma5:+.1f}%／距MA20 {distance_ma20:+.1f}%，短線乖離偏大"
    if (averages[5] > averages[10] > averages[20] and ma20_slope > 0
            and indicators["macd_red_bar"] and indicators["histogram_rising"]):
        return "主升段", f"三線多排、MA20斜率 {ma20_slope:+.1f}%，MACD紅柱擴大"
    return "初升段", f"距MA20 {distance_ma20:+.1f}%，多頭排列或動能尚未同時完整"


def pullback_volume_contracted(frame, lookback=5):
    """Require pullback down-volume below up-volume with a declining trend."""
    df = frame.reset_index(drop=True)
    if len(df) < lookback + 1:
        return False
    pullback = df.iloc[-lookback - 1:-1]
    previous_close = df.close.shift(1).iloc[-lookback - 1:-1]
    down_mask = pullback.close < previous_close
    up_mask = pullback.close > previous_close
    if not down_mask.any() or not up_mask.any():
        return False
    down_average = float(pullback.loc[down_mask, "tick_volume"].mean())
    up_average = float(pullback.loc[up_mask, "tick_volume"].mean())
    volumes = pullback.tick_volume.reset_index(drop=True)
    positions = pd.Series(range(lookback), dtype="float64")
    denominator = float(((positions - positions.mean()) ** 2).sum())
    slope = float(((positions - positions.mean()) * (volumes - volumes.mean())).sum() / denominator)
    return bool(up_average > 0 and down_average < up_average and slope < 0)


def signal(frame, require_stabilization=True, screen="pullback"):
    df = frame.sort_values("time").drop_duplicates("time", keep="last").dropna().copy()
    df = df[df.tick_volume > 0]
    if len(df) < 65:
        return None
    structure = swing_structure(df)
    close = df.close
    ma = {n: close.rolling(n).mean() for n in (5, 10, 20, 60)}
    reasons = bullish_reasons(structure, {n: ma[n].iloc[-1] for n in ma})
    today, yesterday = df.iloc[-1], df.iloc[-2]
    peak = float(df.high.iloc[-11:-1].max())
    pullback = (1 - yesterday.close / peak) * 100
    declining = int((close.diff().iloc[-6:-1] < 0).sum())
    span = today.high - today.low
    position = (today.close - today.low) / span if span > 0 else 0
    pullback_volume_shrinking = pullback_volume_contracted(df)
    volume_increased = bool(today.tick_volume > yesterday.tick_volume)
    prior_volume5 = float(df.tick_volume.iloc[-6:-1].mean())
    entry_volume_met = bool(today.tick_volume >= yesterday.tick_volume * 1.5
                            or today.tick_volume > prior_volume5)
    above_monthly = above_ma20(close)
    if screen not in ("pullback", "bull_confirmation", "consolidation_breakout", "kd_macd_combo"):
        raise ValueError(f"Unknown screen: {screen}")
    indicators = technical_indicators(df)
    averages = {n: float(ma[n].iloc[-1]) for n in ma}
    above_ma5 = bool(today.close > averages[5])
    reclaimed_previous_high = bool(today.close > yesterday.high)
    stabilization = bool(today.close > today.open and today.close > yesterday.close
                         and today.low >= yesterday.low * 0.99 and position >= 0.4
                         and above_ma5 and reclaimed_previous_high and entry_volume_met
                         and (indicators["kd_entry_signal"] or indicators["macd_entry_signal"]))
    momentum_and_volume = entry_volume_met and (indicators["kd_entry_signal"] or indicators["macd_entry_signal"])
    pullback_ready = bool(reasons and above_monthly and pullback_volume_shrinking
                          and 3 <= pullback <= 15 and declining >= 2)
    previous = df.iloc[:-1]
    pivots = swing_pivots(previous)
    swing_highs = [point for point in pivots if point['kind'] == 'high']
    swing_lows = [point for point in pivots if point['kind'] == 'low']
    prior_swing_high = swing_highs[-1]['price'] if swing_highs else None
    higher_lows = bool(len(swing_lows) >= 2 and swing_lows[-1]['price'] > swing_lows[-2]['price']
                       and float(today.low) >= swing_lows[-1]['price']
                       and float(previous.tail(60).reset_index(drop=True).low.iloc[swing_lows[-1]['index'] + 1:].min()) >= swing_lows[-1]['price'])
    ma_rising = all(float(ma[n].iloc[-1]) > float(ma[n].iloc[-2]) for n in (5, 10, 20))
    bull_confirmed = bool(higher_lows and prior_swing_high is not None
                          and yesterday.close <= prior_swing_high < today.close
                          and today.close > today.open and above_monthly and ma_rising and momentum_and_volume)
    box = previous.tail(10)
    neckline = float(box.high.max())
    box_low = float(box.low.min())
    box_width = (neckline / box_low - 1) if box_low > 0 else float('inf')
    consolidation = bool(box_width <= 0.12 and float(ma[20].iloc[-11]) > float(ma[20].iloc[-21]))
    solid_red = bool(span > 0 and today.close > today.open and (today.close - today.open) / span >= 0.5)
    breakout = bool(consolidation and solid_red and today.close > neckline and above_monthly
                    and momentum_and_volume)
    kd_macd_combo = bool(indicators["kd_golden_cross"] and
                         (indicators["macd_green_to_red"] or indicators["macd_red_growing"]))
    if screen == "pullback" and (not pullback_ready or (require_stabilization and not stabilization)):
        return None
    if screen == "bull_confirmation" and not bull_confirmed:
        return None
    if screen == "consolidation_breakout" and not breakout:
        return None
    if screen == "kd_macd_combo" and not kd_macd_combo:
        return None
    if screen == "bull_confirmation":
        reasons = list(dict.fromkeys([*reasons, 'higher_lows']))
    if screen == "consolidation_breakout":
        reasons = list(dict.fromkeys([*reasons, 'consolidation']))
    rising_stage, rising_stage_reason = classify_rising_stage(close, averages, ma[20], indicators)
    volume5 = df.tick_volume.tail(5).mean() / 1000
    volume10 = df.tick_volume.tail(10).mean() / 1000
    return {
        "structure": structure,
        "bullish_reasons": reasons,
        "close": float(today.close), "open": float(today.open), "high": float(today.high),
        "low": float(today.low), "previous_close": float(yesterday.close),
        "previous_high": float(yesterday.high), "previous_low": float(yesterday.low),
        "volume_lots": float(today.tick_volume / 1000),
        "previous_volume_lots": float(yesterday.tick_volume / 1000),
        "volume_increased": volume_increased, "pullback_pct": round(pullback, 2),
        "entry_volume_met": entry_volume_met, "prior_volume5_lots": round(prior_volume5 / 1000, 2),
        "is_red_candle": bool(today.close > today.open),
        "red_k_confirmed": bool(stabilization),
        "pullback_volume_contracted": pullback_volume_shrinking,
        "prior_declining_days": declining, "close_position": round(position, 3),
        "ma": {str(n): round(float(ma[n].iloc[-1]), 3) for n in ma},
        "above_ma20": above_monthly,
        "above_ma5": above_ma5,
        "rising_stage": rising_stage, "rising_stage_reason": rising_stage_reason,
        **indicators,
        "volume5_lots": round(float(volume5), 2), "volume10_lots": round(float(volume10), 2),
        "prior_peak": peak, "pullback_low": float(df.low.tail(6).min()),
        "reclaimed_previous_high": reclaimed_previous_high,
        "bull_confirmation": bull_confirmed, "consolidation_breakout": breakout,
        "kd_macd_combo": kd_macd_combo,
        "prior_swing_high": prior_swing_high, "higher_lows": higher_lows,
        "ma5_10_20_rising": ma_rising, "neckline": neckline,
        "consolidation_width_pct": round(box_width * 100, 2), "solid_red": solid_red,
        "data_bars": len(df),
    }


def write_report(result, path):
    lines = [f"# 多頭回檔紅 K 篩選：{result['date']}", "",
             f"上市櫃普通股；單日成交量至少 {result.get('min_volume_lots', 1500):,} 張，共 {result['liquid_universe']} 檔，其中紅 K {result['red_candidates']} 檔，符合 {len(result['matches'])} 檔。", "",
             "## 篩選條件", "",
             "- 最新收盤價必須嚴格高於當日月線 MA20（盤中採當下最新價）；等於或低於月線均不入選。並且多頭任一成立：頭頭高底底高、三線 MA5 > MA10 > MA20、四線 MA5 > MA10 > MA20 > MA60。",
             "- 結構分支：最近 60 根日 K，以左右各 2 根確認波段；最近兩個高點與低點均嚴格提高，最新波段低點未再跌破。不另要求均線斜率。",
             "- 回檔：前一日收盤相對此前 10 日最高價回落 3% 至 15%，此前 5 日至少 2 日收盤下跌。",
             "- 回檔量縮：止跌紅 K 前 5 日中的收跌日平均量必須低於收漲日平均量，且 5 日成交量整體斜率向下。",
             "- 止跌紅 K：收盤 > 開盤、昨收、當日 MA5 與昨高，且高於當日 MA20；最低價不低於昨低的 99%，收盤位置至少為當日振幅的 40%。",
             "- 今日成交量 ≥ 昨量 1.5 倍，或 > 前五個完整交易日均量；KD(5,3,3) 的 K 上升／K>D／黃金交叉，或 MACD(6,13,9) 的紅柱增長／綠柱縮短／綠轉紅，至少符合其中一項。",
             "- 至少 65 根有效日 K、當日量至少 1,500 張；多頭分支擇一，照片中的價格、量能及動能條件同時滿足。", "",
             "## 候選名單", "", "| 股票 | 收盤 | 成交量（張） | 紅K低點 | 已收復昨高 |",
             "|---|---:|---:|---:|---|"]
    for r in result["matches"]:
        lines.append(f"| {r['code']} {r['name']} | {r['close']:g} | {r['volume_lots']:,.3f} | {r['low']:g} | {'是' if r['reclaimed_previous_high'] else '否'} |")
    for r in result["matches"]:
        distance = (r["close"] / r["ma"]["5"] - 1) * 100
        lines += ["", f"## {r['code']} {r['name']} 波段技術分析", "", "### 基本資訊", "",
                  f"資料日 {result['date']}；日 K；收盤 {r['close']:g}；有效歷史 {r['data_bars']} 根。", "",
                  "### 技術指標", "", "| 指標 | 數值 |", "|---|---:|"]
        lines += [f"| MA{n} | {r['ma'][n]:g} |" for n in ("5", "10", "20", "60")]
        lines += [f"| KD(5,3,3) K | {r['kd_k']:g} |", f"| KD(5,3,3) D | {r['kd_d']:g} |",
                  f"| KD 黃金交叉 | {'是' if r['kd_golden_cross'] else '否'} |",
                  f"| DIF（MACD 6,13,9） | {r['dif']:g} |", f"| MACD Signal | {r['macd']:g} |",
                  f"| 柱狀值（DIF-Signal） | {r['histogram']:g} |",
                  f"| MACD 紅柱 | {'是' if r['macd_red_bar'] else '否'} |",
                  f"| 5 日均量（張） | {r['volume5_lots']:,.2f} |", f"| 10 日均量（張） | {r['volume10_lots']:,.2f} |", "",
                  "### 型態與多空判斷", "",
                  f"符合中期多頭與紅 K 回升條件；截至前一日回檔 {r['pullback_pct']:g}%。MACD 柱狀值{'上升' if r['histogram_rising'] else '下降'}，尚不代表反轉確認。未另外判定三角形或頭肩等型態。", "",
                  "### 關鍵價位", "",
                  f"- 紅 K 高點：{r['high']:g}；後續觀察能否續強。",
                  f"- 前日高點：{r['previous_high']:g}；{'已收復' if r['reclaimed_previous_high'] else '尚未收復'}。",
                  f"- 紅 K 低點：{r['low']:g}；後續跌破會削弱這次止跌訊號。",
                  f"- 近 6 日低點：{r['pullback_low']:g}；此前 10 日高點：{r['prior_peak']:g}。", "",
                  "### 操作觀察與風險", "",
                  f"距 MA5 {distance:.2f}%；{'超過 8%，短線偏熱，不宜因收紅便直接追價。' if distance > 8 else '仍需觀察後续交易日是否守住紅 K 低點、站穩紅 K 高點。'}",
                  "單根紅 K 不是確認止跌，也不是買進建議；應配合後續量價、個別除權息事件與個人風險承受度。"]
    lines += ["", "## 資料與限制", "",
              "當日行情與成交量：證交所／櫃買中心；上市歷史：FinMind；上櫃歷史：櫃買月報。",
              "使用未還原價格，除權息或減資等事件可能影響均線與回檔判斷；上櫃歷史量為月報整張數換算，當日篩選使用每日報表的精確股數。",
              "技術條件僅供觀察，不代表未來上漲保證。"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    cutoff = now.date() - timedelta(days=int(now.hour < 16))
    day, latest = latest_reports(cutoff)
    universe = {(r["code"], r["market"]): r for r in fetch_all_symbols()}
    latest = latest[[key in universe for key in zip(latest.code, latest.market)]]
    liquid = latest[latest.tick_volume >= MIN_VOLUME_SHARES]
    candidates = liquid[liquid.close > liquid.open]
    print(f"Data date {day}; liquid {len(liquid)}; red candles {len(candidates)}", flush=True)
    start = (pd.Timestamp(day).replace(day=1) - pd.DateOffset(months=5)).date()
    def progress(done, total):
        if done % 25 == 0 or done == total:
            print(f"History {done}/{total}", flush=True)
    history = selected_history(start, day, candidates.to_dict("records"), progress)
    history = pd.concat([history, candidates], ignore_index=True).drop_duplicates(["code", "market", "time"], keep="last")
    end = int((pd.Timestamp(day) - pd.Timestamp("1970-01-01")).total_seconds())
    history = history[history.time <= end]
    found, insufficient = [], []
    for (code, market), frame in history.groupby(["code", "market"]):
        if len(frame.dropna()) < 65:
            insufficient.append(code)
        result = signal(frame)
        if result:
            found.append({**universe[(code, market)], **result})
    found.sort(key=lambda r: (not r["reclaimed_previous_high"], r["code"]))
    result = {"date": str(day), "source": "TWSE/TPEx daily; FinMind/TPEx history; unadjusted",
              "screening": SCREENING, "criteria": CRITERIA,
              "min_volume_lots": MIN_VOLUME_LOTS, "liquid_universe": len(liquid), "red_candidates": len(candidates),
              "insufficient_history": insufficient, "matches": found}
    path = ROOT / "output" / f"tw_bull_pullback_{day}_{MIN_VOLUME_LOTS}lots_v4.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(result, path.with_suffix(".md"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
