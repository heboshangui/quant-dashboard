"""
A 股量化分析工具 - 主应用
面向纯新手，技术面 + 基本面一起看
"""

from flask import Flask, render_template, jsonify, request
import pandas as pd
import numpy as np
import akshare as ak
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False

# 默认自选股
DEFAULT_STOCKS = [
    {"code": "002119", "market": "sz", "name": "康强电子"},
    {"code": "600602", "market": "sh", "name": "云赛智联"},
    {"code": "600629", "market": "sh", "name": "华建集团"},
]


# ──────────────────────────────── 工具函数 ────────────────────────────────

def get_stock_code(stock):
    """拼接股票代码：sz002119 / sh600602"""
    return f"{stock['market']}{stock['code']}"


def safe_ak(func, *args, **kwargs):
    """安全调用 akshare，失败返回 None"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        print(f"[WARN] {func.__name__} failed: {e}")
        return None


# ──────────────────────────────── 数据获取 ────────────────────────────────

def fetch_realtime(code_with_market):
    """获取实时行情"""
    try:
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code_with_market[2:]]
        if row.empty:
            return None
        r = row.iloc[0]
        return {
            "price":      round(float(r['最新价']) if pd.notna(r['最新价']) else 0, 2),
            "change_pct": round(float(r['涨跌幅']) if pd.notna(r['涨跌幅']) else 0, 2),
            "volume":     int(r['成交量']) if pd.notna(r['成交量']) else 0,
            "amount":     round(float(r['成交额']) / 1e8, 2) if pd.notna(r['成交额']) else 0,
        }
    except Exception as e:
        print(f"[WARN] fetch_realtime {code_with_market}: {e}")
        return None


def fetch_fundamental(code_with_market):
    """获取基本面数据：PE、PB、市值、营收增速"""
    try:
        # 使用 akshare 实时行情获取 PE、PB、总市值
        df = ak.stock_zh_a_spot_em()
        row = df[df['代码'] == code_with_market[2:]]
        if row.empty:
            return None
        r = row.iloc[0]

        pe = float(r['市盈率-动态']) if pd.notna(r.get('市盈率-动态')) else None
        pb = float(r['市净率']) if pd.notna(r.get('市净率')) else None
        total_mv = round(float(r['总市值']) / 1e8, 2) if pd.notna(r.get('总市值')) else None
        float_mv = round(float(r['流通市值']) / 1e8, 2) if pd.notna(r.get('流通市值')) else None

        # 营收增速：从财务数据中取
        rev_growth = safe_ak(_get_revenue_growth, code_with_market)

        return {
            "pe":         round(pe, 2) if pe else None,
            "pb":         round(pb, 2) if pb else None,
            "total_mv":   total_mv,   # 亿元
            "float_mv":   float_mv,   # 亿元
            "rev_growth": rev_growth, # %
        }
    except Exception as e:
        print(f"[WARN] fetch_fundamental {code_with_market}: {e}")
        return None


def _get_revenue_growth(code_with_market):
    """获取营收增速（近一年）"""
    try:
        df = ak.stock_financial_analysis_indicator(symbol="全部", start_year=str(datetime.now().year-1))
        if df is None or df.empty:
            return None
        # 找营收增长率列
        possible_cols = [c for c in df.columns if '营收' in c or '收入' in c]
        if not possible_cols:
            return None
        col = possible_cols[0]
        val = df[col].dropna().iloc[0] if not df[col].dropna().empty else None
        return round(val, 2) if val else None
    except:
        return None


def fetch_history(code_with_market, days=120):
    """获取日线历史数据（用于计算技术指标）"""
    try:
        end = datetime.today().strftime('%Y%m%d')
        start = (datetime.today() - timedelta(days=days)).strftime('%Y%m%d')
        df = ak.stock_zh_a_hist(
            symbol=code_with_market[2:],
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq"
        )
        if df is None or df.empty:
            return None
        df = df.sort_values('日期')
        df.columns = [c.strip() for c in df.columns]
        return df
    except Exception as e:
        print(f"[WARN] fetch_history {code_with_market}: {e}")
        return None


# ──────────────────────────────── 技术指标计算 ────────────────────────────────

def calc_ma(prices, n):
    """简单移动平均"""
    return prices.rolling(n).mean()


def calc_ema(prices, n):
    """指数移动平均"""
    return prices.ewm(span=n, adjust=False).mean()


def calc_macd(prices, fast=12, slow=26, signal=9):
    """MACD = DIF - DEA"""
    ema_fast = calc_ema(prices, fast)
    ema_slow = calc_ema(prices, slow)
    dif = ema_fast - ema_slow
    dea = calc_ema(dif, signal)
    macd_hist = (dif - dea) * 2  # 柱状图放大2倍
    return dif, dea, macd_hist


def calc_kdj(high, low, close, n=9, m1=3, m2=3):
    """KDJ 指标"""
    lowest_low = low.rolling(n).min()
    highest_high = high.rolling(n).max()
    rsv = (close - lowest_low) / (highest_high - lowest_low + 1e-9) * 100
    K = rsv.ewm(com=m1-1, adjust=False).mean()
    D = K.ewm(com=m2-1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J


def calc_rsi(prices, n=14):
    """RSI 相对强弱指数"""
    delta = prices.diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1/n, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/n, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calc_indicators(df):
    """计算完整技术指标"""
    close = df['收盘']
    high  = df['最高']
    low   = df['最低']
    open_ = df['开盘']

    dif, dea, macd_hist = calc_macd(close)
    K, D, J = calc_kdj(high, low, close)
    rsi = calc_rsi(close)
    ma5  = calc_ma(close, 5)
    ma10 = calc_ma(close, 10)
    ma20 = calc_ma(close, 20)

    return {
        "dif":     dif,
        "dea":     dea,
        "macd_hist": macd_hist,
        "K":       K,
        "D":       D,
        "J":       J,
        "rsi":     rsi,
        "ma5":     ma5,
        "ma10":    ma10,
        "ma20":    ma20,
    }


def get_latest_signals(df, indicators):
    """从最新数据中提取信号"""
    if df is None or df.empty or len(df) < 30:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = last['收盘']
    ma5  = indicators['ma5'].iloc[-1]
    ma10 = indicators['ma10'].iloc[-1]
    ma20 = indicators['ma20'].iloc[-1]

    dif  = indicators['dif'].iloc[-1]
    dea  = indicators['dea'].iloc[-1]
    macd_hist_prev = indicators['macd_hist'].iloc[-2]
    macd_hist_curr = indicators['macd_hist'].iloc[-1]

    K = indicators['K'].iloc[-1]
    D = indicators['D'].iloc[-1]
    K_prev = indicators['K'].iloc[-2]
    D_prev = indicators['D'].iloc[-2]

    rsi = indicators['rsi'].iloc[-1]

    # MACD 金叉：DIF 从下方穿越 DEA
    macd_golden = (dif > dea) and (prev['收盘'] - prev['开盘()'] < dif - dea)  # 简化判断

    # 更准确的金叉判断：前一根 DIF <= DEA，当前 DIF > DEA
    dif_series = indicators['dif']
    dea_series = indicators['dea']
    macd_golden = (dea_series.iloc[-2] >= dif_series.iloc[-2]) and (dea_series.iloc[-1] < dif_series.iloc[-1])

    # KDJ 金叉：K 从下方穿越 D
    kdj_golden = (K_prev < D_prev) and (K > D)
    # KDJ 死叉：K 从上方穿越 D
    kdj_dead   = (K_prev > D_prev) and (K < D)

    # 均线多头排列：MA5 > MA10 > MA20
    ma_bullish = (ma5 > ma10) and (ma10 > ma20)
    # 均线空头排列
    ma_bearish = (ma5 < ma10) and (ma10 < ma20)

    # MACD 柱状图方向
    macd_bullish = macd_hist_curr > macd_hist_prev
    macd_value   = round(macd_hist_curr, 4)

    # RSI
    rsi_value = round(rsi, 2)

    # 综合信号评分（0-4）
    score = 0
    if macd_golden:  score += 1
    if kdj_golden:   score += 1
    if ma_bullish:   score += 1
    if rsi < 70:     score += 1  # RSI 不在超买区

    signal_map = {
        0: "观望",
        1: "观望",
        2: "谨慎",
        3: "关注",
        4: "看好",
    }
    overall = signal_map.get(score, "观望")

    return {
        "macd_golden":  bool(macd_golden),
        "kdj_golden":   bool(kdj_golden),
        "kdj_dead":     bool(kdj_dead),
        "ma_bullish":   bool(ma_bullish),
        "ma_bearish":   bool(ma_bearish),
        "macd_bullish": bool(macd_bullish),
        "macd_value":   macd_value,
        "rsi":          rsi_value,
        "overall":      overall,
        "score":        score,
        "close":        round(float(close), 2),
        "ma5":          round(float(ma5), 2),
        "ma10":         round(float(ma10), 2),
        "ma20":         round(float(ma20), 2),
    }


def get_price_breakout(df):
    """判断是否突破年高 / 半年高"""
    if df is None or len(df) < 250:
        return {"year_high": False, "half_year_high": False}

    close = df['收盘']

    # 年高：250日最高
    year_high = close.iloc[-1] >= close.iloc[-250:].max()

    # 半年高：120日最高
    half_year_high = close.iloc[-1] >= close.iloc[-120:].max()

    return {
        "year_high":     bool(year_high),
        "half_year_high": bool(half_year_high),
    }


# ──────────────────────────────── Flask 路由 ────────────────────────────────

@app.route('/')
def index():
    """自选股仪表盘首页"""
    return render_template('dashboard.html', stocks=DEFAULT_STOCKS)


@app.route('/api/dashboard')
def api_dashboard():
    """API：获取所有自选股数据"""
    results = []

    for stock in DEFAULT_STOCKS:
        code = get_stock_code(stock)
        realtime = fetch_realtime(code)
        fundamental = fetch_fundamental(code)
        df = fetch_history(code, days=300)
        indicators = calc_indicators(df) if df is not None else None
        signals = get_latest_signals(df, indicators) if indicators is not None else None
        breakout = get_price_breakout(df) if df is not None else None

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
    """API：获取单只股票详情"""
    code_with_market = f"{market}{code}"
    realtime = fetch_realtime(code_with_market)
    fundamental = fetch_fundamental(code_with_market)
    df = fetch_history(code_with_market, days=300)
    indicators = calc_indicators(df) if df is not None else None
    signals = get_latest_signals(df, indicators) if indicators is not None else None
    breakout = get_price_breakout(df) if df is not None else None

    return jsonify({
        "code": 0,
        "data": {
            "realtime":    realtime,
            "fundamental": fundamental,
            "signals":     signals,
            "breakout":    breakout,
        }
    })


@app.route('/selector')
def selector():
    """选股器页面"""
    return render_template('selector.html')


@app.route('/api/selector')
def api_selector():
    """API：选股筛选"""
    filter_type = request.args.get('filter', 'limit_up')  # 默认筛选涨停股
    limit = min(int(request.args.get('limit', 20)), 20)

    results = []

    try:
        if filter_type == 'limit_up':
            # 涨停股
            df = ak.stock_zh_a_spot_em()
            df = df[df['涨跌幅'] >= 9.9]
            df = df.head(limit)
            for _, row in df.iterrows():
                code = str(row['代码'])
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                results.append({
                    "name":        row['名称'],
                    "code":        f"{market}{code}",
                    "price":       round(float(row['最新价']), 2),
                    "change_pct":  round(float(row['涨跌幅']), 2),
                    "volume":      int(row['成交量']),
                    "reason":      "今日涨停",
                })

        elif filter_type == 'year_high':
            # 突破年高
            df = ak.stock_zh_a_spot_em()
            # 取成交额前100的股票
            df = df.sort_values('成交额', ascending=False).head(100)
            for _, row in df.iterrows():
                code = str(row['代码'])
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full_code = f"{market}{code}"
                hist = fetch_history(full_code, days=300)
                if hist is None or len(hist) < 250:
                    continue
                close = hist['收盘']
                if close.iloc[-1] >= close.iloc[-250:].max():
                    results.append({
                        "name":       row['名称'],
                        "code":       full_code,
                        "price":      round(float(row['最新价']), 2),
                        "change_pct": round(float(row['涨跌幅']), 2),
                        "reason":     "突破年高",
                    })
                    if len(results) >= limit:
                        break

        elif filter_type == 'macd_golden':
            # MACD 金叉
            df = ak.stock_zh_a_spot_em()
            df = df.sort_values('成交额', ascending=False).head(80)
            for _, row in df.iterrows():
                code = str(row['代码'])
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full_code = f"{market}{code}"
                hist = fetch_history(full_code, days=300)
                if hist is None or len(hist) < 35:
                    continue
                ind = calc_indicators(hist)
                dif = ind['dif']
                dea = ind['dea']
                if (dea.iloc[-2] >= dif.iloc[-2]) and (dea.iloc[-1] < dif.iloc[-1]):
                    results.append({
                        "name":       row['名称'],
                        "code":       full_code,
                        "price":      round(float(row['最新价']), 2),
                        "change_pct": round(float(row['涨跌幅']), 2),
                        "reason":     "MACD 金叉",
                    })
                    if len(results) >= limit:
                        break

        elif filter_type == 'kdj_golden':
            # KDJ 金叉
            df = ak.stock_zh_a_spot_em()
            df = df.sort_values('成交额', ascending=False).head(80)
            for _, row in df.iterrows():
                code = str(row['代码'])
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full_code = f"{market}{code}"
                hist = fetch_history(full_code, days=300)
                if hist is None or len(hist) < 35:
                    continue
                ind = calc_indicators(hist)
                K, D = ind['K'].iloc[-1], ind['D'].iloc[-1]
                K_p, D_p = ind['K'].iloc[-2], ind['D'].iloc[-2]
                if (K_p < D_p) and (K > D):
                    results.append({
                        "name":       row['名称'],
                        "code":       full_code,
                        "price":      round(float(row['最新价']), 2),
                        "change_pct": round(float(row['涨跌幅']), 2),
                        "reason":     "KDJ 金叉",
                    })
                    if len(results) >= limit:
                        break

        elif filter_type == 'ma_bullish':
            # 均线多头排列
            df = ak.stock_zh_a_spot_em()
            df = df.sort_values('成交额', ascending=False).head(80)
            for _, row in df.iterrows():
                code = str(row['代码'])
                market = 'sz' if code.startswith(('0', '3')) else 'sh'
                full_code = f"{market}{code}"
                hist = fetch_history(full_code, days=250)
                if hist is None or len(hist) < 25:
                    continue
                ind = calc_indicators(hist)
                ma5, ma10, ma20 = ind['ma5'].iloc[-1], ind['ma10'].iloc[-1], ind['ma20'].iloc[-1]
                if (ma5 > ma10) and (ma10 > ma20):
                    results.append({
                        "name":       row['名称'],
                        "code":       full_code,
                        "price":      round(float(row['最新价']), 2),
                        "change_pct": round(float(row['涨跌幅']), 2),
                        "reason":     "均线多头排列",
                    })
                    if len(results) >= limit:
                        break

    except Exception as e:
        print(f"[ERROR] selector {filter_type}: {e}")

    return jsonify({"code": 0, "filter": filter_type, "count": len(results), "data": results})


@app.route('/learn')
def learn():
    """新手学院页面"""
    return render_template('learn.html')


@app.route('/api/chart/<market>/<code>')
def api_chart(market, code):
    """API：获取图表数据"""
    code_with_market = f"{market}{code}"
    df = fetch_history(code_with_market, days=300)
    if df is None:
        return jsonify({"code": 1, "msg": "数据获取失败"})

    df = df.tail(120)  # 最近120个交易日
    indicators = calc_indicators(df)

    # K线数据
    ohlc = [
        [str(row['日期']), float(row['开盘']), float(row['收盘']),
         float(row['最低']), float(row['最高'])]
        for _, row in df.iterrows()
    ]

    # 均线数据
    ma_data = {
        "ma5":  [float(v) for v in indicators['ma5'].values],
        "ma10": [float(v) for v in indicators['ma10'].values],
        "ma20": [float(v) for v in indicators['ma20'].values],
    }

    # MACD
    macd_data = {
        "dif":      [float(v) for v in indicators['dif'].values],
        "dea":      [float(v) for v in indicators['dea'].values],
        "hist":     [float(v) * 2 for v in indicators['macd_hist'].values],  # 还原
    }

    # KDJ
    kdj_data = {
        "K": [float(v) for v in indicators['K'].values],
        "D": [float(v) for v in indicators['D'].values],
        "J": [float(v) for v in indicators['J'].values],
    }

    # RSI
    rsi_data = [float(v) for v in indicators['rsi'].values]

    dates = [str(d) for d in df['日期'].values]

    return jsonify({
        "code": 0,
        "dates": dates,
        "ohlc":  ohlc,
        "ma":    ma_data,
        "macd":  macd_data,
        "kdj":   kdj_data,
        "rsi":   rsi_data,
    })


if __name__ == '__main__':
    print("=" * 50)
    print("  📊 A股量化分析工具已启动")
    print("  🌐 访问 http://127.0.0.1:5001")
    print("  📖 新手学院： http://127.0.0.1:5001/learn")
    print("  🔍 选股器：  http://127.0.0.1:5001/selector")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=False)
