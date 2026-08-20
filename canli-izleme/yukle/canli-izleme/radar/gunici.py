# -*- coding: utf-8 -*-
"""Gun ici anomali tespiti, arsivi ve anomali karnesi."""
import csv
import json
import os
import time

import numpy as np
import pandas as pd

from .ayar import AYAR, yol_veri

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

ARSIV_BASLIK = ["ts", "gun", "saat", "sym", "tip", "baslik", "siddet", "fiyat", "detay"]


def _duzenle(ham):
    if ham is None or len(ham) == 0:
        return None
    d = ham.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = [c[0] for c in d.columns]
    d.columns = [str(c).lower() for c in d.columns]
    d = d.reset_index()
    d.columns = [str(c).lower() for c in d.columns]
    zaman = next((k for k in ("datetime", "date", "index") if k in d.columns), None)
    if zaman is None:
        return None
    d = d.rename(columns={zaman: "ts"})
    gerek = ("ts", "open", "high", "low", "close", "volume")
    if not all(k in d.columns for k in gerek):
        return None
    d = d[list(gerek)].dropna()
    if len(d) < 12:
        return None
    d["ts"] = pd.to_datetime(d["ts"], utc=True, errors="coerce")
    d = d.dropna(subset=["ts"])
    return d.sort_values("ts").reset_index(drop=True) if len(d) >= 12 else None


def tek_indir(tic, deneme=2):
    if yf is None:
        return None
    for i in range(deneme):
        try:
            ham = yf.download(tic, period=AYAR.gunici.gecmis, interval=AYAR.gunici.aralik,
                              auto_adjust=True, progress=False, threads=False, prepost=False)
            d = _duzenle(ham)
            if d is not None:
                return d
        except Exception:
            if i + 1 < deneme:
                time.sleep(1.5)
    return None


def indir(semboller):
    if yf is None:
        return {}, list(semboller)
    veri, hatali = {}, []
    for i in range(0, len(semboller), int(AYAR.veri.parca_boyu)):
        parca = semboller[i:i + int(AYAR.veri.parca_boyu)]
        tickerlar = [s + ".IS" for s in parca]
        toplu = None
        try:
            toplu = yf.download(" ".join(tickerlar), period=AYAR.gunici.gecmis,
                                interval=AYAR.gunici.aralik, auto_adjust=True,
                                progress=False, group_by="ticker", threads=True, prepost=False)
        except Exception:
            toplu = None
        cok = toplu is not None and isinstance(toplu.columns, pd.MultiIndex)
        for s, tic in zip(parca, tickerlar):
            d = None
            if cok:
                try:
                    if tic in toplu.columns.get_level_values(0):
                        d = _duzenle(toplu[tic])
                except Exception:
                    d = None
            elif toplu is not None and len(parca) == 1:
                # tek seviyeli kolon geldiginde veriyi tum parcaya dagitmak
                # butun sembolleri ayni hisseye esitler - sadece tek sembolluk
                # parcada guvenli
                d = _duzenle(toplu)
            if d is None:
                d = tek_indir(tic)
            if d is None:
                hatali.append(s)
            else:
                veri[s] = d
        time.sleep(0.4)
    return veri, hatali


def taban_hacim(onceki_df, d, slot, ayar=None):
    """Ayni saat dilimindeki gecmis barlarin ortalamasi.

    Acilis ve kapanis barlari yapisal olarak 3-5 kat hacimlidir; duz 60-bar
    ortalamasi kullanilirsa her sabah sahte "hacim patlamasi" uretilir.
    """
    ayar = ayar or AYAR
    if len(onceki_df):
        slot_gec = onceki_df.loc[onceki_df["slot"] == slot, "volume"]
        if len(slot_gec) >= int(ayar.gunici.min_slot_ornek):
            t = float(slot_gec.mean())
            if t > 0:
                return t, "slot"
        genel = onceki_df["volume"].tail(60)
        if len(genel) >= 10:
            t = float(genel.mean())
            if t > 0:
                return t, "genel"
    kaba = d["volume"].iloc[:-1].tail(60)
    return (float(kaba.mean()) if len(kaba) else 0.0), "zayif"


def anomali(sym, d, simdi, gs_kapanis=None, ayar=None):
    ayar = ayar or AYAR
    g = ayar.gunici
    sonuc = []
    tr = d["ts"].dt.tz_convert(AYAR.genel.tz)
    d = d.assign(gun=tr.dt.date, slot=tr.dt.strftime("%H:%M"))
    son = d.iloc[-1]
    fiyat = float(son["close"])
    if fiyat <= 0:
        return sonuc
    son_gun = son["gun"]
    bugun_df = d[d["gun"] == son_gun]
    onceki_df = d[d["gun"] < son_gun]

    taban, taban_tip = taban_hacim(onceki_df, d, son["slot"], ayar)
    gecen_dk = (simdi - son["ts"]).total_seconds() / 60.0
    oran = float(np.clip(gecen_dk / float(g.aralik_dk), float(g.min_oran), 1.0))

    if taban > 0:
        kat = float(son["volume"]) / (taban * oran)
        esik = float(g.min_hacim_kat) * (1.0 if taban_tip == "slot" else float(g.kaba_taban_carpani))
        if kat >= esik:
            ek = "" if oran >= 0.999 else f" (bar %{oran*100:.0f} tamamlandi, orantilandi)"
            tab = "" if taban_tip == "slot" else " [kaba taban]"
            sonuc.append({"tip": "hacim", "baslik": "Hacim patlamasi",
                          "detay": f"{son['slot']} barinda hacim, ayni saatin ortalamasinin {kat:.1f} kati{ek}{tab}",
                          "siddet": round(min(kat / float(g.min_hacim_kat), 3.0), 2)})

    if len(bugun_df) >= 5:
        onceki = float(bugun_df["close"].iloc[-5])
        if onceki > 0:
            hareket = (fiyat / onceki - 1) * 100
            if abs(hareket) >= float(g.min_hareket):
                yon = "yukari" if hareket > 0 else "asagi"
                sonuc.append({"tip": "hareket", "baslik": f"Ani fiyat hareketi ({yon})",
                              "detay": f"Son 1 saatte %{hareket:+.2f}",
                              "siddet": round(min(abs(hareket) / float(g.min_hareket), 3.0), 2)})

    dun_kapanis = float(onceki_df["close"].iloc[-1]) if len(onceki_df) else None

    if len(bugun_df) and dun_kapanis and dun_kapanis > 0:
        acilis = float(bugun_df["open"].iloc[0])
        gap = (acilis / dun_kapanis - 1) * 100
        if abs(gap) >= float(g.gap_esik):
            yon = "yukari" if gap > 0 else "asagi"
            sonuc.append({"tip": "gap", "baslik": f"Acilis boslugu ({yon})",
                          "detay": f"Acilis dunku kapanisa gore %{gap:+.2f} "
                                   f"(bedelsiz/temettu duzeltmesi olabilir - teyit et)",
                          "siddet": round(min(abs(gap) / float(g.gap_esik), 3.0), 2)})

    referans = gs_kapanis if (gs_kapanis and gs_kapanis > 0) else dun_kapanis
    if referans and referans > 0:
        gun_deg = (fiyat / referans - 1) * 100
        if abs(gun_deg) >= float(g.gun_esik):
            yon = "yukari" if gun_deg > 0 else "asagi"
            sonuc.append({"tip": "gunluk", "baslik": f"Gunluk sert hareket ({yon})",
                          "detay": f"Onceki kapanisa gore %{gun_deg:+.2f}",
                          "siddet": round(min(abs(gun_deg) / float(g.gun_esik), 3.0), 2)})

    if len(bugun_df) >= 6 and taban > 0:
        bar_ort = float(bugun_df["volume"].sum()) / len(bugun_df)
        yuksek = float(bugun_df["high"].max())
        dusuk = float(bugun_df["low"].min())
        gun_taban = float(onceki_df["volume"].tail(60).mean()) if len(onceki_df) >= 10 else taban
        if dusuk > 0 and gun_taban > 0:
            bant = (yuksek / dusuk - 1) * 100
            if bar_ort >= gun_taban * 1.8 and bant <= 1.5:
                sonuc.append({"tip": "birikim", "baslik": "Sessiz birikim",
                              "detay": f"Hacim ortalamanin {bar_ort/gun_taban:.1f} kati, fiyat bandi sadece %{bant:.1f}",
                              "siddet": round(min(bar_ort / gun_taban / 1.8, 3.0), 2)})

    # Tavan/taban kilidi: fiyat bandi neredeyse sifir ama hacim var
    if len(bugun_df) >= 4:
        son4 = bugun_df.tail(4)
        bant = (float(son4["high"].max()) / max(float(son4["low"].min()), 1e-9) - 1) * 100
        if bant < 0.15 and float(son4["volume"].sum()) > 0:
            sonuc.append({"tip": "kilit", "baslik": "Olasi tavan/taban kilidi",
                          "detay": "Son 1 saatte fiyat neredeyse hic oynamadi - emir defteri kilitli olabilir",
                          "siddet": 1.0})

    for a in sonuc:
        a["sym"] = sym
        a["fiyat"] = round(fiyat, 2)
        a["saat"] = son["ts"].tz_convert(AYAR.genel.tz).strftime("%H:%M")
        a["gun"] = str(son_gun)
        a["ts"] = son["ts"].isoformat()
    return sonuc


# ------------------------------------------------------------ durum / arsiv

def durum_yol():
    return yol_veri("intraday_state.json")


def arsiv_yol():
    return yol_veri("anomali_arsiv.csv")


def durum_oku(gun):
    try:
        with open(durum_yol(), encoding="utf-8") as fh:
            s = json.load(fh)
        if s.get("gun") == gun:
            return set(s.get("gonderilen", []))
    except Exception:
        pass
    return set()


def durum_yaz(gun, gonderilen):
    y = durum_yol()
    try:
        with open(y + ".tmp", "w", encoding="utf-8") as fh:
            json.dump({"gun": gun, "gonderilen": sorted(gonderilen)}, fh, ensure_ascii=False)
        os.replace(y + ".tmp", y)
    except Exception as ex:
        print("Durum dosyasi yazilamadi:", ex)


def arsivle(anomaliler):
    """Her tespiti loga yaz - sonradan 'bu anomaliler ne getirdi' diye olculur."""
    if not anomaliler or not AYAR.gunici.arsiv_aktif:
        return 0
    y = arsiv_yol()
    var = os.path.exists(y)
    mevcut = set()
    if var:
        try:
            with open(y, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    mevcut.add((r.get("gun"), r.get("sym"), r.get("tip")))
        except Exception:
            pass
    yeni = [a for a in anomaliler if (a.get("gun"), a.get("sym"), a.get("tip")) not in mevcut]
    if not yeni:
        return 0
    with open(y, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ARSIV_BASLIK)
        if not var:
            w.writeheader()
        for a in yeni:
            w.writerow({k: a.get(k, "") for k in ARSIV_BASLIK})
    return len(yeni)


def anomali_karnesi(ZEN, ufuklar=(1, 3, 5)):
    """Arsivlenen anomalilerden sonra fiyat ne yapmis?

    Anomali sekmesini bir alarm panosu olmaktan cikarip olculmus bir
    istatistige donusturen parca budur.
    """
    y = arsiv_yol()
    if not os.path.exists(y):
        return None
    try:
        with open(y, newline="", encoding="utf-8") as fh:
            kayitlar = list(csv.DictReader(fh))
    except Exception:
        return None
    if not kayitlar:
        return None

    gruplar = {}
    for r in kayitlar:
        sym, tip = r.get("sym"), r.get("tip")
        if sym not in ZEN:
            continue
        e = ZEN[sym]
        try:
            gun = pd.Timestamp(r["gun"]).normalize()
        except Exception:
            continue
        konum = e.index[e["date"] == gun]
        if len(konum) == 0:
            continue
        i = int(konum[0])
        acilis = e["open"].to_numpy(dtype=float)
        kapanis = e["close"].to_numpy(dtype=float)
        if i + 1 >= len(e) or acilis[i + 1] <= 0:
            continue
        for u in ufuklar:
            if i + u < len(e):
                g = (kapanis[i + u] / acilis[i + 1] - 1) * 100
                gruplar.setdefault((tip, u), []).append(g)

    from . import istatistik as ist
    out = []
    tipler = sorted({t for t, _ in gruplar})
    for t in tipler:
        satir = {"tip": t, "ufuk": {}}
        for u in ufuklar:
            g = gruplar.get((t, u))
            if not g:
                continue
            basari = sum(1 for x in g if x > 0)
            satir["ufuk"][str(u)] = {"adet": len(g),
                                     "isabet": ist.wilson(basari, len(g)),
                                     "ort": round(float(np.mean(g)), 2)}
        if satir["ufuk"]:
            out.append(satir)
    return out or None
