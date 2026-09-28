import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import pandas as pd

from scripts.build_pages import build
from scripts.screen_tw_pullback import SCREENING


class PagesTests(unittest.TestCase):
    def snapshot(self, path, matches):
        result = {'date': '2026-09-24', 'screening': SCREENING, 'matches': matches}
        (path / 'screening_results.json').write_text(json.dumps(result), encoding='utf-8')
        (path / 'source.json').write_text('{}', encoding='utf-8')
        for name in ('tw_stock_symbols.csv', 'fetch_errors.csv'):
            (path / name).write_text('code,name\n', encoding='utf-8')
        with zipfile.ZipFile(path / 'tw_stock_2026-09-24_1300lots.zip', 'w') as bundle:
            bundle.writestr('source.json', '{}')

    def test_empty_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.snapshot(path, [])
            build(path, path / 'site')
            self.assertTrue((path / 'site/index.html').exists())
            self.assertTrue((path / 'site/downloads/stocks.zip').exists())
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
            build(path, path / 'site')
            text = (path / 'site/data.js').read_text(encoding='utf-8')
            self.assertNotIn('</script>', text)
            self.assertIn('2026-09-24', text)
            self.assertTrue((path / 'site/downloads/2338_D1.csv').exists())

    def test_old_screening_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / 'screening_results.json').write_text('{"screening":"old"}', encoding='utf-8')
            with self.assertRaises(ValueError):
                build(path, path / 'site')
