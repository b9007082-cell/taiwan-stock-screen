"""Static-site adapter for the same SR engine used by /api/analyze_all."""
import pandas as pd

from src.local_data_loader import load_kline
from src.sr_engine import SREngine, build_summary


def composite_indicator_score(stock, analysis=None):
    """Return a transparent 0-100 score from the indicators published on Pages."""
    analysis = analysis or {}
    score = 0.0
    reasons = set(stock.get('bullish_reasons') or [])
    score += 10 if 'hhhl' in reasons else 0
    score += 8 if 'ma3' in reasons else 0
    score += 7 if 'ma4' in reasons else 0
    score += 8 if stock.get('kd_golden_cross') else 0
    score += 8 if stock.get('macd_red_bar') else 0
    score += 4 if stock.get('histogram_rising') else 0
    score += 5 if stock.get('red_k_confirmed') else 0
    score += 5 if stock.get('volume_increased') else 0
    score += 5 if stock.get('pullback_volume_contracted') else 0
    score += 5 if stock.get('reclaimed_previous_high') else 0
    score += {'主升段': 10, '初升段': 7, '末升段': 3}.get(stock.get('rising_stage'), 0)
    for key in ('p_touch', 'p_hold'):
        value = analysis.get(key)
        if value is not None:
            score += max(0.0, min(1.0, float(value))) * 7.5
    flows = stock.get('institutional_flows') or []
    if flows:
        score += 5 if float(flows[-1].get('net_lots') or 0) > 0 else 0
        score += 5 if sum(float(row.get('net_lots') or 0) for row in flows[-5:]) > 0 else 0
    return round(score, 1)


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
