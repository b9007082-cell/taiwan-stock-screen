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

SCREENING = "bull_pullback_hhhl_v3"
CRITERIA = {
    "structure": "Last 60 valid bars; strict pivots with 2 bars each side; alternating pivots; latest two highs and lows strictly rising; latest pivot low not subsequently breached",
    "trend": "close > SMA20 > SMA60; SMA20 rising over 5 bars; SMA60 >= 99.5% of 5 bars ago",
    "pullback": "previous close 3-15% below previous 10-bar high; >=2 declines in previous 5 bars",
    "candle": "close > open and previous close; low >= 99% of previous low; close position >=0.4",
    "minimum_bars": 65,
    "min_volume_lots": 1300,
}


def swing_structure(frame):
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
    highs = [p for p in pivots if p['kind'] == 'high'][-2:]
    lows = [p for p in pivots if p['kind'] == 'low'][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return None
    if not (highs[1]['price'] > highs[0]['price'] and lows[1]['price'] > lows[0]['price']):
        return None
    if df.low.iloc[lows[-1]['index'] + 1:].min() < lows[-1]['price']:
        return None
    return {'highs': highs, 'lows': lows}


def signal(frame):
    df = frame.sort_values("time").drop_duplicates("time", keep="last").dropna().copy()
    df = df[df.tick_volume > 0]
    if len(df) < 65:
        return None
    structure = swing_structure(df)
    if structure is None:
        return None
    close = df.close
    ma = {n: close.rolling(n).mean() for n in (5, 10, 20, 60)}
    today, yesterday = df.iloc[-1], df.iloc[-2]
    peak = float(df.high.iloc[-11:-1].max())
    pullback = (1 - yesterday.close / peak) * 100
    declining = int((close.diff().iloc[-6:-1] < 0).sum())
    bullish = (today.close > ma[20].iloc[-1] > ma[60].iloc[-1]
               and ma[20].iloc[-1] > ma[20].iloc[-6]
               and ma[60].iloc[-1] >= ma[60].iloc[-6] * 0.995)
    span = today.high - today.low
    position = (today.close - today.low) / span if span > 0 else 0
    stabilization = (today.close > today.open and today.close > yesterday.close
                     and today.low >= yesterday.low * 0.99 and position >= 0.4)
    if not (bullish and 3 <= pullback <= 15 and declining >= 2 and stabilization):
        return None
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd = dif.ewm(span=9, adjust=False).mean()
    hist = dif - macd
    volume5 = df.tick_volume.tail(5).mean() / 1000
    volume10 = df.tick_volume.tail(10).mean() / 1000
    return {
        "structure": structure,
        "close": float(today.close), "open": float(today.open), "high": float(today.high),
        "low": float(today.low), "previous_close": float(yesterday.close),
        "previous_high": float(yesterday.high), "previous_low": float(yesterday.low),
        "volume_lots": float(today.tick_volume / 1000), "pullback_pct": round(pullback, 2),
        "prior_declining_days": declining, "close_position": round(position, 3),
        "ma": {str(n): round(float(ma[n].iloc[-1]), 3) for n in ma},
        "dif": round(float(dif.iloc[-1]), 3), "macd": round(float(macd.iloc[-1]), 3),
        "histogram": round(float(hist.iloc[-1]), 3),
        "histogram_rising": bool(hist.iloc[-1] > hist.iloc[-2]),
        "volume5_lots": round(float(volume5), 2), "volume10_lots": round(float(volume10), 2),
        "prior_peak": peak, "pullback_low": float(df.low.tail(6).min()),
        "reclaimed_previous_high": bool(today.close > yesterday.high),
        "data_bars": len(df),
    }


def write_report(result, path):
    lines = [f"# 多頭回檔紅 K 篩選：{result['date']}", "",
             f"上市櫃普通股；單日成交量至少 {result.get('min_volume_lots', 1500):,} 張，共 {result['liquid_universe']} 檔，其中紅 K {result['red_candidates']} 檔，符合 {len(result['matches'])} 檔。", "",
             "## 篩選條件", "",
             "- 價格結構：最近 60 根日 K，以左右各 2 根確認波段；最近兩個高點與低點均嚴格提高，最新波段低點未再跌破。",
             "- 中期多頭：收盤 > MA20 > MA60，MA20 高於 5 個交易日前，MA60 五日降幅不超過 0.5%。",
             "- 回檔：前一日收盤相對此前 10 日最高價回落 3% 至 15%，此前 5 日至少 2 日收盤下跌。",
             "- 紅 K 回升觀察：收盤 > 開盤及前日收盤，最低價不低於昨低的 99%，收盤位置至少為當日振幅的 40%。",
             "- 至少 65 根有效日 K；不是要求短期 5 > 10 > 20 完整多頭排列。", "",
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
        lines += [f"| DIF | {r['dif']:g} |", f"| MACD Signal | {r['macd']:g} |",
                  f"| 柱狀值（DIF-Signal） | {r['histogram']:g} |",
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
    liquid = latest[latest.tick_volume >= 1300000]
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
              "min_volume_lots": 1300, "liquid_universe": len(liquid), "red_candidates": len(candidates),
              "insufficient_history": insufficient, "matches": found}
    path = ROOT / "output" / f"tw_bull_pullback_{day}_1300lots_v3.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(result, path.with_suffix(".md"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
