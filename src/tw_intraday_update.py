"""Build a noon screen and a clearly marked temporary candle from TWSE MIS."""

import csv
import json
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from scripts.fetch_tw_stock_data import fetch_all_symbols
from scripts.screen_tw_pullback import CRITERIA, MIN_VOLUME_LOTS, SCREENING, signal
from src.tw_official_data import latest_reports, selected_history


SNAPSHOT_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
SNAPSHOT_HOME = "https://mis.twse.com.tw/stock/index.jsp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; TaiwanStockScreen/1.0)",
    "Referer": SNAPSHOT_HOME,
}
MIN_SNAPSHOT_COVERAGE = 0.8


def _number(value):
    """Parse MIS numeric strings while treating '-' as missing."""
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


def fetch_twse_mis_snapshot(symbols, batch_size=120):
    """Fetch listed and OTC quotes through TWSE's official MIS endpoint."""
    records = []
    session = requests.Session()
    # Establish the same session used by the public MIS web page.  A failure here
    # is harmless because the quote endpoint often works without a cookie.
    try:
        session.get(SNAPSHOT_HOME, headers=HEADERS, timeout=20)
    except requests.RequestException:
        pass
    for offset in range(0, len(symbols), batch_size):
        batch = symbols[offset:offset + batch_size]
        channels = [f"{'tse' if row['market'] == 'listed' else 'otc'}_{row['code']}.tw"
                    for row in batch]
        response = session.get(
            SNAPSHOT_URL,
            params={"ex_ch": "|".join(channels), "json": "1", "delay": "0"},
            headers=HEADERS,
            timeout=45,
        )
        try:
            payload = response.json()
        except (requests.JSONDecodeError, ValueError):
            payload = {}
        if not response.ok:
            raise RuntimeError(f"證交所 MIS 盤中資料 HTTP {response.status_code}：{response.reason}")
        if payload.get("rtcode") != "0000":
            raise RuntimeError(f"證交所 MIS 盤中資料失敗：{payload.get('rtmessage', 'unknown error')}")
        records.extend(payload.get("msgArray", []))

    parsed = []
    for row in records:
        quote_time = pd.to_datetime(f"{row.get('d', '')} {row.get('t', '')}",
                                    format="%Y%m%d %H:%M:%S", errors="coerce")
        trade = row.get("trade") if isinstance(row.get("trade"), dict) else {}
        close = _number(row.get("z"))
        if pd.isna(close):
            close = _number(trade.get("z"))
        item = {
            "code": str(row.get("c", "")),
            "quote_time": quote_time,
            "open": _number(row.get("o")),
            "high": _number(row.get("h")),
            "low": _number(row.get("l")),
            "close": close,
            # MIS v is the cumulative trading volume in lots (張).
            "total_volume": _number(row.get("v")),
        }
        if item["code"] and not any(pd.isna(item[key]) for key in
                                    ("quote_time", "open", "high", "low", "close", "total_volume")):
            parsed.append(item)
    frame = pd.DataFrame(parsed)
    if frame.empty:
        raise RuntimeError("證交所 MIS 盤中資料為空或欄位已變更。")
    return frame.drop_duplicates("code", keep="last")


def _write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class IntradayUpdater:
    def __init__(self, root, activate=lambda _: None, now=None):
        self.root = Path(root)
        self.activate = activate
        self.now = now
        self.state = {"status": "idle"}

    def status(self):
        return dict(self.state)

    def update(self, **values):
        self.state.update(values)

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self.update(status="error", error=str(exc))

    def _run(self):
        now = self.now or datetime.now(ZoneInfo("Asia/Taipei"))
        self.update(status="running", stage="取得證交所／櫃買中心盤中快照", min_volume_lots=MIN_VOLUME_LOTS)
        rows = fetch_all_symbols()
        by_code = {r["code"]: r for r in rows}
        if not rows or not all(any(r["market"] == m for r in rows) for m in ("listed", "otc")):
            raise RuntimeError("上市或上櫃股票清單不完整，請稍後重試。")

        snapshot = fetch_twse_mis_snapshot(rows)
        snapshot = snapshot[snapshot.code.isin(by_code)].copy()
        if snapshot.empty:
            raise RuntimeError("證交所 MIS 快照沒有上市櫃普通股資料。")
        snapshot_coverage = len(snapshot) / len(rows)
        if snapshot_coverage < MIN_SNAPSHOT_COVERAGE:
            raise RuntimeError(
                f"證交所 MIS 有效快照僅 {len(snapshot):,}/{len(rows):,} 檔"
                f"（{snapshot_coverage:.1%}），低於安全門檻；保留上次成功頁面。"
            )
        quote_day = snapshot.quote_time.dt.date.mode().iloc[0]
        snapshot = snapshot[snapshot.quote_time.dt.date == quote_day].copy()
        if quote_day != now.date():
            raise RuntimeError(f"證交所 MIS 快照日期為 {quote_day}，不是今天；保留上次成功頁面。")
        as_of = snapshot.quote_time.max()
        if pd.isna(as_of):
            raise RuntimeError("證交所 MIS 快照缺少有效時間。")

        snapshot["market"] = snapshot.code.map(lambda code: by_code[code]["market"])
        snapshot["name"] = snapshot.code.map(lambda code: by_code[code]["name"])
        # MIS total_volume is quoted in lots; daily history stores shares.
        liquid = snapshot[snapshot.total_volume >= MIN_VOLUME_LOTS].copy()
        red_candidates = liquid[liquid.close > liquid.open].copy()

        self.update(stage="取得前一完整交易日與歷史", total=len(liquid), liquid_universe=len(liquid),
                    red_candidates=len(red_candidates), as_of=as_of.isoformat())
        prior_day, _ = latest_reports(now.date() - timedelta(days=1))
        start = (pd.Timestamp(prior_day).replace(day=1) - pd.DateOffset(months=5)).date()
        history = selected_history(start, prior_day, liquid.to_dict("records")) if len(liquid) else pd.DataFrame()
        history_errors = history.attrs.get("errors", [])

        folder = self.root / "data" / "tw_intraday" / now.strftime("%Y%m%d_%H%M%S_%f")
        folder.mkdir(parents=True)
        matches, waiting_matches, selected, errors = [], [], [], list(history_errors)
        bull_confirmation_matches, consolidation_breakout_matches = [], []
        groups = history.groupby(["code", "market"]) if not history.empty else None
        current_time = int((pd.Timestamp(quote_day) - pd.Timestamp("1970-01-01")).total_seconds())
        self.update(stage=f"執行 {MIN_VOLUME_LOTS:,} 張盤中篩選", done=0)
        for done, item in enumerate(liquid.to_dict("records"), 1):
            self.update(done=done)
            code, market = item["code"], item["market"]
            try:
                closed = groups.get_group((code, market)).drop(columns=["code", "name", "market"])
            except (KeyError, AttributeError):
                if not any(error["code"] == code for error in errors):
                    errors.append({"code": code, "reason": "無法取得足夠的已收盤歷史資料"})
                continue
            closed = closed.dropna().drop_duplicates("time").sort_values("time")
            live = pd.DataFrame([{
                "time": current_time, "open": item["open"], "high": item["high"],
                "low": item["low"], "close": item["close"],
                "tick_volume": item["total_volume"] * 1000,
            }])
            combined = pd.concat([closed, live], ignore_index=True)
            metrics = signal(combined, require_stabilization=False)
            bull = signal(combined, screen="bull_confirmation")
            breakout = signal(combined, screen="consolidation_breakout")
            if not (metrics or bull or breakout):
                continue
            intraday_bar = {
                "date": str(quote_day), "as_of": item["quote_time"].isoformat(),
                "open": float(item["open"]), "high": float(item["high"]),
                "low": float(item["low"]), "close": float(item["close"]),
                "tick_volume": int(item["total_volume"] * 1000), "is_partial": True,
            }
            def public(candidate):
                return {**candidate, "code": code, "name": item["name"], "market": market,
                        "intraday_bar": intraday_bar, "volume_threshold_met": True}
            if metrics is not None:
                if metrics["red_k_confirmed"]:
                    matches.append(public(metrics))
                elif not metrics["is_red_candle"]:
                    waiting_matches.append(public(metrics))
            if bull is not None:
                bull_confirmation_matches.append(public(bull))
            if breakout is not None:
                consolidation_breakout_matches.append(public(breakout))
            if not (bull or breakout or (metrics and (metrics["red_k_confirmed"] or not metrics["is_red_candle"]))):
                continue
            closed.to_parquet(folder / f"{code}_D1.parquet", index=False)
            export = closed.copy()
            export.insert(0, "date", pd.to_datetime(export.pop("time"), unit="s").dt.strftime("%Y-%m-%d"))
            export.rename(columns={"tick_volume": "volume_shares"}).to_csv(
                folder / f"{code}_D1.csv", index=False, encoding="utf-8-sig")
            selected.append({**by_code[code], "last_date": str(prior_day), "volume_lots": f">={MIN_VOLUME_LOTS}"})

        matches.sort(key=lambda r: r["code"])
        waiting_matches.sort(key=lambda r: r["code"])
        bull_confirmation_matches.sort(key=lambda r: r["code"])
        consolidation_breakout_matches.sort(key=lambda r: r["code"])
        _write_csv(folder / "tw_stock_symbols.csv", selected,
                   ["code", "name", "market", "last_date", "volume_lots"])
        _write_csv(folder / "fetch_errors.csv", errors, ["code", "reason"])
        result = {
            "date": str(quote_day), "as_of": as_of.isoformat(), "snapshot_kind": "intraday",
            "is_intraday": True, "screening": SCREENING, "min_volume_lots": MIN_VOLUME_LOTS,
            "universe_size": len(rows), "snapshot_universe": len(snapshot),
            "snapshot_coverage": round(snapshot_coverage, 4),
            "liquid_universe": len(liquid), "red_candidates": len(red_candidates),
            "matches": matches, "waiting_matches": waiting_matches,
            "bull_confirmation_matches": bull_confirmation_matches,
            "consolidation_breakout_matches": consolidation_breakout_matches, "criteria": CRITERIA,
        }
        (folder / "screening_results.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8")
        (folder / "source.json").write_text(json.dumps({
            "source": "TWSE MIS intraday snapshot (temporary OHLC and cumulative volume published)",
            "history_source": "FinMind (listed), TPEx (OTC)", "price_basis": "unadjusted",
            "market_date": str(quote_day), "as_of": as_of.isoformat(),
            "history_end": str(prior_day), "min_volume_lots": MIN_VOLUME_LOTS,
            "universe_size": len(rows), "snapshot_universe": len(snapshot),
            "snapshot_coverage": round(snapshot_coverage, 4),
            "screening": SCREENING,
        }, ensure_ascii=False), encoding="utf-8")
        archive = folder / f"tw_stock_{quote_day}_{MIN_VOLUME_LOTS}lots.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(folder.iterdir()):
                if path.suffix in (".csv", ".parquet", ".json"):
                    bundle.write(path, path.name)
        self.activate(str(folder))
        self.update(status="complete", stage="完成", data_dir=str(folder), archive=str(archive),
                    selected=len(selected), failed=len(errors),
                    source="TWSE MIS intraday snapshot")

