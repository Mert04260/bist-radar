
# -*- coding: utf-8 -*-
"""MERT RADAR v3 - BIST tarama ve kagit-uzerinde izleme sistemi."""
import os, sys, csv, json, time, warnings
warnings.filterwarnings("ignore")
import urllib.request, urllib.parse

try:
    import yfinance as yf
except ImportError:
    print("HATA: yfinance kurulu degil.  ->  pip install yfinance pandas numpy")
    sys.exit(1)
import pandas as pd
import numpy as np

UFUK = 3
ESIK = 72
GUVEN_ESIK = 88
MAX_SECIM = 6
MIN_ISLEM_TL = 5_000_000
PARCA_BOYU = 25
GECMIS_GUN = "2y"

SEMBOLLER = (
 "THYAO ASELS EREGL SISE TUPRS FROTO GARAN AKBNK BIMAS KCHOL SAHOL PETKM TCELL "
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

BETIK_DIZIN = os.path.dirname(os.path.abspath(__file__))

def _repo_koku():
    d = BETIK_DIZIN
    for _ in range(4):
        if os.path.exists(os.path.join(d, "index.html")) or os.path.isdir(os.path.join(d, ".git")):
            return d
        ust = os.path.dirname(d)
        if ust == d:
            break
        d = ust
    return BETIK_DIZIN

KOK = _repo_koku()
DEFTER = os.path.join(BETIK_DIZIN, "signals.csv")
ARSIV = os.path.join(BETIK_DIZIN, "signals_v2_arsiv.csv")
CIKTI_JSON = os.path.join(KOK, "data.json")
DEFTER_BASLIK = ["date", "sym", "skor", "giris", "giris_tarih", "hedef", "stop",
                 "cikis", "getiri", "sonuc"]


def _duzenle(df):
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.columns = [str(c).lower() for c in df.columns]
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    if "date" not in df.columns:
        for aday in ("datetime", "index"):
            if aday in df.columns:
                df = df.rename(columns={aday: "date"})
                break
    gerek = ["date", "open", "high", "low", "close", "volume"]
    if not all(k in df.columns for k in gerek):
        return None
    df = df[gerek].dropna()
    if len(df) == 0:
        return None
    df["date"] = pd.to_datetime(df["date"])
    try:
        if getattr(df["date"].dt, "tz", None) is not None:
            df["date"] = df["date"].dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    df["date"] = df["date"].dt.normalize()
    return df.sort_values("date").reset_index(drop=True)


def tek_indir(tic, deneme=2):
    for i in range(deneme):
        try:
            ham = yf.download(tic, period=GECMIS_GUN, auto_adjust=True,
                              progress=False, threads=False)
            d = _duzenle(ham)
            if d is not None:
                return d
        except Exception:
            if i + 1 < deneme:
                time.sleep(1.5)
    return None


def toplu_indir(semboller):
    veri, hatali = {}, []
    for i in range(0, len(semboller), PARCA_BOYU):
        parca = semboller[i:i + PARCA_BOYU]
        tickers = [s + ".IS" for s in parca]
        toplu = None
        try:
            toplu = yf.download(" ".join(tickers), period=GECMIS_GUN,
                                auto_adjust=True, progress=False,
                                group_by="ticker", threads=True)
        except Exception:
            toplu = None
        for s, tic in zip(parca, tickers):
            d = None
            if toplu is not None and isinstance(toplu.columns, pd.MultiIndex):
                try:
                    if tic in toplu.columns.get_level_values(0):
                        d = _duzenle(toplu[tic])
                except Exception:
                    d = None
            if d is None:
                d = tek_indir(tic)
            if d is not None and len(d) > 120:
                veri[s] = d
            else:
                hatali.append(s)
        time.sleep(0.4)
    return veri, hatali


def zenginlestir(df, endeks_serisi=None):
    o = df.copy()
    d = o["close"].diff()
    kaz = d.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    kay = (-d.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    o["rsi"] = 100 - 100 / (1 + kaz / kay.replace(0, np.nan))
    m = o["close"].ewm(span=12).mean() - o["close"].ewm(span=26).mean()
    o["macd"] = m
    o["macd_sig"] = m.ewm(span=9).mean()
    o["mh"] = o["macd"] - o["macd_sig"]
    o["s20"] = o["close"].rolling(20).mean()
    o["s50"] = o["close"].rolling(50).mean()
    hac_ort = o["volume"].rolling(20).mean()
    hac_std = o["volume"].rolling(20).std()
    o["vr"] = o["volume"] / hac_ort.replace(0, np.nan)
    o["vz"] = (o["volume"] - hac_ort) / hac_std.replace(0, np.nan)
    o["islem_tl"] = (o["close"] * o["volume"]).rolling(20).mean()
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
    kapanis_yeri = (o["close"] - o["low"]) / aralik
    o["kap_yeri"] = kapanis_yeri
    o["bm"] = ((o["vz"] > 2) & (kapanis_yeri > 0.65)).astype(int)
    hl = o["high"] - o["low"]
    hc = (o["high"] - o["close"].shift(1)).abs()
    lc = (o["low"] - o["close"].shift(1)).abs()
    o["atr"] = pd.concat([hl, hc, lc], axis=1).max(axis=1).rolling(14).mean() / o["close"] * 100
    o["ext"] = o["close"] / o["s20"] - 1
    o["mom5"] = o["close"].pct_change(5, fill_method=None)
    if endeks_serisi is not None:
        o["rs"] = o["close"].pct_change(10, fill_method=None) - endeks_serisi.pct_change(10, fill_method=None)
    else:
        o["rs"] = np.nan
    return o


def _s(x, alt=0.0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return alt
    return alt if not np.isfinite(v) else v


def skorla(r):
    kirp = lambda v: float(np.clip(v, 0, 20))
    t = 0.0
    if _s(r["close"]) > _s(r["s20"]):
        t += 6
    if _s(r["close"]) > _s(r["s50"]):
        t += 4
    if _s(r["s20"]) > _s(r["s50"]):
        t += 4
    rs = r["rs"]
    rs_var = np.isfinite(_s(rs, np.nan)) if rs is not None else False
    if rs_var:
        t += float(np.clip(_s(rs) * 100, -3, 6))
    ext = _s(r["ext"])
    if ext > 0.08:
        t -= min((ext - 0.08) * 100, 8)
    trend = kirp(t)
    vr = _s(r["vr"], 1.0)
    vz = _s(r["vz"], 0.0)
    mom5 = _s(r["mom5"], 0.0)
    kap_yeri = _s(r["kap_yeri"], 0.5)
    h = np.interp(min(vr, 4.0), [0.8, 1.5, 2.5, 4.0], [4, 10, 16, 20])
    h += float(np.clip(vz, 0, 2))
    if vr > 6:
        h -= 4
    if vr >= 2.0 and mom5 < -0.03:
        h -= 10
    if vr >= 2.0 and kap_yeri < 0.35:
        h -= 5
    hacim = kirp(h)
    mf = _s(r["mfi"], 50.0)
    cf = _s(r["cmf"], 0.0)
    p = np.interp(mf, [30, 50, 65, 80], [3, 9, 15, 18])
    p += float(np.clip(cf * 20, -4, 4))
    if _s(r["bm"], 0) == 1 and mom5 >= -0.02:
        p += 4
    if mf > 88:
        p -= 5
    if cf < 0:
        p -= 3
    para = kirp(p)
    rsi = _s(r["rsi"], 50.0)
    k = 0.0
    if 50 <= rsi <= 68:
        k += 8
    elif 45 <= rsi < 50 or 68 < rsi <= 75:
        k += 4
    if _s(r["mh"]) > 0:
        k += 5
    if _s(r["macd"]) > _s(r["macd_sig"]) and _s(r["mh"]) > 0:
        k += 4
    if rsi > 78:
        k -= 8
    teknik = kirp(k + 3)
    toplam = (trend + hacim + para + teknik) / 4 * 5
    if trend < 8:
        toplam = min(toplam, 84.0)
    if trend < 5:
        toplam = min(toplam, 76.0)
    return {"T": round(trend, 1), "H": round(hacim, 1), "P": round(para, 1),
            "K": round(teknik, 1), "S": round(float(toplam), 1),
            "rs_var": bool(rs_var)}


def benzer_gun(e, i):
    r = e.iloc[i]
    gecmis = e.iloc[:i]
    if len(gecmis) < 80 or not np.isfinite(_s(r["rsi"], np.nan)) or not np.isfinite(_s(r["vr"], np.nan)):
        return None
    m = (
        gecmis["rsi"].sub(r["rsi"]).abs().lt(8)
        & gecmis["vr"].sub(r["vr"]).abs().lt(0.8)
        & (gecmis["close"].gt(gecmis["s20"]) == bool(r["close"] > r["s20"]))
    ).fillna(False)
    konumlar = np.flatnonzero(m.to_numpy())
    epizotlar, son = [], -10000
    for p in konumlar:
        if p - son > UFUK:
            epizotlar.append(p)
            son = p
    getiriler = []
    for p in epizotlar:
        if p + 1 < len(e) and p + UFUK < len(e):
            giris = float(e["open"].iloc[p + 1])
            cikis = float(e["close"].iloc[p + UFUK])
            if giris > 0:
                getiriler.append(cikis / giris - 1)
    if len(getiriler) < 8:
        return None
    g = np.array(getiriler)
    yuk, dus = g[g > 0], g[g <= 0]
    return {
        "epizot": int(len(g)),
        "ham": int(len(konumlar)),
        "up": round(float((g > 0).mean() * 100), 1),
        "avg_up": round(float(yuk.mean() * 100), 2) if len(yuk) else 0.0,
        "avg_dn": round(float(abs(dus.mean()) * 100), 2) if len(dus) else 0.0,
    }


def sebepler(r, sim, f):
    s = []
    vr = _s(r["vr"], 1.0)
    mom5 = _s(r["mom5"], 0.0)
    if vr >= 2:
        s.append(f"Hacim 20 gunluk ortalamanin %{vr*100:.0f}'i")
    if _s(r["bm"], 0) == 1 and mom5 >= -0.02:
        s.append("Olagan disi hacim + guclu kapanis: buyuk oyuncu izi olabilir")
    if vr >= 2 and mom5 < -0.03:
        s.append("UYARI: hacim yuksek ama fiyat dususte - cikis baskisi olabilir")
    if _s(r["macd"]) > _s(r["macd_sig"]) and _s(r["mh"]) > 0:
        s.append("MACD al sinyali aktif")
    rsi = _s(r["rsi"], 50)
    if 50 <= rsi <= 70:
        s.append(f"RSI saglikli momentum bolgesinde ({rsi:.0f})")
    if f.get("rs_var") and _s(r["rs"]) > 0.02:
        s.append(f"Endekse gore %{_s(r['rs'])*100:.1f} daha iyi performans")
    if _s(r["close"]) > _s(r["s20"]) > _s(r["s50"]):
        s.append("Fiyat > SMA20 > SMA50: yukselen trend dizilimi")
    mf = _s(r["mfi"], 50)
    if mf >= 65:
        s.append(f"Para akisi gostergeleri olumlu (MFI {mf:.0f})")
    if sim:
        s.append(f"Benzer {sim['epizot']} bagimsiz epizodun %{sim['up']}'i yukselisle bitmis")
    return s[:7]


def telegram(mesaj):
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip().replace("\n", "").replace("\r", "")
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip().replace("\n", "").replace("\r", "")
    if not tok or not cid:
        print("Telegram ayarli degil. Mesaj:\n" + mesaj)
        return
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    veri = urllib.parse.urlencode({"chat_id": cid, "text": mesaj}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=veri), timeout=25)
        print("Telegram gonderildi.")
    except Exception as ex:
        print("Telegram hatasi:", ex)


def defter_oku():
    if not os.path.exists(DEFTER):
        return [], False
    with open(DEFTER, newline="", encoding="utf-8") as fh:
        satirlar = list(csv.DictReader(fh))
    if satirlar and "giris_tarih" not in satirlar[0]:
        try:
            os.replace(DEFTER, ARSIV)
            print(f"UYARI: v2 defteri arsivlendi ({len(satirlar)} satir). Karne temiz basliyor.")
        except OSError as ex:
            print("Arsivleme hatasi:", ex)
        return [], True
    return satirlar, False


def defter_yaz(satirlar):
    with open(DEFTER, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=DEFTER_BASLIK)
        w.writeheader()
        for s in satirlar:
            w.writerow({k: s.get(k, "") for k in DEFTER_BASLIK})


def main(test_modu=False, sembol_limit=None):
    sem = SEMBOLLER if not sembol_limit else SEMBOLLER[:sembol_limit]
    print(f"Veri iniyor ({len(sem)} sembol)...")
    VERI, hatali = toplu_indir(sem)
    print(f"  indirilen: {len(VERI)} | alinamayan: {len(hatali)}")
    if not VERI:
        print("HATA: hicbir sembol indirilemedi, cikiliyor.")
        return 1
    idf = tek_indir("XU100.IS")
    ENDEKS = idf.set_index("date")["close"] if idf is not None else None
    if ENDEKS is None:
        print("UYARI: endeks (XU100) alinamadi - goreceli guc hesaplanmayacak.")
    ZEN = {}
    for s, df in VERI.items():
        es = ENDEKS.reindex(df["date"]).reset_index(drop=True) if ENDEKS is not None else None
        ZEN[s] = zenginlestir(df, es)
    son_tarihler = [e["date"].iloc[-1] for e in ZEN.values()]
    piyasa_gunu = pd.Series(son_tarihler).mode().iloc[0]
    bugun = piyasa_gunu.date()
    adaylar, bayat, likit_disi = [], [], []
    for s, e in ZEN.items():
        r = e.iloc[-1]
        if r["date"] != piyasa_gunu:
            bayat.append(s)
            continue
        if not np.isfinite(_s(r["rsi"], np.nan)) or not np.isfinite(_s(r["s50"], np.nan)):
            continue
        if _s(r["islem_tl"], 0) < MIN_ISLEM_TL:
            likit_disi.append(s)
            continue
        f = skorla(r)
        adaylar.append((f["S"], s, f, r))
    adaylar.sort(key=lambda x: (-x[0], x[1]))
    secilen = [a for a in adaylar if a[0] >= ESIK][:MAX_SECIM]
    print(f"  taranan: {len(adaylar)} | bayat: {len(bayat)} | likit disi: {len(likit_disi)}")
    satirlar, arsivlendi = defter_oku()
    mevcut = {(x["date"], x["sym"]) for x in satirlar}
    for skor, sym, f, r in secilen:
        if (str(bugun), sym) in mevcut:
            continue
        sim = benzer_gun(ZEN[sym], len(ZEN[sym]) - 1)
        hedef = stop = ""
        if sim:
            hedef = round(float(r["close"]) * (1 + sim["avg_up"] / 100), 2)
            stop = round(float(r["close"]) * (1 - sim["avg_dn"] / 100), 2)
        satirlar.append({"date": str(bugun), "sym": sym, "skor": skor,
                         "giris": "", "giris_tarih": "", "hedef": hedef,
                         "stop": stop, "cikis": "", "getiri": "", "sonuc": ""})
    for satir in satirlar:
        sym = satir["sym"]
        if sym not in ZEN:
            continue
        e = ZEN[sym]
        try:
            sinyal_g = pd.Timestamp(satir["date"]).normalize()
        except Exception:
            continue
        konum = e.index[e["date"] == sinyal_g]
        if len(konum) == 0:
            continue
        i = int(konum[0])
        if not satir.get("giris"):
            if i + 1 < len(e):
                satir["giris"] = round(float(e["open"].iloc[i + 1]), 2)
                satir["giris_tarih"] = str(e["date"].iloc[i + 1].date())
            else:
                continue
        if satir.get("giris") and not satir.get("getiri"):
            if i + UFUK < len(e):
                giris = float(satir["giris"])
                cikis = float(e["close"].iloc[i + UFUK])
                if giris > 0:
                    getiri = (cikis / giris - 1) * 100
                    satir["cikis"] = round(cikis, 2)
                    satir["getiri"] = round(getiri, 2)
                    satir["sonuc"] = "ISABET" if getiri > 0 else "ISKA"
    defter_yaz(satirlar)
    biten = [x for x in satirlar if x.get("getiri") not in ("", None)]
    bekleyen = [x for x in satirlar if x.get("getiri") in ("", None)]
    karne = None
    if biten:
        isabet = sum(1 for x in biten if x["sonuc"] == "ISABET") / len(biten) * 100
        ort = sum(float(x["getiri"]) for x in biten) / len(biten)
        karne = {"adet": len(biten), "isabet": round(isabet, 1),
                 "ort_getiri": round(ort, 2), "bekleyen": len(bekleyen)}
    msg = f"MERT RADAR | {bugun}\nTaranan: {len(adaylar)} -> Secilen: {len(secilen)}\n\n"
    if not secilen:
        msg += "BUGUN ISLEM YAPMA - hicbir hisse esigi gecemedi.\n"
        if adaylar:
            msg += f"En yuksek: {adaylar[0][1]} {adaylar[0][0]}/100\n"
    else:
        for skor, sym, f, r in secilen:
            risk = "Dusuk" if _s(r["atr"], 3) < 2.5 else ("Orta" if _s(r["atr"], 3) < 4.5 else "Yuksek")
            im = "*" if skor >= GUVEN_ESIK else "-"
            msg += f"{im} {sym} {skor}/100 | {risk} | {float(r['close']):.2f}\n"
        msg += f"\n* = {GUVEN_ESIK}+ guven dilimi\nGiris ertesi acilistan varsayilir.\n"
    if karne:
        msg += (f"\nKARNE ({karne['adet']} kapanan, {karne['bekleyen']} bekleyen)\n"
                f"Isabet: %{karne['isabet']} | Ort. {UFUK}g getiri: %{karne['ort_getiri']:+.2f}\n")
    if ENDEKS is None:
        msg += "\nUYARI: Endeks alinamadi - goreceli guc bu kosuda hesaplanmadi.\n"
    if arsivlendi:
        msg += "\nEski defter arsivlendi (giris fiyati duzeltmesi). Karne sifirdan basliyor.\n"
    msg += "\nYatirim tavsiyesi degildir. Kagit-uzerinde izleme modu."
    print(msg)
    if not test_modu:
        telegram(msg)
    radar_listesi = []
    for skor, sym, f, r in secilen:
        e = ZEN[sym]
        sim = benzer_gun(e, len(e) - 1)
        risk = "Dusuk" if _s(r["atr"], 3) < 2.5 else ("Orta" if _s(r["atr"], 3) < 4.5 else "Yuksek")
        kap = float(r["close"])
        radar_listesi.append({
            "sym": sym, "skor": skor, "risk": risk, "fiyat": round(kap, 2),
            "guven": bool(skor >= GUVEN_ESIK),
            "faktor": {"Trend": f["T"], "Hacim": f["H"], "Para": f["P"], "Teknik": f["K"]},
            "sebep": sebepler(r, sim, f),
            "benzer": sim,
            "hedef": round(kap * (1 + sim["avg_up"] / 100), 2) if sim else None,
            "stop": round(kap * (1 - sim["avg_dn"] / 100), 2) if sim else None,
            "seri": [round(float(x), 2) for x in e["close"].tail(30).tolist()],
        })
    karne_seri, dogru = [], 0
    for n, x in enumerate(sorted(biten, key=lambda z: z["date"]), 1):
        if x["sonuc"] == "ISABET":
            dogru += 1
        karne_seri.append({"date": x["date"], "isabet": round(dogru / n * 100, 1), "adet": n})
    endeks_obj = None
    if ENDEKS is not None:
        iv = ENDEKS.dropna()
        if len(iv) > 31:
            endeks_obj = {"degisim": round(float(iv.iloc[-1] / iv.iloc[-2] - 1) * 100, 2),
                          "seri": [round(float(x), 1) for x in iv.tail(30).tolist()]}
    gecmis = [{"date": x["date"], "sym": x["sym"], "skor": x["skor"],
               "giris": x.get("giris", ""), "getiri": x["getiri"], "sonuc": x["sonuc"]}
              for x in biten][-15:]
    web = {
        "surum": "v3",
        "tarih": str(bugun),
        "ufuk": UFUK,
        "taranan": len(adaylar),
        "evren": len(sem),
        "endeks": endeks_obj,
        "radar": radar_listesi,
        "karne": karne,
        "karne_seri": karne_seri,
        "gecmis": gecmis,
        "uyarilar": {
            "endeks_yok": ENDEKS is None,
            "bayat": len(bayat),
            "likit_disi": len(likit_disi),
            "alinamayan": len(hatali),
            "defter_arsivlendi": arsivlendi,
        },
    }
    gecici = CIKTI_JSON + ".tmp"
    with open(gecici, "w", encoding="utf-8") as fh:
        json.dump(web, fh, ensure_ascii=False, indent=1)
    os.replace(gecici, CIKTI_JSON)
    print(f"data.json yazildi -> {CIKTI_JSON}")
    return 0


if __name__ == "__main__":
    test = "--test" in sys.argv
    limit = None
    if "--sembol" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--sembol") + 1])
        except (IndexError, ValueError):
            limit = None
    sys.exit(main(test_modu=test, sembol_limit=limit))
