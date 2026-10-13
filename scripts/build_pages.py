"""Build a self-contained public snapshot; never publish local paths or logs."""
import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.tw_daily_update import DailyUpdater
from src.tw_intraday_update import IntradayUpdater
from scripts.screen_tw_pullback import MIN_VOLUME_LOTS, SCREENING
from src.pages_analysis import analyze_stock, composite_indicator_score
from src.tw_official_data import institutional_history


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
    screen_keys = ('matches', 'waiting_matches', 'bull_confirmation_matches', 'consolidation_breakout_matches')
    stocks = [stock for key in screen_keys for stock in result.get(key, [])]
    unique_stocks = list({stock['code']: stock for stock in stocks}.values())
    stock_analysis = {}
    for stock in unique_stocks:
        code = stock['code']
        if not (code.isdigit() and len(code) == 4):
            raise ValueError('Invalid stock code')
        frame = pd.read_parquet(snapshot / f'{code}_D1.parquet').sort_values('time')
        try:
            stock['analysis'] = analyze_stock(snapshot, code)
        except Exception as exc:
            stock['analysis'] = {'error': f'分析失敗（{type(exc).__name__}）', 'zones': []}
        stock_analysis[code] = stock['analysis']
        frame['date'] = pd.to_datetime(frame.time, unit='s').dt.strftime('%Y-%m-%d')
        candles[code] = frame[['date', 'open', 'high', 'low', 'close', 'tick_volume']].to_dict('records')
        intraday_bar = stock.get('intraday_bar') if result.get('is_intraday') else None
        if intraday_bar:
            candles[code].append({
                'date': intraday_bar['date'], 'as_of': intraday_bar['as_of'],
                'open': intraday_bar['open'], 'high': intraday_bar['high'],
                'low': intraday_bar['low'], 'close': intraday_bar['close'],
                'tick_volume': intraday_bar.get('tick_volume'), 'is_partial': True,
            })
        shutil.copy2(snapshot / f'{code}_D1.csv', downloads / f'{code}_D1.csv')
    completed_days = {pd.to_datetime(bar['date']).date() for bars in candles.values()
                      for bar in bars if not bar.get('is_partial')}
    flows = institutional_history(unique_stocks, completed_days)
    for stock in stocks:
        stock['analysis'] = dict(stock_analysis[stock['code']])
        rows = flows[flows.code == stock['code']]
        stock['institutional_flows'] = [
            {'date': str(row.date), 'foreign_lots': round(float(row.foreign_net) / 1000, 3),
             'trust_lots': round(float(row.trust_net) / 1000, 3),
             'dealer_lots': round(float(row.dealer_net) / 1000, 3),
             'net_lots': round(float(row.total_net) / 1000, 3)}
            for row in rows.itertuples(index=False)
        ]
        stock['analysis']['composite_score'] = composite_indicator_score(stock, stock['analysis'])
    archive = snapshot / f"tw_stock_{result['date']}_{MIN_VOLUME_LOTS}lots.zip"
    shutil.copy2(archive, downloads / 'stocks.zip')
    confirmed_codes = {s['code'] for s in result['matches']}
    list_types = {stock['code']: [key for key in screen_keys
                  if any(item['code'] == stock['code'] for item in result.get(key, []))]
                  for stock in unique_stocks}
    analysis = [{'code': s['code'], 'name': s['name'],
                 'list_type': ('confirmed' if s['code'] in confirmed_codes else
                               'waiting' if 'waiting_matches' in list_types[s['code']] else
                               'bull_confirmation' if 'bull_confirmation_matches' in list_types[s['code']] else
                               'consolidation_breakout'),
                 'all_lists': list_types[s['code']],
                 'rising_stage': s.get('rising_stage'),
                 'rising_stage_reason': s.get('rising_stage_reason'),
                 'kd_golden_cross': s.get('kd_golden_cross'),
                 'macd_red_bar': s.get('macd_red_bar'),
                 'above_ma5': s.get('above_ma5'),
                 'reclaimed_previous_high': s.get('reclaimed_previous_high'),
                 'entry_volume_met': s.get('entry_volume_met'),
                 'kd_entry_signal': s.get('kd_entry_signal'),
                 'macd_entry_signal': s.get('macd_entry_signal'),
                 **s['analysis']} for s in unique_stocks]
    (downloads / 'analysis.json').write_text(json.dumps(analysis, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    fields = ['code', 'name', 'list_type', 'rising_stage', 'rising_stage_reason',
              'kd_golden_cross', 'macd_red_bar', 'above_ma5', 'reclaimed_previous_high',
              'entry_volume_met', 'kd_entry_signal', 'macd_entry_signal',
              'current_price', 'change_pct',
              'composite_score', 'p_touch', 'p_hold', 'n_events', 'trend_label',
              'nearest_distance_atr', 'nearest_support', 'nearest_resistance', 'n_zones', 'error']
    pd.DataFrame(analysis).reindex(columns=fields).to_csv(downloads / 'analysis.csv', index=False, encoding='utf-8-sig')
    with zipfile.ZipFile(downloads / 'stocks.zip', 'a', zipfile.ZIP_DEFLATED) as bundle:
        for name in ('analysis.json', 'analysis.csv'):
            bundle.write(downloads / name, name)
    for name in ('tw_stock_symbols.csv', 'fetch_errors.csv'):
        shutil.copy2(snapshot / name, downloads / name)
    payload = {**result, 'source': source, 'candles': candles,
               'institutional_status': flows.attrs.get('status', 'unavailable'),
               'built_at': datetime.now(timezone.utc).isoformat()}
    # JSON lives in a separate script, so file:// previews need no fetch/server.
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
    (destination / 'data.js').write_text('window.STOCK_DATA = ' + encoded + ';\n', encoding='utf-8')
    index = destination / 'index.html'
    index.write_text(index.read_text(encoding='utf-8').replace('__BUILD__', datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')), encoding='utf-8')
    (destination / '.nojekyll').touch()
    print(f"Built {result['date']}: {len(result['matches'])} confirmed, "
          f"{len(result.get('waiting_matches', []))} waiting")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--snapshot', type=Path, help='Explicit existing snapshot for local preview only')
    parser.add_argument('--output', type=Path, default=ROOT / '_site')
    parser.add_argument('--mode', choices=('daily', 'intraday'), default='daily',
                        help='daily: completed market report; intraday: TWSE MIS noon screen')
    args = parser.parse_args()
    if args.snapshot:
        build(args.snapshot, args.output)
    else:
        with tempfile.TemporaryDirectory() as tmp:
            job = IntradayUpdater(tmp) if args.mode == 'intraday' else DailyUpdater(tmp, lambda _: None)
            job.run()
            state = job.status()
            if state['status'] != 'complete':
                raise RuntimeError(state.get('error', 'Daily update failed'))
            build(state['data_dir'], args.output)


if __name__ == '__main__':
    main()
