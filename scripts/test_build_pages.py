import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from scripts.build_pages import build
from scripts.screen_tw_pullback import SCREENING
from src.pages_analysis import analyze_stock
from src.sr_engine import SREngine, build_summary
from src.local_data_loader import load_kline


class AnalysisTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'close': [100.] * 64 + [105.], 'pct_chg': [0.] * 64 + [5.]})

    def test_absent_levels_preserve_nulls(self):
        with patch('src.pages_analysis.load_kline', return_value=self.frame()), patch('src.pages_analysis.SREngine') as engine:
            engine.return_value.detect.return_value = ([], {'prob_ready': False})
            result = analyze_stock('unused', '2338')
        self.assertEqual(result['change_pct'], 5.)
        self.assertEqual(result['n_zones'], 0)
        for key in ('p_touch', 'p_hold', 'n_events', 'nearest_distance_atr', 'nearest_support', 'nearest_resistance'):
            self.assertIsNone(result[key])

    def test_same_engine_and_nearest_support_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            closes = [100 + i * 0.15 + (i % 12 - 6) * 0.6 for i in range(123)]
            pd.DataFrame({'time': [1790208000 + i * 86400 for i in range(123)],
                          'open': closes, 'high': [c+1 for c in closes], 'low': [c-1 for c in closes],
                          'close': closes, 'tick_volume': 2000000}).to_parquet(path / '2338_D1.parquet')
            df = load_kline(str(path), '2338', 'D1')
            zones, info = SREngine(n_zones=6).detect(df, '2338')
            nearest = build_summary(zones, df, 'long', info).get('nearest') or {}
            actual = analyze_stock(path, '2338')
            self.assertNotIn('error', actual)
            self.assertEqual(actual['n_zones'], len(zones))
            self.assertEqual(actual['p_touch'], nearest.get('p_touch'))
            self.assertEqual(actual['p_hold'], nearest.get('p_hold'))
            self.assertEqual(actual['n_events'], nearest.get('n_events'))
            self.assertEqual(actual['nearest_distance_atr'], nearest.get('distance_atr'))
            self.assertEqual(actual['change_pct'], round((closes[-1]/closes[-2]-1)*100, 2))


class PagesTests(unittest.TestCase):
    def test_intraday_workflow_retries_transient_failures(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'daily-pages.yml').read_text(encoding='utf-8')
        self.assertEqual(workflow.count('for attempt in 1 2 3'), 2)
        self.assertIn('python -u scripts/build_pages.py --mode intraday', workflow)
        self.assertIn('python -u scripts/build_pages.py --mode daily', workflow)
        self.assertEqual(workflow.count('sleep "$delay"'), 2)

    def snapshot(self, path, matches, waiting=None, is_intraday=False):
        result = {'date': '2026-09-24', 'screening': SCREENING, 'matches': matches,
                  'waiting_matches': waiting or []}
        if is_intraday:
            result['is_intraday'] = True
        (path / 'screening_results.json').write_text(json.dumps(result), encoding='utf-8')
        (path / 'source.json').write_text('{}', encoding='utf-8')
        for name in ('tw_stock_symbols.csv', 'fetch_errors.csv'):
            (path / name).write_text('code,name\n', encoding='utf-8')
        with zipfile.ZipFile(path / 'tw_stock_2026-09-24_1500lots.zip', 'w') as bundle:
            bundle.writestr('source.json', '{}')

    def test_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.snapshot(path, [])
            build(path, path / 'site')
            self.assertTrue((path / 'site/index.html').exists())
            self.assertTrue((path / 'site/downloads/stocks.zip').exists())
            with zipfile.ZipFile(path / 'site/downloads/stocks.zip') as bundle:
                self.assertEqual(json.loads(bundle.read('analysis.json')), [])
                self.assertIn('p_touch', bundle.read('analysis.csv').decode('utf-8-sig'))
            text = (path / 'site/data.js').read_text(encoding='utf-8')
            self.assertNotIn(str(path), text)
            self.assertIn('"matches": []', text)

    def test_candles_and_escaped_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.snapshot(path, [{'code': '2338', 'name': '</script>'}])
            pd.DataFrame([{'time': 1790208000, 'open': 46.3, 'high': 47.45,
                           'low': 46.05, 'close': 47.1, 'tick_volume': 4013030}]).to_parquet(path / '2338_D1.parquet')
            (path / '2338_D1.csv').write_text('date,close\n2026-09-24,47.1', encoding='utf-8')
            flows = pd.DataFrame([{'date': pd.Timestamp('2026-09-24').date(), 'code': '2338',
                                   'market': 'listed', 'foreign_net': 500000, 'trust_net': 150000,
                                   'dealer_net': 100000, 'total_net': 750000}])
            flows.attrs['status'] = 'available'
            with patch('scripts.build_pages.institutional_history', return_value=flows):
                build(path, path / 'site')
            text = (path / 'site/data.js').read_text(encoding='utf-8')
            self.assertNotIn('</script>', text)
            self.assertIn('2026-09-24', text)
            self.assertIn('"institutional_status": "available"', text)
            self.assertIn('"net_lots": 750.0', text)
            self.assertTrue((path / 'site/downloads/2338_D1.csv').exists())
            analysis = json.loads((path / 'site/downloads/analysis.json').read_text(encoding='utf-8'))
            self.assertIn('error', analysis[0])

    def test_waiting_snapshot_is_published_with_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.snapshot(path, [], [{'code': '2338', 'name': '等待股',
                                      'red_k_confirmed': False}])
            pd.DataFrame([{'time': 1790208000, 'open': 46.3, 'high': 47.45,
                           'low': 46.05, 'close': 46.1, 'tick_volume': 4013030}]).to_parquet(
                               path / '2338_D1.parquet')
            (path / '2338_D1.csv').write_text('date,close\n2026-09-24,46.1', encoding='utf-8')
            build(path, path / 'site')
            text = (path / 'site/data.js').read_text(encoding='utf-8')
            self.assertIn('"waiting_matches": [{', text)
            analysis = json.loads((path / 'site/downloads/analysis.json').read_text(encoding='utf-8'))
            self.assertEqual(analysis[0]['list_type'], 'waiting')
            self.assertTrue((path / 'site/downloads/2338_D1.csv').exists())

    def test_intraday_temporary_candle_is_appended_to_public_chart_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            stock = {'code': '2338', 'name': '台股', 'intraday_bar': {
                'date': '2026-09-25', 'as_of': '2026-09-25T11:30:00',
                'open': 47.1, 'high': 48.2, 'low': 46.8, 'close': 47.9,
                'tick_volume': 5500000,
                'is_partial': True,
            }}
            self.snapshot(path, [stock], is_intraday=True)
            pd.DataFrame([{'time': 1790208000, 'open': 46.3, 'high': 47.45,
                           'low': 46.05, 'close': 47.1, 'tick_volume': 4013030}]).to_parquet(
                               path / '2338_D1.parquet')
            (path / '2338_D1.csv').write_text('date,close\n2026-09-24,47.1', encoding='utf-8')
            build(path, path / 'site')
            text = (path / 'site/data.js').read_text(encoding='utf-8')
            self.assertIn('"date": "2026-09-25"', text)
            self.assertIn('"is_partial": true', text)
            self.assertIn('"tick_volume": 5500000', text)
            self.assertEqual(len(pd.read_parquet(path / '2338_D1.parquet')), 1)

    def test_old_screening_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'screening_results.json').write_text('{"screening":"old"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                build(path, path / 'site')
