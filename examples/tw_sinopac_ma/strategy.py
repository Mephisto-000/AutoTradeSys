# Strategy: 0050 60 分 K 均線交叉(永豐金 Shioaji 資料)
# Type:     A (single symbol, signal-based)
# Symbol:   0050 (元大台灣50)
# Market:   spot — 現股,不放空;實盤由永豐金自動下單(references/sinopac-broker.md)
# Interval: 60m
# Data:     lib/sinopac_data.fetch_sinopac_kbars — SinoPac 1-minute kbars (2020-03-02 on),
#           adjusted by the exchanges' own 除權息 events; needs the sinopac_* keys in .env
# (AutoTradeSys fork example, 2026-10-25)

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# At the top, not inside fetch_data: importing it registers the fetcher in lib.data, and
# lib/runner's look-ahead check only follows a fetcher registered before fetch_data runs
from lib.sinopac_data import fetch_sinopac_kbars  # noqa: E402

# ── Config ────────────────────────────────────────────────────────────────────
STRATEGY_NAME = "tw_sinopac_ma"
DISPLAY_NAME  = "0050 60分K 均線交叉(永豐資料)"
DESCRIPTION   = "用永豐金的 60 分 K,0050 快線站上慢線就買進、跌破就賣出,只做多"
VERSION_NOTE  = ""
LOGIC = """
entry: 5 根 60 分 K 均線向上穿越 20 根均線時買進 0050
exit: 5 根均線向下穿越 20 根均線時全部賣出
"""
SYMBOL        = "0050"
MARKET        = "spot"            # 台股現股:只做多
INTERVAL      = "60m"
START         = "2021-01-01"
END           = None
FEE           = 0.003             # 單邊(per side):台股 ETF 預設 0.3%,已含手續費、ETF 證交稅、價差(references/trading-costs.md)

SMA_FAST = 5
SMA_SLOW = 20
WARMUP   = SMA_SLOW

PLOT_SERIES = {"SMA 5": ("SMA_F", {"overlay": True}), "SMA 20": ("SMA_S", {"overlay": True})}


# ── indicators ────────────────────────────────────────────────────────────────
def _add_indicators(df, fast=SMA_FAST, slow=SMA_SLOW):
    df = df.copy()
    df['SMA_F'] = df['Close'].rolling(fast).mean()
    df['SMA_S'] = df['Close'].rolling(slow).mean()
    return df


# ── fetch_data ────────────────────────────────────────────────────────────────
def fetch_data(hdrs):
    # adjust=True: 除權息 days do not show up as fake drops (volume is never adjusted)
    df = fetch_sinopac_kbars(SYMBOL, INTERVAL, START, END, adjust=True)
    return _add_indicators(df)


# ── compute_signals ───────────────────────────────────────────────────────────
def compute_signals(df, fast=SMA_FAST, slow=SMA_SLOW):
    import pandas as pd, numpy as np
    df = _add_indicators(df, fast, slow)
    f, s  = df['SMA_F'], df['SMA_S']
    golden = (f > s) & (f.shift(1) <= s.shift(1))
    death  = (f < s) & (f.shift(1) >= s.shift(1))
    signal = pd.Series(np.nan, index=df.index)
    signal[golden] = 1.0
    signal[death]  = 0.0
    # Seed the state on the bars before the first cross (one seeded bar is dropped with WARMUP).
    pre = signal.ffill().isna() & f.notna() & s.notna()
    signal[pre] = (f > s)[pre].astype(float)
    return signal.clip(lower=0.0)   # spot cannot short — live clamps to flat, so must the backtest


if __name__ == '__main__':
    from lib.runner import run
    from lib.notify import make_sender
    run(locals(), fetch_data, compute_signals, make_sender())
