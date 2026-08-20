# -*- coding: utf-8 -*-
"""Teknik gosterge hesaplari.

Onemli: referans ortalamalar (hacim ortalamasi, islem hacmi) shift(1) ile
hesaplanir. Aksi halde patlama gunu kendi ortalamasini sisirir ve oran
oldugundan kucuk cikar; ayrica backtest'te nedensellik bozulur.
"""
import numpy as np
import pandas as pd


def sayi(x, alt=0.0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return alt
    return alt if not np.isfinite(v) else v


def zenginlestir(df, endeks_serisi=None, sektor_serisi=None):
    o = df.copy()
    d = o["close"].diff()
    kaz = d.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    kay = (-d.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    o["rsi"] = 100 - 100 / (1 + kaz / kay.replace(0, np.nan))
    o.loc[(kay == 0) & (kaz > 0), "rsi"] = 100.0
    o.loc[(kay == 0) & (kaz == 0), "rsi"] = 50.0

    m = o["close"].ewm(span=12).mean() - o["close"].ewm(span=26).mean()
    o["macd"] = m
    o["macd_sig"] = m.ewm(span=9).mean()
    o["mh"] = o["macd"] - o["macd_sig"]
    o["s20"] = o["close"].rolling(20).mean()
    o["s50"] = o["close"].rolling(50).mean()

    hac_ort = o["volume"].rolling(20).mean().shift(1)
    hac_std = o["volume"].rolling(20).std().shift(1)
    o["vr"] = o["volume"] / hac_ort.replace(0, np.nan)
    o["vz"] = (o["volume"] - hac_ort) / hac_std.replace(0, np.nan)
    o["islem_tl"] = (o["close"] * o["volume"]).rolling(20).mean().shift(1)

    tp = (o["high"] + o["low"] + o["close"]) / 3
    ham = tp * o["volume"]
    poz = ham.where(tp > tp.shift(1), 0.0).rolling(14).sum()
    neg = ham.where(tp < tp.shift(1), 0.0).rolling(14).sum()
    oran = poz / neg.replace(0, np.nan)
    o["mfi"] = 100 - 100 / (1 + oran)
    o.loc[(neg == 0) & (poz > 0), "mfi"] = 100.0

    aralik = (o["high"] - o["low"]).replace(0, np.nan)
    carp = ((o["close"] - o["low"]) - (o["high"] - o["close"])) / aralik
    o["cmf"] = (carp * o["volume"]).rolling(20).sum() / o["volume"].rolling(20).sum()
    kap_yeri = (o["close"] - o["low"]) / aralik
    o["kap_yeri"] = kap_yeri
    o["bm"] = ((o["vz"] > 2) & (kap_yeri > 0.65)).astype(int)

    hl = o["high"] - o["low"]
    hc = (o["high"] - o["close"].shift(1)).abs()
    lc = (o["low"] - o["close"].shift(1)).abs()
    o["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean() / o["close"] * 100

    o["ext"] = o["close"] / o["s20"] - 1
    o["mom5"] = o["close"].pct_change(5, fill_method=None)
    o["zirve60"] = o["close"].rolling(60).max()

    getiri10 = o["close"].pct_change(10, fill_method=None)
    o["rs"] = getiri10 - endeks_serisi.pct_change(10, fill_method=None) if endeks_serisi is not None else np.nan
    o["rs_sektor"] = getiri10 - sektor_serisi if sektor_serisi is not None else np.nan
    return o
