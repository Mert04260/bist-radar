# -*- coding: utf-8 -*-
"""Kagit-uzerinde sinyal defteri (signals.csv)."""
import csv
import os

import numpy as np
import pandas as pd

from .ayar import AYAR, yol_veri

BASLIK = ["date", "sym", "sektor", "skor", "ham_skor", "rejim", "giris", "giris_tarih",
          "hedef", "stop", "cikis", "cikis_tipi", "cikis_tarih", "getiri",
          "endeks_getiri", "havuz_getiri", "sonuc"]
SAYISAL = ("skor", "ham_skor", "giris", "hedef", "stop", "cikis",
           "getiri", "endeks_getiri", "havuz_getiri")


def yol():
    return yol_veri("signals.csv")


def sayi(v):
    if v is None or v == "":
        return None
    try:
        s = float(v)
    except (TypeError, ValueError):
        return None
    return s if np.isfinite(s) else None


def oku():
    y = yol()
    if not os.path.exists(y):
        return [], False
    with open(y, newline="", encoding="utf-8") as fh:
        ham = list(csv.DictReader(fh))
    if ham and "giris_tarih" not in ham[0]:
        ars = yol_veri("signals_eski_arsiv.csv")
        try:
            os.replace(y, ars)
            print(f"UYARI: cok eski defter arsivlendi ({len(ham)} satir).")
        except OSError as ex:
            print("Arsivleme hatasi:", ex)
        return [], True
    temiz = []
    for s in ham:
        r = {k: s.get(k, "") for k in BASLIK}
        for k in SAYISAL:
            r[k] = sayi(r.get(k))
        r["date"] = str(s.get("date", "")).strip()
        r["sym"] = str(s.get("sym", "")).strip()
        temiz.append(r)
    return temiz, False


def yaz(satirlar):
    y = yol()
    gecici = y + ".tmp"
    with open(gecici, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=BASLIK)
        w.writeheader()
        for s in satirlar:
            w.writerow({k: ("" if s.get(k) is None else s.get(k, "")) for k in BASLIK})
    os.replace(gecici, y)


def cikis_tara(acilis, dusuk, yuksek, kapanis, i, giris, hedef, stop, ufuk, aktif=True):
    """Cikis mantiginin dizi tabanli cekirdegi.

    Canli akis da backtest de bu ayni fonksiyonu cagirir; iki tarafin
    birbirinden sapmasi boylece imkansiz hale gelir.

    - Anlamsiz seviyeler (hedef <= giris, stop >= giris) yok sayilir.
    - Ayni barda iki seviye de tetiklenirse muhafazakar davranilip STOP alinir.
    - Bar acilisi seviyeyi asmis geliyorsa cikis acilistan yapilir.
    """
    if i + ufuk >= len(kapanis):
        return None
    if hedef is not None and hedef <= giris:
        hedef = None
    if stop is not None and stop >= giris:
        stop = None
    if aktif:
        for j in range(i + 1, i + ufuk + 1):
            if stop is not None and dusuk[j] <= stop:
                return round(min(stop, float(acilis[j])), 2), "STOP", j
            if hedef is not None and yuksek[j] >= hedef:
                return round(float(acilis[j]) if acilis[j] > hedef else hedef, 2), "HEDEF", j
    j = i + ufuk
    return round(float(kapanis[j]), 2), "SURE", j


def cikis_bul(e, i, giris, hedef, stop, ayar=None):
    ayar = ayar or AYAR
    return cikis_tara(e["open"].to_numpy(dtype=float), e["low"].to_numpy(dtype=float),
                      e["high"].to_numpy(dtype=float), e["close"].to_numpy(dtype=float),
                      i, giris, hedef, stop, int(ayar.skor.ufuk),
                      bool(ayar.skor.stop_hedef_aktif))


def cipala(hedef, stop, kapanis_sinyal, giris):
    """Hedef/stop sinyal kapanisina gore hesaplanir; girise yeniden cipalanir.

    Gece gap'inde seviyeler girise gore anlamsiz kalabiliyor; ayni yuzde
    mesafe korunarak gercek giris fiyatina tasinir.
    """
    if not kapanis_sinyal or kapanis_sinyal <= 0:
        return hedef, stop
    yeni = []
    for v in (hedef, stop):
        yeni.append(round(v / kapanis_sinyal * giris, 2) if v else v)
    return yeni[0], yeni[1]


def havuz_getirisi(ZEN, sinyal_g, ayar=None):
    """O gun filtreleri gecen TUM adaylarin ortalama ileri getirisi.

    "Secmeseydin ne olurdu" sorusunun cevabi. Backtest'te bu her gun
    hesaplaniyordu; canli defterde de olmasi lazim, yoksa karnede
    karsilastirma yapilamiyor.
    """
    ayar = ayar or AYAR
    ufuk = int(ayar.skor.ufuk)
    min_tl = float(ayar.skor.min_islem_tl)
    getiriler = []
    for e in ZEN.values():
        konum = e.index[e["date"] == sinyal_g]
        if len(konum) == 0:
            continue
        i = int(konum[0])
        if i + ufuk >= len(e):
            continue
        tl = e["islem_tl"].iloc[i]
        if not np.isfinite(tl) or tl < min_tl:
            continue
        acilis = float(e["open"].iloc[i + 1])
        if acilis <= 0:
            continue
        getiriler.append(float(e["close"].iloc[i + ufuk]) / acilis - 1)
    return round(float(np.mean(getiriler)) * 100, 2) if getiriler else None


def izle(satirlar, ZEN, piyasa_gunu, endeks=None, ayar=None):
    """Bekleyen sinyalleri doldurur/kapatir. Yerinde degistirir."""
    ayar = ayar or AYAR
    _havuz = {}
    for satir in satirlar:
        if satir.get("sonuc"):
            continue
        sym = satir["sym"]
        try:
            sinyal_g = pd.Timestamp(satir["date"]).normalize()
        except Exception:
            continue
        yas = (piyasa_gunu - sinyal_g).days

        if sym not in ZEN:
            if yas > int(ayar.skor.veri_yok_gun):
                satir["sonuc"] = "VERI_YOK"
                satir["cikis_tipi"] = "VERI_YOK"
            continue
        e = ZEN[sym]
        konum = e.index[e["date"] == sinyal_g]
        if len(konum) == 0:
            if yas > int(ayar.skor.veri_yok_gun):
                satir["sonuc"] = "VERI_YOK"
                satir["cikis_tipi"] = "VERI_YOK"
            continue
        i = int(konum[0])

        if satir.get("giris") is None:
            if i + 1 >= len(e):
                continue
            acilis = float(e["open"].iloc[i + 1])
            if acilis <= 0:
                satir["sonuc"] = "VERI_YOK"
                satir["cikis_tipi"] = "VERI_YOK"
                continue
            satir["giris"] = round(acilis, 2)
            satir["giris_tarih"] = str(e["date"].iloc[i + 1].date())
            satir["hedef"], satir["stop"] = cipala(
                satir.get("hedef"), satir.get("stop"), float(e["close"].iloc[i]), acilis)

        giris = float(satir["giris"])
        if giris <= 0:
            satir["sonuc"] = "VERI_YOK"
            satir["cikis_tipi"] = "VERI_YOK"
            continue

        bulunan = cikis_bul(e, i, giris, satir.get("hedef"), satir.get("stop"), ayar)
        if bulunan is None:
            continue
        cikis, tip, j = bulunan
        getiri = (cikis / giris - 1) * 100
        satir["cikis"] = cikis
        satir["cikis_tipi"] = tip
        satir["cikis_tarih"] = str(e["date"].iloc[j].date())
        satir["getiri"] = round(getiri, 2)
        satir["sonuc"] = "ISABET" if getiri > 0 else "ISKA"

        if endeks is not None and satir.get("endeks_getiri") is None:
            try:
                g0 = e["date"].iloc[i + 1]
                g1 = e["date"].iloc[j]
                alt = endeks.loc[(endeks.index >= g0) & (endeks.index <= g1)].dropna()
                if len(alt) >= 2 and float(alt.iloc[0]) > 0:
                    satir["endeks_getiri"] = round((float(alt.iloc[-1]) / float(alt.iloc[0]) - 1) * 100, 2)
            except Exception:
                pass

        if satir.get("havuz_getiri") is None:
            if sinyal_g not in _havuz:
                _havuz[sinyal_g] = havuz_getirisi(ZEN, sinyal_g, ayar)
            satir["havuz_getiri"] = _havuz[sinyal_g]
    return satirlar


def bolumle(satirlar):
    biten = [x for x in satirlar if x.get("sonuc") in ("ISABET", "ISKA")]
    iptal = [x for x in satirlar if x.get("sonuc") == "VERI_YOK"]
    bekleyen = [x for x in satirlar if not x.get("sonuc")]
    return biten, bekleyen, iptal
