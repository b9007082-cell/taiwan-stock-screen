"""Build a licence-safe noon screen from FinMind's real-time snapshot.

The public artifact contains only screening decisions and prior completed daily
bars.  It deliberately excludes the real-time quote fields because FinMind's
terms do not permit directly presenting those fields on a public web page.
"""

import csv
import json
import os
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from scripts.fetch_tw_stock_data import fetch_all_symbols
from scripts.screen_tw_pullback import CRITERIA, SCREENING, signal
from src.tw_official_data import latest_reports, selected_history


SNAPSHOT_URL = "https://api.finmindtrade.com/api/v4/taiwan_stock_tick_snapshot"
REQUIRED = {"stock_id", "date", "open", "high", "low", "close", "total_volume"}


def fetch_finmind_snapshot(token):
    if not token:
        raise RuntimeError("缺少 FINMIND_TOKEN；請在 GitHub Actions Secrets 設定。")
    response = requests.get(
        SNAPSHOT_URL,
        headers={"Authorization": f"Bearer {token}"},
        params={"data_id": ""},
        timeout=45,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") not in (None, 200):
        raise RuntimeError(f"FinMind 即時資料失敗：{payload.get('msg', 'unknown error')}")
    frame = pd.DataFrame(payload.get("data", []))
    if frame.empty or not REQUIRED.issubset(frame.columns):
        raise RuntimeError("FinMind 即時資料為空或欄位已變更。")
    frame = frame.rename(columns={"stock_id": "code"})
    for column in ("open", "high", "low", "close", "total_volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["quote_time"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["quote_time", "open", "high", "low", "close", "total_volume"])
    frame["code"] = frame["code"].astype(str)
    return frame


def _write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class IntradayUpdater:
    def __init__(self, root, activate=lambda _: None, token=None, now=None):
        self.root = Path(root)
        self.activate = activate
        self.token = token if token is not None else os.environ.get("FINMIND_TOKEN")
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
        self.update(status="running", stage="取得 FinMind 盤中快照", min_volume_lots=1300)
        rows = fetch_all_symbols()
        universe = {(r["code"], r["market"]): r for r in rows}
        by_code = {r["code"]: r for r in rows}
        if not rows or not all(any(r["market"] == m for r in rows) for m in ("listed", "otc")):
            raise RuntimeError("上市或上櫃股票清單不完整，請稍後重試。")

        snapshot = fetch_finmind_snapshot(self.token)
        snapshot = snapshot[snapshot.code.isin(by_code)].copy()
        if snapshot.empty:
            raise RuntimeError("FinMind 快照沒有上市櫃普通股資料。")
        quote_day = snapshot.quote_time.dt.date.mode().iloc[0]
        snapshot = snapshot[snapshot.quote_time.dt.date == quote_day].copy()
        if quote_day != now.date():
            raise RuntimeError(f"FinMind 快照日期為 {quote_day}，不是今天；保留上次成功頁面。")
        as_of = snapshot.quote_time.max()
        if pd.isna(as_of):
            raise RuntimeError("FinMind 快照缺少有效時間。")

        snapshot["market"] = snapshot.code.map(lambda code: by_code[code]["market"])
        snapshot["name"] = snapshot.code.map(lambda code: by_code[code]["name"])
        # FinMind total_volume is quoted in lots; daily history stores shares.
        liquid = snapshot[snapshot.total_volume >= 1300].copy()
        eligible = liquid[liquid.close > liquid.open].copy()

        self.update(stage="取得前一完整交易日與歷史", total=len(eligible), liquid_universe=len(liquid),
                    red_candidates=len(eligible), as_of=as_of.isoformat())
        prior_day, _ = latest_reports(now.date() - timedelta(days=1))
        start = (pd.Timestamp(prior_day).replace(day=1) - pd.DateOffset(months=5)).date()
        history = selected_history(start, prior_day, eligible.to_dict("records")) if len(eligible) else pd.DataFrame()

        folder = self.root / "data" / "tw_intraday" / now.strftime("%Y%m%d_%H%M%S_%f")
        folder.mkdir(parents=True)
        matches, selected, errors = [], [], []
        groups = history.groupby(["code", "market"]) if not history.empty else None
        current_time = int((pd.Timestamp(quote_day) - pd.Timestamp("1970-01-01")).total_seconds())
        self.update(stage="執行 1,300 張盤中篩選", done=0)
        for done, item in enumerate(eligible.to_dict("records"), 1):
            self.update(done=done)
            code, market = item["code"], item["market"]
            try:
                closed = groups.get_group((code, market)).drop(columns=["code", "name", "market"])
            except (KeyError, AttributeError):
                errors.append({"code": code, "reason": "無法取得足夠的已收盤歷史資料"})
                continue
            closed = closed.dropna().drop_duplicates("time").sort_values("time")
            live = pd.DataFrame([{
                "time": current_time, "open": item["open"], "high": item["high"],
                "low": item["low"], "close": item["close"],
                "tick_volume": item["total_volume"] * 1000,
            }])
            metrics = signal(pd.concat([closed, live], ignore_index=True))
            if metrics is None:
                continue
            # Publish derived decisions only. Exact real-time price/OHLCV stays out of the artifact.
            public = {
                "code": code, "name": item["name"], "market": market,
                "bullish_reasons": metrics["bullish_reasons"],
                "structure": metrics["structure"],
                "pullback_pct": metrics["pullback_pct"],
                "prior_declining_days": metrics["prior_declining_days"],
                "reclaimed_previous_high": metrics["reclaimed_previous_high"],
                "data_bars": metrics["data_bars"],
                "volume_threshold_met": True,
            }
            matches.append(public)
            closed.to_parquet(folder / f"{code}_D1.parquet", index=False)
            export = closed.copy()
            export.insert(0, "date", pd.to_datetime(export.pop("time"), unit="s").dt.strftime("%Y-%m-%d"))
            export.rename(columns={"tick_volume": "volume_shares"}).to_csv(
                folder / f"{code}_D1.csv", index=False, encoding="utf-8-sig")
            selected.append({**by_code[code], "last_date": str(prior_day), "volume_lots": ">=1300"})

        matches.sort(key=lambda r: r["code"])
        _write_csv(folder / "tw_stock_symbols.csv", selected,
                   ["code", "name", "market", "last_date", "volume_lots"])
        _write_csv(folder / "fetch_errors.csv", errors, ["code", "reason"])
        result = {
            "date": str(quote_day), "as_of": as_of.isoformat(), "snapshot_kind": "intraday",
            "is_intraday": True, "screening": SCREENING, "min_volume_lots": 1300,
            "liquid_universe": len(liquid), "red_candidates": len(eligible),
            "matches": matches, "criteria": CRITERIA,
        }
        (folder / "screening_results.json").write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8")
        (folder / "source.json").write_text(json.dumps({
            "source": "FinMind-derived intraday signals (real-time fields not republished)",
            "history_source": "FinMind (listed), TPEx (OTC)", "price_basis": "unadjusted",
            "market_date": str(quote_day), "as_of": as_of.isoformat(),
            "history_end": str(prior_day), "min_volume_lots": 1300,
            "screening": SCREENING,
        }, ensure_ascii=False), encoding="utf-8")
        archive = folder / f"tw_stock_{quote_day}_1300lots.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(folder.iterdir()):
                if path.suffix in (".csv", ".parquet", ".json"):
                    bundle.write(path, path.name)
        self.activate(str(folder))
        self.update(status="complete", stage="完成", data_dir=str(folder), archive=str(archive),
                    selected=len(matches), failed=len(errors), source="FinMind-derived intraday signals")

