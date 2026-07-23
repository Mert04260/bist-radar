# -*- coding: utf-8 -*-
"""BIST RADAR — Canli Izleme (paper trading) sistemi.
Her sabah GitHub Actions tarafindan calistirilir:
1) Gun sonu verisini indirir, skorlari hesaplar
2) Gunun radarini uretir ve signals.csv'ye kaydeder
3) 3+ is gunu onceki sinyalleri degerlendirir (karne)
4) Sonucu Telegram'a gonderir
Yatirim tavsiyesi degildir.
"""
import os, csv, datetime, urllib.request, urllib.parse, json, warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np

S = ("THYAO ASELS EREGL SISE TUPRS FROTO GARAN AKBNK BIMAS KCHOL SAHOL PETKM TCELL "
     "ISCTR YKBNK TOASO SASA HEKTS KRDMD ARCLK ASTOR KONTR ENKAI PGSUS TAVHL MGROS "
     "SOKM ULKER AEFES CCOLA OYAKC CIMSA AKSEN ZOREN ALARK DOAS VESTL TTKOM TTRAK "
     "OTKAR GUBRF EKGYO ISGYO AKSA BRSAN SMRTG GESAN EUPWR YEOTK").split()
ESIK = 72
GUVEN_ESIK = 88   # "ciddiye al" cizgisi
LEDGER = "signals.csv"


def indir(t):
    df = yf.download(t, period="2y", auto_adjust=True, progress=False)
    if df.empty:
        return None
    df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    try:
        return df[["date", "open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)
    except KeyError:
        return None


def enrich(df, ic=None):
    o = df.copy()
    d = o["close"].diff()
    g = d.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    o["rsi"] = 100 - 100/(1 + g/l.replace(0, np.nan))
    m = o["close"].ewm(span=12).mean() - o["close"].ewm(span=26).mean()
    o["macd"], o["macd_sig"] = m, m.ewm(span=9).mean()
    o["mh"] = o["macd"] - o["macd_sig"]
    o["s20"] = o["close"].rolling(20).mean()
    o["s50"] = o["close"].rolling(50).mean()
    o["vr"] = o["volume"] / o["volume"].rolling(20).mean()
    o["vz"] = (o["volume"] - o["volume"].rolling(20).mean()) / o["volume"].rolling(20).std().replace(0, np.nan)
    tp = (o["high"] + o["low"] + o["close"]) / 3
    raw = tp * o["volume"]
    pos = raw.where(tp > tp.shift(1), 0.0).rolling(14).sum()
    neg = raw.where(tp < tp.shift(1), 0.0).rolling(14).sum()
    o["mfi"] = 100 - 100/(1 + pos/neg.replace(0, np.nan))
    rng = (o["high"] - o["low"]).replace(0, np.nan)
    o["cmf"] = ((((o["close"]-o["low"])-(o["high"]-o["close"]))/rng)*o["volume"]).rolling(20).sum()/o["volume"].rolling(20).sum()
    o["bm"] = ((o["vz"] > 2) & (((o["close"]-o["low"])/rng) > 0.65)).astype(int)
    hl = o["high"]-o["low"]; hc = (o["high"]-o["close"].shift(1)).abs(); lc = (o["low"]-o["close"].shift(1)).abs()
    o["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean()/o["close"]*100
    o["ext"] = o["close"]/o["s20"] - 1
    o["rs"] = o["close"].pct_change(10, fill_method=None) - (ic.pct_change(10, fill_method=None) if ic is not None else 0)
    return o


def skor(r):
    c = lambda x: float(np.clip(x, 0, 20))
    t = (6 if r["close"] > r["s20"] else 0) + (4 if r["close"] > r["s50"] else 0) + (4 if r["s20"] > r["s50"] else 0)
    t += float(np.clip(r["rs"]*100, -3, 6))
    e = r["ext"] if pd.notna(r["ext"]) else 0
    if e > 0.08:
        t -= min((e-0.08)*100, 8)
    vr = r["vr"] if pd.notna(r["vr"]) else 1
    vz = r["vz"] if pd.notna(r["vz"]) else 0
    h = np.interp(min(vr, 4), [0.8, 1.5, 2.5, 4], [4, 10, 16, 20]) + float(np.clip(vz, 0, 2)) - (4 if vr > 6 else 0)
    mf = r["mfi"] if pd.notna(r["mfi"]) else 50
    cf = r["cmf"] if pd.notna(r["cmf"]) else 0
    p = np.interp(mf, [30, 50, 65, 80], [3, 9, 15, 18]) + float(np.clip(cf*20, -4, 4)) + (4 if r["bm"] == 1 else 0) - (5 if mf > 88 else 0)
    rs = r["rsi"] if pd.notna(r["rsi"]) else 50
    k = (8 if 50 <= rs <= 68 else (4 if 45 <= rs < 50 or 68 < rs <= 75 else 0)) + (5 if r["mh"] > 0 else 0)
    k += (4 if r["macd"] > r["macd_sig"] and r["mh"] > 0 else 0) - (8 if rs > 78 else 0)
    T, H, P, K = c(t), c(h), c(p), c(k+3)
    return {"T": round(T, 1), "H": round(H, 1), "P": round(P, 1), "K": round(K, 1),
            "S": round((T+H+P+K)/4*5, 1)}


def telegram(msg):
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip()
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not tok or not cid:
        print("Telegram ayarli degil, mesaj konsola yazildi:\n" + msg)
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": cid, "text": msg}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20)
        print("Telegram gonderildi.")
    except Exception as ex:
        print("Telegram hatasi:", ex)


def main():
    print("Veri iniyor...")
    DATA = {}
    for s in S:
        d = indir(s + ".IS")
        if d is not None and len(d) > 150:
            DATA[s] = d
    i = indir("XU100.IS")
    IDX = i.set_index("date")["close"] if i is not None else None
    ENR = {}
    for sym, df in DATA.items():
        ic = IDX.reindex(df["date"]).reset_index(drop=True) if IDX is not None else None
        ENR[sym] = enrich(df, ic)
    bugun = max(e["date"].iloc[-1] for e in ENR.values()).date()

    # ── 1) Gunun radari ────────────────────────────────────
    son = []
    for sym, e in ENR.items():
        r = e.iloc[-1]
        if pd.isna(r["rsi"]) or pd.isna(r["s50"]):
            continue
        f = skor(r)
        son.append((f["S"], sym, f, r))
    son.sort(reverse=True)
    sec = [x for x in son if x[0] >= ESIK][:6]

    # ── 2) Karne defteri: yeni sinyalleri ekle ─────────────
    rows = []
    if os.path.exists(LEDGER):
        with open(LEDGER, newline="") as fh:
            rows = list(csv.DictReader(fh))
    mevcut = {(r["date"], r["sym"]) for r in rows}
    for s_, sym, f, r in sec:
        key = (str(bugun), sym)
        if key not in mevcut:
            rows.append({"date": str(bugun), "sym": sym, "skor": s_,
                         "giris": round(float(r["close"]), 2),
                         "ret3": "", "sonuc": ""})

    # ── 3) 3+ is gunu onceki bekleyen sinyalleri degerlendir ─
    for row in rows:
        if row["ret3"] != "":
            continue
        sym = row["sym"]
        if sym not in ENR:
            continue
        e = ENR[sym]
        tarih = pd.Timestamp(row["date"])
        pos = e.index[e["date"] == tarih]
        if len(pos) == 0:
            continue
        pi = pos[0]
        if pi + 3 < len(e):
            ret3 = (e["close"].iloc[pi+3] / float(row["giris"]) - 1) * 100
            row["ret3"] = round(float(ret3), 2)
            row["sonuc"] = "ISABET" if ret3 > 0 else "ISKA"

    with open(LEDGER, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["date", "sym", "skor", "giris", "ret3", "sonuc"])
        w.writeheader()
        w.writerows(rows)

    # ── 4) Karne ozeti ─────────────────────────────────────
    biten = [r for r in rows if r["ret3"] != ""]
    karne = ""
    if biten:
        isabet = sum(1 for r in biten if r["sonuc"] == "ISABET") / len(biten) * 100
        ort = sum(float(r["ret3"]) for r in biten) / len(biten)
        karne = f"\n📒 KARNE ({len(biten)} kapanan sinyal)\nIsabet: %{isabet:.1f} | Ort. 3g getiri: %{ort:+.2f}\n"
        g88 = [r for r in biten if float(r["skor"]) >= GUVEN_ESIK]
        if g88:
            i88 = sum(1 for r in g88 if r["sonuc"] == "ISABET") / len(g88) * 100
            karne += f"88+ dilimi: {len(g88)} sinyal, isabet %{i88:.1f}\n"

    # ── 5) Telegram mesaji ─────────────────────────────────
    msg = f"📡 BIST RADAR | {bugun}\nTaranan: {len(son)} → Secilen: {len(sec)}\n\n"
    if not sec:
        msg += "🛑 BUGUN ISLEM YAPMA — esik gecilmedi.\n"
        if son:
            msg += f"En yuksek: {son[0][1]} {son[0][0]}/100\n"
    else:
        for s_, sym, f, r in sec:
            risk = "Dusuk" if r["atr"] < 2.5 else ("Orta" if r["atr"] < 4.5 else "Yuksek")
            g = "⭐" if s_ >= GUVEN_ESIK else "•"
            msg += f"{g} {sym} {s_}/100 | {risk} | {r['close']:.2f}\n"
        msg += f"\n⭐ = {GUVEN_ESIK}+ guven dilimi (backtest'te en isabetli)\n"
    msg += karne
    msg += "\n⚠️ Yatirim tavsiyesi degildir. Kagit-uzerinde izleme modu."
    print(msg)
    telegram(msg)


if __name__ == "__main__":
    main()
