"""Static-site adapter for the same SR engine used by /api/analyze_all."""
from src.local_data_loader import load_kline
from src.sr_engine import SREngine, build_summary


def analyze_stock(folder, code):
    df = load_kline(str(folder), code, 'D1')
    if len(df) < 60:
        return {'error': '有效歷史不足 60 根，無法分析', 'zones': []}
    df.attrs.update(adjust_mode='none', adjust_source='unadjusted')
    zones, info = SREngine(n_zones=6).detect(df, code)
    if info.get('error'):
        return {'error': '支撐壓力分析無法完成', 'zones': []}
    summary = build_summary(zones, df, 'long', info)
    nearest = summary.get('nearest') or {}
    def closest(kind):
        candidates = [z for z in zones if z['zone_type'] == kind]
        return min(candidates, key=lambda z: abs(z['distance_atr'])) if candidates else {}
    support, resistance = closest('support'), closest('resistance')
    return {
        'current_price': round(float(df.close.iloc[-1]), 4),
        'change_pct': round(float(df.pct_chg.iloc[-1]), 2),
        'p_touch': nearest.get('p_touch'), 'p_hold': nearest.get('p_hold'),
        'n_events': nearest.get('n_events'), 'n_zones': len(zones),
        'nearest_distance_atr': nearest.get('distance_atr'),
        'nearest_distance_pct': nearest.get('distance_pct'),
        'nearest_support': support.get('center'),
        'nearest_resistance': resistance.get('center'),
        'trend_label': {'上涨': '上漲', '震荡': '震盪', '下跌': '下跌'}.get(summary['trend_label'], summary['trend_label']),
        'prob_ready': info.get('prob_ready', False), 'price_basis': 'unadjusted',
        'direction': 'long', 'zones': zones,
    }
