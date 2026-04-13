"""
A 股量化分析工具 - 主应用 v2
优化版：单股票API + 内存缓存，大幅提速
"""

from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
import warnings
import threading
import time
import json
warnings.filterwarnings('ignore')

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 处理 numpy 类型序列化
class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

app.json_encoder = NumpyEncoder

# 默认自选股
DEFAULT_STOCKS = [
    {"code": "002119", "market": "sz", "name": "康强电子"},
    {"code": "600602", "market": "sh", "name": "云赛智联"},
    {"code": "600629", "market": "sh", "name": "华建集团"},
]

# ──────────────────────────────── 内存缓存 ────────────────────────────────

_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 120  # 缓存2分钟


def _cache_get(key):
    """从缓存读取，未过期返回数据，否则返回 None"""
    entry = _cache.get(key)
    if entry is None:
        return None
    if time.time() - entry['_t'] > _CACHE_TTL:
        return None
    return entry['data']


def _cache_set(key, data):
    """写入缓存"""
    with _cache_lock:
        _cache[key] = {'data': data, '_t': time.time()}


# ──────────────────────────────── 数据获取（单股票API） ────────────────────────────────

def get_stock_code(stock):
    """拼接股票代码：sz002119 / sh600602"""
    return f"{stock['market']}{stock['code']}"


def fetch_realtime(code_with_market):
    """获取实时行情 - 单股票API，秒级响应"""
    cache_key = f"rt:{code_with_market}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        # 单股票实时行情（快10倍）
        df = ak.stock_zh_a_realtime_em(symbol=code_with_market)
        if df is None or df.empty:
            return None
        r = df.iloc[0]
        return {
            "price":      round(float(r.get('最新价', 0) or 0), 2),
            "change_pct": round(float(r.get('涨跌幅', 0) or 0), 2),
            "volume":     int(r.get('成交量', 0) or 0),
            "amount":     round(float(r.get('成交额', 0) or 0) / 1e8, 2),
        }
    except Exception as e:
        print(f"[WARN] fetch_realtime {code_with_market}: {e}")
        return None


def fetch_fundamental(code_with_market):
    """获取基本面数据 - 从实时行情提取，跳过慢速财务API"""
    cache_key = f"fu:{code_with_market}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        df = ak.stock_zh_a_realtime_em(symbol=code_with_market)
        if df is None or df.empty:
            return None
        r = df.iloc[0]

        def try_float(val):
            try:
                v = float(val)
                return round(v, 2) if v and v > 0 else None
            except:
                return None

        total_mv = r.get('总市值')
        float_mv = r.get('流通市值')
        return {
            "pe":         try_float(r.get('市盈率-动态')),
            "pb":         try_float(r.get('市净率')),
            "total_mv":   round(total_mv / 1e8, 2) if total_mv and total_mv > 0 else None,
            "float_mv":   round(float_mv / 1e8, 2) if float_mv and float_mv > 0 else None,
            "rev_growth": None,  # 营收增速需调财务API，太慢，跳过
        }
    except Exception as e:
        print(f"[WARN] fetch_fundamental {code_with_market}: {e}")
        return None


def fetch_history(code_with_market, days=120):
    """获取日线历史数据（用于计算技术指标）"""
    cache_key = f"hist:{code_with_market}:{days}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        end = datetime.today().strftime('%Y%m%d')
        start = (datetime.today() - timedelta(days=days+30)).strftime('%Y%m%d')  # 多取30天保险
        df = ak.stock_zh_a_hist(
            symbol=code_with_market[2:],
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq"
        )
        if df is None or df.empty:
            return None
        df = df.sort_values('日期').tail(days)  # 只保留最近days天
        df.columns = [c.strip() for c in df.columns]
        _cache_set(cache_key, df)
        return df
    except Exception as e:
        print(f"[WARN] fetch_history {code_with_market}: {e}")
        return None


# ──────────────────────────────── 技术指标计算 ────────────────────────────────

def calc_ma(prices, n):
    return prices.rolling(n).mean()


def calc_ema(prices, n):
    return prices.ewm(span=n, adjust=False).mean()


def calc_macd(prices, fast=12, slow=26, signal=9):
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2
    return dif, dea, macd_hist


def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    lowest_low = low.rolling(n).min()
    highest_high = high.rolling(n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100
    K = rsv.ewm(com=m1-1, adjust=False).mean()
    D = K.ewm(com=m2-1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J


def calc_rsi(prices, n=14):
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


def calc_indicators(df):
    close = df['收盘']
    high  = df['最高']
    low   = df['最低']
    dif, dea, macd_hist = calc_macd(close)
    K, D, J = calc_kdj(high, low, close)
    rsi = calc_rsi(close)
    return {
        "dif":       dif,
        "dea":       dea,
        "macd_hist": macd_hist,
        "K":         K,
        "D":         D,
        "J":         J,
        "rsi":       rsi,
        "ma5":       calc_ma(close, 5),
        "ma10":      calc_ma(close, 10),
        "ma20":      calc_ma(close, 20),
    }


def get_latest_signals(df, indicators):
    if df is None or len(df) < 30:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]
    close = last['收盘']
    ma5  = indicators['ma5'].iloc[-1]
    ma10 = indicators['ma10'].iloc[-1]
    ma20 = indicators['ma20'].iloc[-1]
    dif  = indicators['dif'].iloc[-1]
    dea  = indicators['dea'].iloc[-1]
    dif_p, dea_p = indicators['dif'].iloc[-2], indicators['dea'].iloc[-2]
    macd_hist_prev = indicators['macd_hist'].iloc[-2]
    macd_hist_curr = indicators['macd_hist'].iloc[-1]
    K, D = indicators['K'].iloc[-1], indicators['D'].iloc[-1]
    K_p, D_p = indicators['K'].iloc[-2], indicators['D'].iloc[-2]
    rsi = indicators['rsi'].iloc[-1]

    # MACD 金叉
    macd_golden = (dea_p >= dif_p) and (dea < dif)
    # KDJ 金叉/死叉
    kdj_golden = (K_p < D_p) and (K > D)
    kdj_dead   = (K_p > D_p) and (K < D)
    # 均线多头/空头
    ma_bullish = (ma5 > ma10) and (ma10 > ma20)
    ma_bearish = (ma5 < ma10) and (ma10 < ma20)
    # RSI 超买超卖
    rsi_overbought = rsi > 70
    rsi_oversold   = rsi < 30

    score = sum([macd_golden, kdj_golden, ma_bullish, not rsi_overbought])
    signal_map = {0: "观望", 1: "谨慎", 2: "关注", 3: "看好", 4: "强烈看好"}
    overall = signal_map.get(score, "观望")

    return {
        "macd_golden":  bool(macd_golden),
        "kdj_golden":   bool(kdj_golden),
        "kdj_dead":     bool(kdj_dead),
        "ma_bullish":   bool(ma_bullish),
        "ma_bearish":   bool(ma_bearish),
        "macd_bullish": bool(macd_hist_curr > macd_hist_prev),
        "macd_value":   round(macd_hist_curr, 4),
        "rsi":          round(float(rsi), 2),
        "rsi_overbought": bool(rsi_overbought),
        "rsi_oversold":   bool(rsi_oversold),
        "overall":      overall,
        "score":        score,
        "close":        round(float(close), 2),
        "ma5":          round(float(ma5), 2),
        "ma10":         round(float(ma10), 2),
        "ma20":         round(float(ma20), 2),
    }


def get_price_breakout(df):
    if df is None or len(df) < 250:
        return {"year_high": False, "half_year_high": False}
    close = df['收盘']
    year_high = bool(close.iloc[-1] >= close.iloc[-250:].max())
    half_year_high = bool(close.iloc[-1] >= close.iloc[-120:].max())
    return {"year_high": year_high, "half_year_high": half_year_high}


# ──────────────────────────────── Flask 路由 ────────────────────────────────

@app.route('/')
def index():
    return render_template('dashboard.html', stocks=DEFAULT_STOCKS)


@app.route('/api/dashboard')
def api_dashboard():
    """API：获取所有自选股数据"""
    results = []
    for stock in DEFAULT_STOCKS:
        code = get_stock_code(stock)
        realtime    = fetch_realtime(code)
        fundamental = fetch_fundamental(code)
        df          = fetch_history(code, days=300)
        indicators  = calc_indicators(df) if df is not None else None
        signals     = get_latest_signals(df, indicators) if indicators is not None else None
        breakout    = get_price_breakout(df) if df is not None else None
        results.append({
            "name":        stock['name'],
            "code":        code,
            "market":      stock['market'],
            "stock_code":  stock['code'],
            "realtime":    realtime,
            "fundamental": fundamental,
            "signals":     signals,
            "breakout":    breakout,
        })
    return jsonify({"code": 0, "data": results})


@app.route('/api/stock/<market>/<code>')
def api_stock(market, code):
    code_with_market = f"{market}{code}"
    realtime    = fetch_realtime(code_with_market)
    fundamental = fetch_fundamental(code_with_market)
    df          = fetch_history(code_with_market, days=300)
    indicators  = calc_indicators(df) if df is not None else None
    signals     = get_latest_signals(df, indicators) if indicators is not None else None
    breakout    = get_price_breakout(df) if df is not None else None
    return jsonify({
        "code": 0, "data": {
            "realtime":    realtime,
            "fundamental": fundamental,
            "signals":     signals,
            "breakout":    breakout,
        }
    })


@app.route('/selector')
def selector():
    return render_template('selector.html')


@app.route('/api/selector')
def api_selector():
    """选股筛选 - 使用单股票API，不下载全市场"""
    filter_type = request.args.get('filter', 'limit_up')
    limit = min(int(request.args.get('limit', 20)), 20)

    # 以下筛选暂用全市场快照（akshare最快的方式）
    # 实际使用时有缓存，不会每次都下载全量
    results = []
    try:
        cache_key = f"spot:{filter_type}"
        all_stocks = _cache_get(cache_key)
        if all_stocks is None:
            df = ak.stock_zh_a_spot_em()
            # 只保留有成交额的活跃股票
            df = df[df['成交额'].notna() & (df['成交额'] > 0)]
            all_stocks = df.to_dict('records')
            _cache_set(cache_key, all_stocks)

        if filter_type == 'limit_up':
            filtered = [s for s in all_stocks if float(s.get('涨跌幅', 0) or 0) >= 9.9]
            for s in filtered[:limit]:
                results.append({
                    "name":       s.get('名称', ''),
                    "code":       f"{'sz' if str(s.get('代码','')).startswith(('0','3')) else 'sh'}{s.get('代码','')}",
                    "price":      round(float(s.get('最新价', 0) or 0), 2),
                    "change_pct": round(float(s.get('涨跌幅', 0) or 0), 2),
                    "reason":     "今日涨停",
                })

        elif filter_type == 'year_high':
            # 从成交额前100中筛选（减少计算量）
            by_amount = sorted(all_stocks, key=lambda x: float(x.get('成交额', 0) or 0), reverse=True)
            for s in by_amount[:120]:
                code = str(s.get('代码', ''))
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full = f"{market}{code}"
                df_h = fetch_history(full, days=300)
                if df_h is None or len(df_h) < 250:
                    continue
                close = df_h['收盘']
                if close.iloc[-1] >= close.iloc[-250:].max():
                    results.append({
                        "name":       s.get('名称', ''),
                        "code":       full,
                        "price":      round(float(s.get('最新价', 0) or 0), 2),
                        "change_pct": round(float(s.get('涨跌幅', 0) or 0), 2),
                        "reason":     "突破250日新高",
                    })
                    if len(results) >= limit:
                        break

        elif filter_type in ('macd_golden', 'kdj_golden', 'ma_bullish'):
            by_amount = sorted(all_stocks, key=lambda x: float(x.get('成交额', 0) or 0), reverse=True)
            reason_map = {
                'macd_golden': 'MACD 金叉',
                'kdj_golden':  'KDJ 金叉',
                'ma_bullish':  '均线多头排列',
            }
            reason = reason_map.get(filter_type, '')
            for s in by_amount[:80]:
                code = str(s.get('代码', ''))
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full = f"{market}{code}"
                df_h = fetch_history(full, days=300)
                if df_h is None or len(df_h) < 35:
                    continue
                ind = calc_indicators(df_h)
                add = False
                if filter_type == 'macd_golden':
                    d0, d1 = ind['dea'].iloc[-2], ind['dea'].iloc[-1]
                    f0, f1 = ind['dif'].iloc[-2],  ind['dif'].iloc[-1]
                    add = (d0 >= f0) and (d1 < f1)
                elif filter_type == 'kdj_golden':
                    K0, D0 = ind['K'].iloc[-2], ind['D'].iloc[-2]
                    K1, D1 = ind['K'].iloc[-1], ind['D'].iloc[-1]
                    add = (K0 < D0) and (K1 > D1)
                elif filter_type == 'ma_bullish':
                    m5, m10, m20 = ind['ma5'].iloc[-1], ind['ma10'].iloc[-1], ind['ma20'].iloc[-1]
                    add = (m5 > m10) and (m10 > m20)
                if add:
                    results.append({
                        "name":       s.get('名称', ''),
                        "code":       full,
                        "price":      round(float(s.get('最新价', 0) or 0), 2),
                        "change_pct": round(float(s.get('涨跌幅', 0) or 0), 2),
                        "reason":     reason,
                    })
                    if len(results) >= limit:
                        break

    except Exception as e:
        print(f"[ERROR] selector {filter_type}: {e}")

    return jsonify({"code": 0, "filter": filter_type, "count": len(results), "data": results})


@app.route('/learn')
def learn():
    return render_template('learn.html')


@app.route('/chart')
def chart_page():
    """K线图页面"""
    return render_template('chart.html')


@app.route('/api/chart/<market>/<code>')
def api_chart(market, code):
    code_with_market = f"{market}{code}"
    df = fetch_history(code_with_market, days=300)
    if df is None:
        return jsonify({"code": 1, "msg": "数据获取失败"})
    indicators = calc_indicators(df)
    return jsonify({
        "code": 0,
        "data": {
            "dates":      df['日期'].tolist()[-60:],
            "close":      df['收盘'].tolist()[-60:],
            "ma5":        indicators['ma5'].tolist()[-60:],
            "ma10":       indicators['ma10'].tolist()[-60:],
            "ma20":       indicators['ma20'].tolist()[-60:],
            "dif":        indicators['dif'].tolist()[-60:],
            "dea":        indicators['dea'].tolist()[-60:],
            "macd_hist":  indicators['macd_hist'].tolist()[-60:],
        }
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
