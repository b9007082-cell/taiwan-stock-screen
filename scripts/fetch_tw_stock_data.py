"""
Fetch Taiwan stock daily candles into parquet files for the web app.

Output format:
    {code}_D1.parquet
    columns: time, open, high, low, close, tick_volume
"""

from __future__ import annotations

import argparse
import csv
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.tw_official_data import download_one

DEFAULT_SYMBOLS = ["2881", "2330", "2317", "2454", "2603"]
ISIN_URLS = {
    "listed": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2",
    "otc": "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4",
}


def _normalize_symbol(symbol: str) -> str:
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("empty symbol")
    return symbol


def _download_one(symbol: str, start: str, end: str, market: str | None = None) -> tuple[str, pd.DataFrame, str]:
    if market is None:
        if symbol.endswith(".TWO"):
            market = "otc"
        elif symbol.endswith(".TW"):
            market = "listed"
        else:
            market = next((r["market"] for r in fetch_all_symbols() if r["code"] == symbol), None)
        if market is None:
            raise ValueError(f"{symbol}: 不在上市櫃普通股清單")
    return download_one(symbol, start, end, market)


def _recent_avg_volume_lots(df: pd.DataFrame, window: int) -> float:
    if df.empty:
        return 0.0
    volume = pd.to_numeric(df["tick_volume"], errors="coerce").dropna()
    if volume.empty:
        return 0.0
    recent = volume.tail(max(1, window))
    return float(recent.mean() / 1000.0)


def _fetch_isin_market(market: str) -> list[dict[str, str]]:
    url = ISIN_URLS[market]
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.content, "html.parser")
    rows: list[dict[str, str]] = []

    for tr in soup.select("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
        if len(cells) < 6:
            continue

        code_name = cells[0].replace("\u3000", " ").strip()
        parts = code_name.split(maxsplit=1)
        if not parts:
            continue

        code = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        cfi_code = cells[5].strip().upper()

        # ESVUFR is used by TWSE ISIN pages for ordinary shares.
        if code.isdigit() and len(code) == 4 and cfi_code == "ESVUFR":
            rows.append({"code": code, "name": name, "market": market})

    return rows


def fetch_all_symbols(market: str = "all") -> list[dict[str, str]]:
    markets = ["listed", "otc"] if market == "all" else [market]
    symbols: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item_market in markets:
        for row in _fetch_isin_market(item_market):
            key = (row["code"], row["market"])
            if key in seen:
                continue
            seen.add(key)
            symbols.append(row)

    return symbols


def _write_symbol_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["code", "name", "market"])
        writer.writeheader()
        writer.writerows(rows)


def _fetch_and_save(
    row: dict[str, str],
    start: str,
    end: str,
    out_dir: Path,
    force: bool,
    min_volume_lots: float,
    volume_window: int,
) -> tuple[bool, str]:
    code = row["code"]
    path = out_dir / f"{code}_D1.parquet"
    if path.exists() and not force:
        try:
            df = pd.read_parquet(path, columns=["time", "tick_volume"])
            if len(df) >= 60:
                avg_lots = _recent_avg_volume_lots(df, volume_window)
                if min_volume_lots > 0 and avg_lots < min_volume_lots:
                    return False, f"[filter] {code} avg_volume={avg_lots:.0f} lots < {min_volume_lots:.0f}"
                return True, f"[skip] {code} exists ({len(df)} bars)"
        except Exception:
            pass

    code_out, df, ticker = _download_one(code, start, end, row.get("market"))
    avg_lots = _recent_avg_volume_lots(df, volume_window)
    if min_volume_lots > 0 and avg_lots < min_volume_lots:
        return False, f"[filter] {code_out} ({ticker}) avg_volume={avg_lots:.0f} lots < {min_volume_lots:.0f}"

    path = out_dir / f"{code_out}_D1.parquet"
    df.to_parquet(path, index=False)
    first = pd.to_datetime(df["time"].iloc[0], unit="s").date()
    last = pd.to_datetime(df["time"].iloc[-1], unit="s").date()
    return True, f"[ok] {code_out} ({ticker}) {len(df)} bars {first}..{last} avg_volume={avg_lots:.0f} lots"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Taiwan stock daily candles.")
    parser.add_argument(
        "symbols",
        nargs="*",
        default=DEFAULT_SYMBOLS,
        help="Taiwan ordinary stock codes, e.g. 2330 2317 8069.TWO",
    )
    parser.add_argument(
        "--start",
        default=(date.today() - timedelta(days=365 * 3)).isoformat(),
        help="Start date, YYYY-MM-DD. Default: 3 years ago.",
    )
    parser.add_argument(
        "--end",
        default=(date.today() + timedelta(days=1)).isoformat(),
        help="End date, YYYY-MM-DD. Default: tomorrow.",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "data" / "tw_stock"),
        help="Output folder for parquet files.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch all TWSE/TPEX ordinary shares from the official ISIN lists.",
    )
    parser.add_argument(
        "--market",
        choices=["all", "listed", "otc"],
        default="all",
        help="Market scope for --all. Default: all.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=6,
        help="Concurrent downloads for --all. Default: 6.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing parquet files instead of skipping them.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit the number of symbols, useful for testing.",
    )
    parser.add_argument(
        "--min-volume-lots",
        type=float,
        default=0,
        help="Keep only symbols whose recent average volume is at least this many lots.",
    )
    parser.add_argument(
        "--volume-window",
        type=int,
        default=20,
        help="Number of recent trading days used for --min-volume-lots. Default: 20.",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.all:
        symbol_rows = fetch_all_symbols(args.market)
        if args.limit > 0:
            symbol_rows = symbol_rows[:args.limit]
        _write_symbol_manifest(out_dir / "tw_stock_symbols.csv", symbol_rows)
        print(f"Fetched symbol list: {len(symbol_rows)} ordinary shares")

        failures: list[dict[str, str]] = []
        ok = 0
        started = time.time()
        workers = max(1, min(args.workers, 16))
        filtered: list[dict[str, str]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _fetch_and_save,
                    row,
                    args.start,
                    args.end,
                    out_dir,
                    args.force,
                    args.min_volume_lots,
                    args.volume_window,
                ): row
                for row in symbol_rows
            }
            for i, future in enumerate(as_completed(futures), start=1):
                row = futures[future]
                try:
                    success, message = future.result()
                except Exception as exc:
                    success = False
                    message = f"[fail] {row['code']}: {exc}"
                if success:
                    ok += 1
                elif message.startswith("[filter]"):
                    filtered.append({"code": row["code"], "market": row["market"], "reason": message})
                else:
                    failures.append({"code": row["code"], "market": row["market"], "reason": message})
                print(f"{i}/{len(symbol_rows)} {message}")

        kept_rows = [row for row in symbol_rows if (out_dir / f"{row['code']}_D1.parquet").exists()]
        if args.min_volume_lots > 0:
            _write_symbol_manifest(out_dir / "tw_stock_symbols.csv", kept_rows)
            filter_path = out_dir / "tw_stock_volume_filtered.csv"
            with filter_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["code", "market", "reason"])
                writer.writeheader()
                writer.writerows(filtered)
            print(f"Volume-filtered symbols saved to {filter_path}")

        if failures:
            fail_path = out_dir / "tw_stock_fetch_failures.csv"
            with fail_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.DictWriter(f, fieldnames=["code", "market", "reason"])
                writer.writeheader()
                writer.writerows(failures)
            print(f"Failures saved to {fail_path}")

        elapsed = time.time() - started
        print(f"Done. Saved/skipped {ok}/{len(symbol_rows)} symbols to {out_dir} in {elapsed:.1f}s")
        return 0 if ok else 1

    ok = 0
    for raw_symbol in args.symbols:
        symbol = _normalize_symbol(raw_symbol)
        try:
            code, df, ticker = _download_one(symbol, args.start, args.end)
        except Exception as exc:
            print(f"[fail] {symbol}: {exc}")
            continue

        avg_lots = _recent_avg_volume_lots(df, args.volume_window)
        if args.min_volume_lots > 0 and avg_lots < args.min_volume_lots:
            print(f"[filter] {code} ({ticker}) avg_volume={avg_lots:.0f} lots < {args.min_volume_lots:.0f}")
            continue

        path = out_dir / f"{code}_D1.parquet"
        df.to_parquet(path, index=False)
        first = pd.to_datetime(df["time"].iloc[0], unit="s").date()
        last = pd.to_datetime(df["time"].iloc[-1], unit="s").date()
        print(f"[ok] {code} ({ticker}) {len(df)} bars {first}..{last} avg_volume={avg_lots:.0f} lots -> {path}")
        ok += 1

    print(f"Done. Saved {ok}/{len(args.symbols)} symbols to {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
