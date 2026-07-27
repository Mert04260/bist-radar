# -*- coding: utf-8 -*-
"""MERT RADAR — Canli Izleme (paper trading) sistemi."""
import os, csv, datetime, urllib.request, urllib.parse, json, warnings
warnings.filterwarnings("ignore")
import yfinance as yf
import pandas as pd
import numpy as np

S = ("THYAO ASELS EREGL SISE TUPRS FROTO GARAN AKBNK BIMAS KCHOL SAHOL PETKM TCELL "
     "ISCTR YKBNK TOASO SASA HEKTS KRDMD ARCLK ASTOR KONTR ENKAI PGSUS TAVHL MGROS "
     "SOKM ULKER AEFES CCOLA OYAKC CIMSA AKSEN ZOREN ALARK DOAS VESTL TTKOM TTRAK "
     "OTKAR GUBRF EKGYO ISGYO AKSA BRSAN SMRTG GESAN EUPWR YEOTK TUKAS "
     "HALKB VAKBN TSKB ISDMR AYGAZ ALKIM BAGFS DEVA ECILC SELEC LOGO KAREL INDES "
     "MAVI BIZIM ENJSA AYDEM GWIND ODAS KARSN EGEEN TKFEN KORDS VESBE DOHOL AGHOL "
     "TATGD PNSUT BRISA GOODY BUCIM KONYA GOLTS ANHYT AGESA TURSG AKGRT JANTS "
     "TMSN NETAS ALCTL YATAS MPARK CLEBI CWENE "
     "ADEL AGROT AHGAZ AKCNS ALBRK ALTNY ANSGR BERA BFREN BINHO BRYAT BTCIM "
     "CANTE ENERY FENER GLYHO IZENR KCAER KLSER LMKDC MAGEN MIATK PASEU PEKGY "
     "QUAGR REEDR SAYAS SDTTR SKBNK TABGD TUREX VAKKO ISMEN").split()
ESIK = 72
GUVEN_ESIK = 88
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


def sebepler(r, sim):
    s = []
    vr = r["vr"] if pd.notna(r["vr"]) else 1
    if vr >= 2:
        s.append(f"Hacim 20 gunluk ortalamanin %{vr*100:.0f}'i")
    if r.get("bm", 0) == 1:
        s.append("Olagan disi hacim + guclu kapanis: buyuk oyuncu izi")
    if r["macd"] > r["macd_sig"] and r["mh"] > 0:
        s.append("MACD al sinyali aktif")
    rs_v = r["rsi"] if pd.notna(r["rsi"]) else 50
    if 50 <= rs_v <= 70:
        s.append(f"RSI saglikli momentum bolgesinde ({rs_v:.0f})")
    if pd.notna(r["rs"]) and r["rs"] > 0.02:
        s.append(f"Endeksin %{r['rs']*100:.1f} uzerinde goreceli guc")
    if r["close"] > r["s20"] > r["s50"]:
        s.append("Fiyat > SMA20 > SMA50: yukselen trend dizilimi")
    mf = r["mfi"] if pd.notna(r["mfi"]) else 50
    if mf >= 65:
        s.append(f"Para girisi guclu (MFI {mf:.0f})")
    if sim and sim.get("count", 0) >= 10:
        s.append(f"Benzer {sim['count']} gunun %{sim['up']}'i yukselisle sonuclandi")
    return s[:6]


def benzer_gun(e, i):
    r = e.iloc[i]
    h = e.iloc[:i]
    if len(h) < 60 or pd.isna(r["rsi"]) or pd.isna(r["vr"]):
        return None
    m = (
        (h["rsi"].sub(r["rsi"]).abs() < 8)
        & (h["vr"].sub(r["vr"]).abs() < 0.8)
        & ((h["close"] > h["s20"]) == (r["close"] > r["s20"]))
    )
    idxs = h.index[m.fillna(False)]
    fwd = []
    for j in idxs:
        p = e.index.get_loc(j)
        if p + 3 < len(e):
            fwd.append(e["close"].iloc[p+3] / e["close"].iloc[p] - 1)
    if len(fwd) < 10:
        return None
    fwd = np.array(fwd)
    ups = fwd[fwd > 0]; dns = fwd[fwd <= 0]
    return {"count": int(len(fwd)),
            "up": round(float((fwd > 0).mean() * 100), 1),
            "avg_up": round(float(ups.mean() * 100), 2) if len(ups) else 0.0,
            "avg_dn": round(float(abs(dns.mean()) * 100), 2) if len(dns) else 0.0}


def telegram(msg):
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip().replace("\n", "").replace("\r", "")
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip().replace("\n", "").replace("\r", "")
    if not tok or not cid:
        print("Telegram ayarli degil:\n" + msg)
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

    son = []
    for sym, e in ENR.items():
        r = e.iloc[-1]
        if pd.isna(r["rsi"]) or pd.isna(r["s50"]):
            continue
        f = skor(r)
        son.append((f["S"], sym, f, r))
    son.sort(reverse=True)
    sec = [x for x in son if x[0] >= ESIK][:6]

    rows = []
    if os.path.exists(LEDGER):
        with open(LEDGER, newline="") as fh:
            rows = list(csv.DictReader(fh))
    mevcut = {(r["date"], r["sym"]) for r in rows}
    for s_, sym, f, r in sec:
        if (str(bugun), sym) not in mevcut:
            rows.append({"date": str(bugun), "sym": sym, "skor": s_,
                         "giris": round(float(r["close"]), 2), "ret3": "", "sonuc": ""})

    for row in rows:
        if row["ret3"] != "":
            continue
        sym = row["sym"]
        if sym not in ENR:
            continue
        e = ENR[sym]
        pos = e.index[e["date"] == pd.Timestamp(row["date"])]
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

    biten = [r for r in rows if r["ret3"] != ""]
    karne = ""
    if biten:
        isabet = sum(1 for r in biten if r["sonuc"] == "ISABET") / len(biten) * 100
        ort = sum(float(r["ret3"]) for r in biten) / len(biten)
        karne = f"\n📒 KARNE ({len(biten)} kapanan sinyal)\nIsabet: %{isabet:.1f} | Ort. 3g getiri: %{ort:+.2f}\n"

    msg = f"📡 MERT RADAR | {bugun}\nTaranan: {len(son)} → Secilen: {len(sec)}\n\n"
    if not sec:
        msg += "🛑 BUGUN ISLEM YAPMA — esik gecilmedi.\n"
        if son:
            msg += f"En yuksek: {son[0][1]} {son[0][0]}/100\n"
    else:
        for s_, sym, f, r in sec:
            risk = "Dusuk" if r["atr"] < 2.5 else ("Orta" if r["atr"] < 4.5 else "Yuksek")
            g = "⭐" if s_ >= GUVEN_ESIK else "•"
            msg += f"{g} {sym} {s_}/100 | {risk} | {r['close']:.2f}\n"
        msg += f"\n⭐ = {GUVEN_ESIK}+ guven dilimi\n"
    msg += karne
    msg += "\n⚠️ Yatirim tavsiyesi degildir. Kagit-uzerinde izleme modu."
    print(msg)
    telegram(msg)

    radar_list = []
    for s_, sym, f, r in sec:
        e = ENR[sym]
        risk = "Dusuk" if r["atr"] < 2.5 else ("Orta" if r["atr"] < 4.5 else "Yuksek")
        sim = benzer_gun(e, len(e) - 1)
        beklenen = f"+%{sim['avg_up']:.1f} / -%{sim['avg_dn']:.1f}" if sim else None
        radar_list.append({
            "sym": sym, "skor": s_, "risk": risk,
            "fiyat": round(float(r["close"]), 2),
            "guven": bool(s_ >= GUVEN_ESIK),
            "faktor": {"Trend": f["T"], "Hacim": f["H"], "Para": f["P"], "Teknik": f["K"]},
            "sebep": sebepler(r, sim),
            "benzer": sim,
            "beklenen": beklenen,
            "seri": [round(float(x), 2) for x in e["close"].tail(30).tolist()],
        })
    karne_obj = None
    if biten:
        karne_obj = {"adet": len(biten),
                     "isabet": round(sum(1 for r in biten if r["sonuc"] == "ISABET") / len(biten) * 100, 1),
                     "ort_getiri": round(sum(float(r["ret3"]) for r in biten) / len(biten), 2)}
    karne_seri = []
    dogru = 0
    for n, row in enumerate(sorted(biten, key=lambda x: x["date"]), 1):
        if row["sonuc"] == "ISABET":
            dogru += 1
        karne_seri.append({"date": row["date"], "isabet": round(dogru / n * 100, 1), "adet": n})
    endeks = None
    if IDX is not None and len(IDX.dropna()) > 31:
        iv = IDX.dropna()
        endeks = {"degisim": round(float(iv.iloc[-1] / iv.iloc[-2] - 1) * 100, 2),
                  "seri": [round(float(x), 1) for x in iv.tail(30).tolist()]}
    gecmis = [r for r in rows if r["ret3"] != ""][-15:]
    web = {"tarih": str(bugun), "taranan": len(son), "endeks": endeks,
           "radar": radar_list, "karne": karne_obj, "karne_seri": karne_seri,
           "gecmis": [{"date": r["date"], "sym": r["sym"], "skor": r["skor"],
                       "ret3": r["ret3"], "sonuc": r["sonuc"]} for r in gecmis]}
    with open("../data.json", "w", encoding="utf-8") as fh:
        json.dump(web, fh, ensure_ascii=False, indent=1)
    print("data.json yazildi (tam surum).")


if __name__ == "__main__":
    main()
