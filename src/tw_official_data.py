"""TWSE/TPEx daily snapshots and FinMind/TPEx unadjusted history."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
import time
import threading

import pandas as pd
import requests

URLS = {
    "listed": "https://www.twse.com.tw/exchangeReport/MI_INDEX",
    "otc": "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes",
}
COLUMNS = ["code", "name", "market", "time", "open", "high", "low", "close", "tick_volume"]
CACHE = Path(__file__).resolve().parents[1] / ".cache" / "official_daily_v1"
_local = threading.local()


def parse_report(payload, market, day):
    if market == "listed" and "沒有符合條件" in payload.get("stat", ""):
        return pd.DataFrame(columns=COLUMNS)
    if payload.get("date") != day.strftime("%Y%m%d"):
        raise ValueError(f"{market} 回傳日期與查詢日期 {day} 不符")
    code_field = "證券代號" if market == "listed" else "代號"
    table = next((t for t in payload.get("tables", []) if code_field in t.get("fields", [])), None)
    if table is None:
        raise ValueError(f"{market} {day} 缺少官方行情表")
    mapping = ({"code": "證券代號", "name": "證券名稱", "open": "開盤價", "high": "最高價",
                "low": "最低價", "close": "收盤價", "tick_volume": "成交股數"} if market == "listed" else
               {"code": "代號", "name": "名稱", "open": "開盤", "high": "最高",
                "low": "最低", "close": "收盤", "tick_volume": "成交股數"})
    if not set(mapping.values()).issubset(table["fields"]):
        raise ValueError(f"{market} 行情欄位已變更")
    df = pd.DataFrame(table.get("data", []), columns=table["fields"])
    df = df[list(mapping.values())].rename(columns={v: k for k, v in mapping.items()})
    df = df[df.code.astype(str).str.fullmatch(r"[1-9][0-9]{3}")].copy()
    for field in ["open", "high", "low", "close", "tick_volume"]:
        df[field] = pd.to_numeric(df[field].astype(str).str.replace(",", "", regex=False), errors="coerce")
    df["market"] = market
    df["time"] = int((pd.Timestamp(day) - pd.Timestamp("1970-01-01")).total_seconds())
    return df[COLUMNS]


def daily_report(market, day, refresh=False):
    path = CACHE / market / f"{day:%Y%m%d}.parquet"
    if path.exists() and not refresh:
        return pd.read_parquet(path)
    params = {"response": "json", "date": day.strftime("%Y%m%d" if market == "listed" else "%Y/%m/%d")}
    if market == "listed":
        params["type"] = "ALLBUT0999"
    for attempt in range(3):
        try:
            if not hasattr(_local, "session"):
                _local.session = requests.Session()
            response = _local.session.get(URLS[market], params=params, timeout=30)
            response.raise_for_status()
            frame = parse_report(response.json(), market, day)
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            frame.to_parquet(temp, index=False)
            temp.replace(path)
            return frame
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def monthly_history(code, market, month, refresh=False):
    suffix = f"_{refresh}" if isinstance(refresh, date) else ""
    path = CACHE / "monthly" / market / code / f"{month:%Y%m}{suffix}.parquet"
    if path.exists() and (not refresh or isinstance(refresh, date)):
        return pd.read_parquet(path)
    if market == "listed":
        url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
        params = {"response": "json", "date": month.strftime("%Y%m%d"), "stockNo": code}
    else:
        url = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
        params = {"response": "json", "date": month.strftime("%Y/%m/%d"), "code": code}
    time.sleep(0.3)
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("date") != month.strftime("%Y%m%d"):
        if "沒有符合條件" in data.get("stat", ""):
            return pd.DataFrame(columns=COLUMNS)
        raise ValueError(f"{code} {month} 官方歷史日期不符")
    table = data if market == "listed" else data.get("tables", [{}])[0]
    fields = table.get("fields", [])
    expected = (["日期", "成交股數", "開盤價", "最高價", "最低價", "收盤價"] if market == "listed" else
                ["日 期", "成交張數", "開盤", "最高", "最低", "收盤"])
    if not set(expected).issubset(fields):
        raise ValueError(f"{code} 官方歷史欄位已改變")
    records = []
    for row in table.get("data", []):
        values = dict(zip(fields, row))
        roc = [int(x) for x in values[expected[0]].strip().rstrip("*").split("/")]
        day = date(roc[0] + 1911, roc[1], roc[2])
        prices = [pd.to_numeric(str(values[f]).replace(",", ""), errors="coerce") for f in expected[2:]]
        volume = pd.to_numeric(str(values[expected[1]]).replace(",", ""), errors="coerce")
        if market == "otc":
            volume *= 1000
        records.append(dict(zip(COLUMNS, [code, code, market,
            int((pd.Timestamp(day) - pd.Timestamp("1970-01-01")).total_seconds()), *prices, volume])))
    frame = pd.DataFrame(records, columns=COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return frame


def finmind_history(code, start, end):
    path = CACHE / "finmind" / f"{code}_{start}_{end}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    response = requests.get("https://api.finmindtrade.com/api/v4/data", params={
        "dataset": "TaiwanStockPrice", "data_id": code,
        "start_date": str(start), "end_date": str(end),
    }, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != 200:
        raise ValueError(f"FinMind {code}: {payload.get('msg', 'request failed')}")
    df = pd.DataFrame(payload.get("data", []))
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    df = df.rename(columns={"stock_id": "code", "max": "high", "min": "low", "Trading_Volume": "tick_volume"})
    if not (df.code == code).all():
        raise ValueError("FinMind 股票代碼不符")
    df["time"] = (pd.to_datetime(df.date) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
    df["name"], df["market"] = code, "listed"
    df = df[COLUMNS]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
    return df


INSTITUTIONAL_COLUMNS = ["date", "code", "market", "foreign_net", "trust_net", "dealer_net", "total_net"]


def _number(value):
    return pd.to_numeric(str(value).replace(",", ""), errors="coerce")


def institutional_daily_report(market, day):
    """Fetch one official TWSE/TPEx three-institution report (values in shares)."""
    path = CACHE / "institutional" / market / f"{day:%Y%m%d}.parquet"
    if path.exists():
        return pd.read_parquet(path)
    if market == "listed":
        response = requests.get("https://www.twse.com.tw/rwd/zh/fund/T86", params={
            "response": "json", "date": day.strftime("%Y%m%d"), "selectType": "ALLBUT0999",
        }, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if payload.get("date") != day.strftime("%Y%m%d"):
            return pd.DataFrame(columns=INSTITUTIONAL_COLUMNS)
        fields = payload.get("fields", [])
        required = ["證券代號", "外陸資買賣超股數(不含外資自營商)", "投信買賣超股數",
                    "自營商買賣超股數", "三大法人買賣超股數"]
        if not set(required).issubset(fields):
            raise ValueError("TWSE 三大法人欄位已變更")
        indexes = [fields.index(name) for name in required]
        rows = [[day, row[indexes[0]], market, *[_number(row[i]) for i in indexes[1:]]]
                for row in payload.get("data", [])]
    elif market == "otc":
        roc = f"{day.year - 1911:03d}/{day.month:02d}/{day.day:02d}"
        response = requests.get("https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade", params={
            "type": "Daily", "sect": "EW", "date": roc, "id": "", "response": "json",
        }, timeout=30)
        response.raise_for_status()
        payload = response.json()
        table = next((t for t in payload.get("tables", []) if t.get("title") == "三大法人買賣明細資訊"), None)
        if not table or table.get("date") != roc:
            return pd.DataFrame(columns=INSTITUTIONAL_COLUMNS)
        rows = [[day, row[0], market, _number(row[10]), _number(row[13]),
                 _number(row[22]), _number(row[23])]
                for row in table.get("data", []) if len(row) >= 24]
    else:
        raise ValueError(f"Unknown market: {market}")
    frame = pd.DataFrame(rows, columns=INSTITUTIONAL_COLUMNS)
    frame["code"] = frame.code.astype(str).str.strip().str.strip('="')
    frame = frame[frame.code.str.fullmatch(r"[1-9][0-9]{3}")].dropna(subset=INSTITUTIONAL_COLUMNS[3:])
    totals = frame.foreign_net + frame.trust_net + frame.dealer_net
    frame = frame[(totals - frame.total_net).abs() < 0.5]
    if not frame.empty:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        frame.to_parquet(temp, index=False)
        temp.replace(path)
    return frame


def institutional_history(symbols, days):
    """Return official daily institutional flows for selected symbols, fail-open."""
    symbol_markets = {(str(row["code"]), row.get("market", "listed")) for row in symbols}
    markets = sorted({market for _, market in symbol_markets})
    jobs = [(market, day) for day in sorted(set(days)) for market in markets]
    frames, failed = [], False
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(institutional_daily_report, *job): job for job in jobs}
        for future in as_completed(futures):
            try:
                frame = future.result()
                if not frame.empty:
                    frames.append(frame)
            except (requests.RequestException, ValueError, TypeError, KeyError):
                failed = True
    if frames:
        result = pd.concat(frames, ignore_index=True)
        result = result[result.apply(lambda row: (row.code, row.market) in symbol_markets, axis=1)]
        result = result.sort_values(["code", "date"])
    else:
        result = pd.DataFrame(columns=INSTITUTIONAL_COLUMNS)
    result.attrs["status"] = "partial" if failed and not result.empty else ("unavailable" if failed else "available")
    return result


def selected_history(start, end, symbols, progress=None):
    months = pd.date_range(pd.Timestamp(start).replace(day=1), end, freq="MS")
    jobs = [(monthly_history, (r["code"], r["market"], m.date(), end if m.date() == end.replace(day=1) else False))
            for r in symbols if r["market"] == "otc" for m in months]
    jobs += [(finmind_history, (r["code"], start, end)) for r in symbols if r["market"] == "listed"]
    frames = []
    pool = ThreadPoolExecutor(max_workers=2)
    futures = {pool.submit(fn, *args): args[0] for fn, args in jobs}
    try:
        for done, future in enumerate(as_completed(futures), 1):
            frames.append(future.result())
            if progress:
                progress(done, len(jobs))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    nonempty = [f for f in frames if not f.empty]
    return pd.concat(nonempty, ignore_index=True).sort_values("time") if nonempty else pd.DataFrame(columns=COLUMNS)


def latest_reports(cutoff):
    # Query both markets on the same explicit date; never hide a one-market gap.
    for back in range(15):
        day = cutoff - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        frames = [daily_report(m, day, refresh=True) for m in URLS]
        if all(not f.empty for f in frames):
            return day, pd.concat(frames, ignore_index=True)
        if any(not f.empty for f in frames):
            raise ValueError(f"{day} 上市與上櫃官方資料尚未齊全，請稍後再試")
    raise ValueError("官方來源尚無近期完整資料")


def download_one(symbol, start, end, market=None):
    code = symbol.split(".")[0]
    market = market or ("otc" if symbol.endswith(".TWO") else None)
    markets = [market] if market else ["listed", "otc"]
    df = selected_history(date.fromisoformat(start), date.fromisoformat(end) - timedelta(days=1),
                          [{"code": code, "market": m} for m in markets])
    df = df[df.code == code]
    if market:
        df = df[df.market == market]
    if df.empty:
        raise ValueError(f"{code}: 無官方行情")
    first = int((pd.Timestamp(start) - pd.Timestamp("1970-01-01")).total_seconds())
    last = int((pd.Timestamp(end) - pd.Timestamp("1970-01-01")).total_seconds())
    df = df[(df.time >= first) & (df.time < last)]
    return code, df.drop(columns=["code", "name", "market"]).dropna(), "TWSE/TPEx"
