"""Daily Taiwan snapshots, isolated from previously downloaded datasets."""

import csv
import json
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from scripts.fetch_tw_stock_data import fetch_all_symbols
from scripts.screen_tw_pullback import CRITERIA, SCREENING, signal
from src.tw_official_data import latest_reports, selected_history


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class DailyUpdater:
    def __init__(self, root, activate):
        self.root = Path(root)
        self.activate = activate
        self.lock = threading.Lock()
        self.state = {"status": "idle"}
        self.saved = self.root / "output" / "tw_daily_latest.json"
        if self.saved.exists():
            try:
                self.state = json.loads(self.saved.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass

    def status(self):
        with self.lock:
            return dict(self.state)

    def update(self, **values):
        with self.lock:
            self.state.update(values)

    def start(self):
        with self.lock:
            if self.state["status"] == "running":
                return False
            self.state = {"status": "running", "stage": "取得股票清單", "done": 0,
                          "total": 0, "selected": 0, "failed": 0, "min_volume_lots": 1300}
        threading.Thread(target=self.run, daemon=True).start()
        return True

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self.update(status="error", error=str(exc))

    def _run(self):
        now = datetime.now(ZoneInfo("Asia/Taipei"))
        # Before 16:00 only request prior days, avoiding partial daily volume.
        end = now.date() + timedelta(days=int(now.hour >= 16))
        rows = fetch_all_symbols()
        if not rows or not all(any(r["market"] == m for r in rows) for m in ("listed", "otc")):
            raise RuntimeError("上市或上櫃股票清單不完整，請稍後重試。")
        self.update(stage="確認交易日期", total=len(rows))
        target, latest = latest_reports(end - timedelta(days=1))
        start = (pd.Timestamp(target).replace(day=1) - pd.DateOffset(months=5)).date()
        universe = {(r["code"], r["market"]): r for r in rows}
        latest = latest[[key in universe for key in zip(latest.code, latest.market)]]
        liquid = latest[latest.tick_volume >= 1300000]
        eligible = liquid[liquid.close > liquid.open]
        folder = self.root / "data" / "tw_daily" / now.strftime("%Y%m%d_%H%M%S_%f")
        folder.mkdir(parents=True)
        self.update(stage="補齊歷史資料", market_date=target.isoformat(),
                    source="TWSE/TPEx", history_source="FinMind/TPEx", price_basis="unadjusted",
                    selected=0, min_volume_lots=1300, screening=SCREENING,
                    liquid_universe=len(liquid), red_candidates=len(eligible))
        selected, errors, matches = [], [], []
        history = selected_history(start, target, eligible.to_dict("records"),
                                   lambda done, total: self.update(done=done, total=total)) if len(eligible) else eligible.copy()
        # The daily report supplies exact shares, replacing rounded monthly TPEx volume on the target day.
        history = pd.concat([history, eligible], ignore_index=True).drop_duplicates(["code", "market", "time"], keep="last")
        history = history[history.time <= int((pd.Timestamp(target) - pd.Timestamp("1970-01-01")).total_seconds())]
        groups = history.groupby(["code", "market"])
        self.update(stage="整理股票資料", done=0, total=len(eligible))
        for done, item in enumerate(eligible.to_dict("records"), 1):
            self.update(done=done)
            row = universe[(item["code"], item["market"])]
            if any(pd.isna(item[k]) for k in ("open", "high", "low", "close")):
                errors.append({"code": row["code"], "reason": "官方當日價格欄位不完整"})
                continue
            frame = groups.get_group((row["code"], row["market"])).drop(columns=["code", "name", "market"])
            frame = frame.dropna().drop_duplicates("time").sort_values("time")
            if len(frame[frame.tick_volume > 0]) < 65:
                errors.append({"code": row["code"], "reason": "有效歷史不足 65 根日 K"})
                continue
            metrics = signal(frame)
            if metrics is None:
                continue
            matches.append({**row, **metrics})
            shares = float(item["tick_volume"])
            frame.to_parquet(folder / f"{row['code']}_D1.parquet", index=False)
            export = frame.copy()
            export.insert(0, "date", pd.to_datetime(export.pop("time"), unit="s").dt.strftime("%Y-%m-%d"))
            export.rename(columns={"tick_volume": "volume_shares"}).to_csv(
                folder / f"{row['code']}_D1.csv", index=False, encoding="utf-8-sig")
            selected.append({**row, "last_date": str(target), "volume_lots": shares / 1000})
            self.update(done=done, selected=len(selected), failed=len(errors))

        selected.sort(key=lambda r: r["code"])
        write_csv(folder / "tw_stock_symbols.csv", selected,
                  ["code", "name", "market", "last_date", "volume_lots"])
        write_csv(folder / "fetch_errors.csv", errors, ["code", "reason"])
        self.update(stage="建立下載檔", selected=len(selected), failed=len(errors))
        (folder / "screening_results.json").write_text(json.dumps({
            "date": str(target), "screening": SCREENING, "min_volume_lots": 1300,
            "liquid_universe": len(liquid), "red_candidates": len(eligible), "matches": matches,
            "criteria": CRITERIA,
        }, ensure_ascii=False), encoding="utf-8")
        (folder / "source.json").write_text(json.dumps({
            "source": "TWSE/TPEx", "history_source": "FinMind (listed), TPEx (OTC)",
            "price_basis": "unadjusted", "volume_unit": "shares",
            "market_date": str(target), "history_start": str(start), "min_volume_lots": 1300,
            "screening": SCREENING,
            "history_volume_note": "TPEx monthly historical volume is rounded to lots and converted to shares; target-day volume is exact shares.",
        }), encoding="utf-8")
        archive = folder / f"tw_stock_{target}_1300lots.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in sorted(folder.iterdir()):
                if path.suffix in (".csv", ".parquet", ".json"):
                    bundle.write(path, path.name)
        self.activate(str(folder))
        self.update(status="complete", stage="完成", data_dir=str(folder), archive=str(archive))
        self.saved.parent.mkdir(parents=True, exist_ok=True)
        temp = self.saved.with_suffix(".tmp")
        temp.write_text(json.dumps(self.status(), ensure_ascii=False), encoding="utf-8")
        temp.replace(self.saved)
