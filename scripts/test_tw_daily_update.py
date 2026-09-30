import json
import tempfile
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock, patch
import pandas as pd
from src.tw_daily_update import DailyUpdater
from src.tw_intraday_update import IntradayUpdater, fetch_finmind_snapshot
from src.tw_official_data import parse_report, latest_reports, monthly_history, finmind_history
from scripts.screen_tw_pullback import signal, swing_structure, bullish_reasons


class PullbackSignalTests(unittest.TestCase):
    def setUp(self):
        # These tests isolate candle/MA thresholds from structural qualification.
        mock = patch('scripts.screen_tw_pullback.swing_structure', return_value={'highs': [], 'lows': []})
        mock.start()
        self.addCleanup(mock.stop)

    def frame(self):
        closes = list(range(100, 180)) + [176, 173, 172, 173, 174, 177]
        return pd.DataFrame({"time": range(len(closes)), "close": closes,
                             "open": [c - 1 for c in closes], "high": [c + 1 for c in closes],
                             "low": [c - 2 for c in closes], "tick_volume": 1300000}).astype(float)

    def test_relaxed_low_and_close_position(self):
        frame = self.frame()
        frame.loc[85, "low"] = frame.loc[84, "low"] * 0.99
        self.assertIsNotNone(signal(frame))
        frame.loc[85, "low"] -= 0.01
        self.assertIsNone(signal(frame))
        frame = self.frame()
        frame.loc[85, "high"] = 180
        self.assertIsNotNone(signal(frame))  # (177 - 175) / (180 - 175) = 0.4
        frame.loc[85, "high"] = 180.01
        self.assertIsNone(signal(frame))

    def test_retains_red_candle_and_history_requirements(self):
        frame = self.frame()
        self.assertIsNotNone(signal(frame))
        self.assertIsNone(signal(frame.tail(64)))
        frame.loc[85, "open"] = frame.loc[85, "close"]
        self.assertIsNone(signal(frame))

    def test_structure_branch_does_not_require_ma_slope(self):
        frame = self.frame()
        # These five bars leave the 60-bar window during the slope comparison.
        frame.loc[21:25, "close"] += 52
        ma = frame.close.rolling(60).mean()
        self.assertLess(ma.iloc[-1], ma.iloc[-6])
        self.assertIsNotNone(signal(frame))
        frame.loc[21:25, "close"] += 20
        self.assertIsNotNone(signal(frame))

    def test_ma_branch_without_structure(self):
        frame = self.frame()
        values = [182, 177, 175, 174, 179]
        for column, offset in [('close', 0), ('open', -1), ('high', 1), ('low', -2)]:
            frame.loc[81:85, column] = [v + offset for v in values]
        with patch('scripts.screen_tw_pullback.swing_structure', return_value=None):
            result = signal(frame)
            self.assertIsNotNone(result)
            self.assertIsNone(result['structure'])
            self.assertEqual(result['bullish_reasons'], ['ma3', 'ma4'])
            frame.loc[85, 'open'] = frame.loc[85, 'close']
            self.assertIsNone(signal(frame))


class BullishOrTests(unittest.TestCase):
    def test_independent_branches_and_strict_order(self):
        self.assertEqual(bullish_reasons({}, {5: 1, 10: 2, 20: 3, 60: 4}), ['hhhl'])
        self.assertEqual(bullish_reasons(None, {5: 4, 10: 3, 20: 2, 60: 5}), ['ma3'])
        self.assertEqual(bullish_reasons(None, {5: 4, 10: 3, 20: 2, 60: 1}), ['ma3', 'ma4'])
        self.assertEqual(bullish_reasons({}, {5: 4, 10: 3, 20: 2, 60: 1}), ['hhhl', 'ma3', 'ma4'])
        for values in ({5: 3, 10: 3, 20: 2, 60: 1}, {5: 4, 10: 2, 20: 2, 60: 1}, {5: 1, 10: 2, 20: 3, 60: 4}):
            self.assertEqual(bullish_reasons(None, values), [])


class StructureTests(unittest.TestCase):
    def frame(self, values=None):
        values = values or [10, 11, 14, 12, 11, 9, 10, 12, 16, 14, 12, 11, 12, 13, 14]
        return pd.DataFrame({'time': range(len(values)), 'high': [v + 0.5 for v in values], 'low': [v - 0.5 for v in values]})

    def test_higher_highs_and_lows(self):
        result = swing_structure(self.frame())
        self.assertEqual([p['price'] for p in result['highs']], [14.5, 16.5])
        self.assertEqual([p['price'] for p in result['lows']], [8.5, 10.5])

    def test_lower_or_equal_high_and_low_fail(self):
        for column, index, value in [('high', 8, 14.5), ('high', 8, 14), ('low', 11, 8.5), ('low', 11, 8)]:
            frame = self.frame()
            frame.loc[index, column] = value
            self.assertIsNone(swing_structure(frame))

    def test_unconfirmed_and_broken_low_fail(self):
        self.assertIsNone(swing_structure(self.frame().iloc[:13]))
        frame = self.frame()
        frame.loc[14, 'low'] = 10
        self.assertIsNone(swing_structure(frame))

    def test_signal_rejects_when_no_trend_branch_matches(self):
        frame = PullbackSignalTests().frame()
        self.assertIsNone(signal(frame))


class OfficialDataTests(unittest.TestCase):
    def report(self, market, close="10"):
        fields = (["證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價", "成交股數"]
                  if market == "listed" else ["代號", "名稱", "開盤", "最高", "最低", "收盤", "成交股數"])
        return {"date": "20260914", "tables": [{"fields": fields, "data": [
            ["2330", "name", "10", "11", "9", close, "1,499,722"],
            ["0050", "ETF", "10", "11", "9", "10", "9999999"],
        ]}]}

    def test_units_and_missing_prices(self):
        for market in ("listed", "otc"):
            frame = parse_report(self.report(market), market, date(2026, 9, 14))
            self.assertEqual(len(frame), 1)
            self.assertEqual(frame.tick_volume.iloc[0], 1499722)
            frame = parse_report(self.report(market, close="---"), market, date(2026, 9, 14))
            self.assertTrue(pd.isna(frame.close.iloc[0]))

    def test_wrong_date_fails(self):
        with self.assertRaises(ValueError):
            parse_report(self.report("listed"), "listed", date(2026, 9, 15))

    def test_mixed_market_dates_fail(self):
        with patch("src.tw_official_data.daily_report", side_effect=[pd.DataFrame({"x": [1]}), pd.DataFrame()]):
            with self.assertRaises(ValueError):
                latest_reports(date(2026, 9, 14))

    @patch('scripts.screen_tw_pullback.swing_structure', return_value={'highs': [], 'lows': []})
    def test_snapshot_threshold_history_and_archive(self, structure):
        rows = [{"code": c, "name": c, "market": m} for c, m in [("2330", "listed"), ("8069", "otc"), ("1101", "listed")]]
        closes = list(range(100, 180)) + [176, 173, 172, 173, 174, 177]
        history = pd.concat([pd.DataFrame({
            **r, "time": (pd.date_range(end="2026-09-14", periods=len(closes)) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1),
            "open": [c - 1 for c in closes], "high": [c + 1 for c in closes],
            "low": [c - 2 for c in closes], "close": closes,
            "tick_volume": 1299722 if r["code"] == "1101" else 1300000,
        }) for r in rows], ignore_index=True)
        latest = history.groupby("code").tail(1)
        with tempfile.TemporaryDirectory() as tmp, \
                patch("src.tw_daily_update.fetch_all_symbols", return_value=rows), \
                patch("src.tw_daily_update.latest_reports", return_value=(date(2026, 9, 14), latest)) as reports, \
                patch("src.tw_daily_update.selected_history", return_value=history), \
                patch("src.tw_daily_update.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 15, 1)
            activate = Mock()
            job = DailyUpdater(tmp, activate)
            job.run()
            result = job.status()
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["selected"], 2)
            reports.assert_called_with(date(2026, 9, 14))
            with zipfile.ZipFile(result["archive"]) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertNotIn("1101_D1.csv", bundle.namelist())
                self.assertEqual(json.loads(bundle.read("source.json"))["source"], "TWSE/TPEx")
            folder = Path(result["data_dir"])
            self.assertEqual(len(pd.read_parquet(folder / "2330_D1.parquet")), len(closes))
            clock.now.return_value = datetime(2026, 9, 15, 1, 1)
            job.run()
            self.assertNotEqual(result["data_dir"], job.status()["data_dir"])
            self.assertTrue(folder.exists())
            self.assertEqual(DailyUpdater(tmp, activate).status()["source"], "TWSE/TPEx")
            with patch("src.tw_daily_update.signal", return_value=None):
                clock.now.return_value = datetime(2026, 9, 15, 1, 2)
                job.run()
            self.assertEqual(job.status()["status"], "complete")
            self.assertEqual(job.status()["selected"], 0)
            with zipfile.ZipFile(job.status()["archive"]) as bundle:
                self.assertFalse(any(n.endswith(".parquet") for n in bundle.namelist()))
                self.assertEqual(json.loads(bundle.read("screening_results.json"))["matches"], [])

    def test_failure_preserves_active_dataset(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.tw_daily_update.fetch_all_symbols", side_effect=ValueError("offline")):
            activate = Mock()
            job = DailyUpdater(tmp, activate)
            job.run()
            self.assertEqual(job.status()["status"], "error")
            activate.assert_not_called()

    def test_no_duplicate_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch("src.tw_daily_update.threading.Thread") as thread:
            job = DailyUpdater(tmp, Mock())
            self.assertTrue(job.start())
            self.assertFalse(job.start())
            thread.return_value.start.assert_called_once()

    def test_otc_monthly_volume_and_cache(self):
        payload = {"date": "20260901", "tables": [{"fields": ["日 期", "成交張數", "開盤", "最高", "最低", "收盤"],
                    "data": [["115/09/14*", "4,039", "145", "148", "143", "145.5"]]}]}
        with tempfile.TemporaryDirectory() as tmp, patch("src.tw_official_data.CACHE", Path(tmp)), \
                patch("src.tw_official_data.requests.get") as get, patch("src.tw_official_data.time.sleep"):
            get.return_value.json.return_value = payload
            frame = monthly_history("8069", "otc", date(2026, 9, 1))
            self.assertEqual(frame.tick_volume.iloc[0], 4039000)
            monthly_history("8069", "otc", date(2026, 9, 1))
            get.assert_called_once()

    def test_finmind_shares_and_cache(self):
        payload = {"status": 200, "data": [{"date": "2026-09-14", "stock_id": "2330", "open": 2385,
                   "max": 2395, "min": 2380, "close": 2380, "Trading_Volume": 21520958}]}
        with tempfile.TemporaryDirectory() as tmp, patch("src.tw_official_data.CACHE", Path(tmp)), \
                patch("src.tw_official_data.requests.get") as get:
            get.return_value.json.return_value = payload
            frame = finmind_history("2330", date(2026, 4, 1), date(2026, 9, 14))
            self.assertEqual(frame.tick_volume.iloc[0], 21520958)
            self.assertEqual(frame.close.iloc[0], 2380)
            finmind_history("2330", date(2026, 4, 1), date(2026, 9, 14))
            get.assert_called_once()


class IntradayUpdateTests(unittest.TestCase):
    def test_snapshot_schema_and_lot_unit_are_preserved(self):
        response = Mock()
        response.json.return_value = {"status": 200, "data": [{
            "stock_id": "2330", "date": "2026-09-15 12:00:01", "open": 100,
            "high": 103, "low": 99, "close": 102, "total_volume": 1300,
        }]}
        with patch("src.tw_intraday_update.requests.get", return_value=response) as get:
            frame = fetch_finmind_snapshot("secret")
        self.assertEqual(frame.total_volume.iloc[0], 1300)
        self.assertEqual(frame.code.iloc[0], "2330")
        self.assertEqual(get.call_args.kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertNotIn("params", get.call_args.kwargs)

    def test_snapshot_http_error_includes_finmind_message(self):
        response = Mock(ok=False, status_code=403, reason="Forbidden")
        response.json.return_value = {"detail": "sponsor required"}
        with patch("src.tw_intraday_update.requests.get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403.*sponsor required"):
                fetch_finmind_snapshot("secret")

    def test_public_intraday_artifact_excludes_realtime_ohlcv(self):
        rows = [{"code": "2330", "name": "台積電", "market": "listed"},
                {"code": "8069", "name": "元太", "market": "otc"}]
        times = (pd.date_range(end="2026-09-14", periods=70) - pd.Timestamp("1970-01-01")) // pd.Timedelta(seconds=1)
        history = pd.DataFrame({
            "code": "2330", "name": "台積電", "market": "listed", "time": times,
            "open": 100., "high": 103., "low": 99., "close": 102., "tick_volume": 1500000.,
        })
        snapshot = pd.DataFrame([{
            "code": "2330", "date": "2026-09-15 12:00:01",
            "quote_time": pd.Timestamp("2026-09-15 12:00:01"), "open": 100.,
            "high": 110., "low": 99., "close": 108., "total_volume": 1300.,
        }])
        metrics = {"bullish_reasons": ["ma3"], "structure": None, "pullback_pct": 5.,
                   "prior_declining_days": 2, "reclaimed_previous_high": True, "data_bars": 71}
        with tempfile.TemporaryDirectory() as tmp, \
                patch("src.tw_intraday_update.fetch_all_symbols", return_value=rows), \
                patch("src.tw_intraday_update.fetch_finmind_snapshot", return_value=snapshot), \
                patch("src.tw_intraday_update.latest_reports", return_value=(date(2026, 9, 14), Mock())), \
                patch("src.tw_intraday_update.selected_history", return_value=history), \
                patch("src.tw_intraday_update.signal", return_value=metrics):
            job = IntradayUpdater(tmp, token="secret", now=datetime(2026, 9, 15, 12, 0))
            job.run()
            self.assertEqual(job.status()["status"], "complete")
            folder = Path(job.status()["data_dir"])
            result = json.loads((folder / "screening_results.json").read_text(encoding="utf-8"))
            self.assertTrue(result["is_intraday"])
            self.assertEqual(result["min_volume_lots"], 1300)
            published = result["matches"][0]
            for field in ("open", "high", "low", "close", "total_volume", "volume_lots", "ma"):
                self.assertNotIn(field, published)
            closed = pd.read_parquet(folder / "2330_D1.parquet")
            self.assertEqual(len(closed), 70)
            self.assertEqual(pd.to_datetime(closed.time.iloc[-1], unit="s").date(), date(2026, 9, 14))

    def test_stale_snapshot_does_not_publish(self):
        rows = [{"code": "2330", "name": "台積電", "market": "listed"},
                {"code": "8069", "name": "元太", "market": "otc"}]
        snapshot = pd.DataFrame([{
            "code": "2330", "quote_time": pd.Timestamp("2026-09-14 13:30:00"),
            "open": 100., "high": 103., "low": 99., "close": 102., "total_volume": 2000.,
        }])
        with tempfile.TemporaryDirectory() as tmp, \
                patch("src.tw_intraday_update.fetch_all_symbols", return_value=rows), \
                patch("src.tw_intraday_update.fetch_finmind_snapshot", return_value=snapshot):
            job = IntradayUpdater(tmp, token="secret", now=datetime(2026, 9, 15, 12, 0))
            job.run()
            self.assertEqual(job.status()["status"], "error")
            self.assertIn("不是今天", job.status()["error"])

if __name__ == "__main__":
    unittest.main()
