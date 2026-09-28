"""Build a self-contained public snapshot; never publish local paths or logs."""
import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tw_daily_update import DailyUpdater
from scripts.screen_tw_pullback import SCREENING


def build(snapshot, destination):
    snapshot, destination = Path(snapshot), Path(destination)
    result = json.loads((snapshot / 'screening_results.json').read_text(encoding='utf-8'))
    if result['screening'] != SCREENING:
        raise ValueError('Snapshot screening version is outdated')
    source = json.loads((snapshot / 'source.json').read_text(encoding='utf-8'))
    destination.mkdir(parents=True, exist_ok=True)
    for asset in (ROOT / 'pages').iterdir():
        if asset.is_file():
            shutil.copy2(asset, destination / asset.name)
        elif asset.is_dir():
            shutil.copytree(asset, destination / asset.name, dirs_exist_ok=True)
    downloads = destination / 'downloads'
    downloads.mkdir(exist_ok=True)
    candles = {}
    for stock in result['matches']:
        code = stock['code']
        if not (code.isdigit() and len(code) == 4):
            raise ValueError('Invalid stock code')
        frame = pd.read_parquet(snapshot / f'{code}_D1.parquet').sort_values('time')
        frame['date'] = pd.to_datetime(frame.time, unit='s').dt.strftime('%Y-%m-%d')
        candles[code] = frame[['date', 'open', 'high', 'low', 'close', 'tick_volume']].to_dict('records')
        shutil.copy2(snapshot / f'{code}_D1.csv', downloads / f'{code}_D1.csv')
    archive = snapshot / f"tw_stock_{result['date']}_1300lots.zip"
    shutil.copy2(archive, downloads / 'stocks.zip')
    for name in ('tw_stock_symbols.csv', 'fetch_errors.csv'):
        shutil.copy2(snapshot / name, downloads / name)
    payload = {**result, 'source': source, 'candles': candles,
               'built_at': datetime.now(timezone.utc).isoformat()}
    # JSON lives in a separate script, so file:// previews need no fetch/server.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    (destination / 'data.js').write_text('window.STOCK_DATA = ' + encoded + ';\n', encoding='utf-8')
    index = destination / 'index.html'
    index.write_text(index.read_text(encoding='utf-8').replace('__BUILD__', datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')), encoding='utf-8')
    (destination / '.nojekyll').touch()
    print(f"Built {result['date']}: {len(result['matches'])} stocks")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, help='Explicit existing snapshot for local preview only')
    parser.add_argument('--output', type=Path, default=ROOT / '_site')
    args = parser.parse_args()
    if args.snapshot:
        build(args.snapshot, args.output)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            job = DailyUpdater(tmp, lambda _: None)
            job.run()
            state = job.status()
            if state['status'] != 'complete':
                raise RuntimeError(state.get('error', 'Daily update failed'))
            build(state['data_dir'], args.output)


if __name__ == '__main__':
    main()
