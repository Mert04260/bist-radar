# -*- coding: utf-8 -*-
"""Veri indirme ve onbellek katmani.

Onbellek mantigi:
  - Her sembol icin bir dosya (parquet varsa parquet, yoksa csv.gz).
  - Onbellek varsa yalnizca son N aylik pencere indirilir ve birlestirilir.
  - Ortusen barlarda fiyat farki tolerans disindaysa (temettu/bolunme sonrasi
    yeniden duzeltme) tam gecmis yeniden indirilir - yoksa seride sahte bir
    sicrama olusur ve butun gostergeler bozulur.
"""
import os
import time

import numpy as np
import pandas as pd

from .ayar import AYAR, yol_veri

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

GEREK = ["date", "open", "high", "low", "close", "volume"]

try:
    import pyarrow  # noqa: F401
    _PARQUET = True
except ImportError:
    _PARQUET = False


def _dizin():
    d = yol_veri(AYAR.veri.onbellek_dizin)
    os.makedirs(d, exist_ok=True)
    return d


def _yol(sym):
    uz = ".parquet" if _PARQUET else ".csv.gz"
    return os.path.join(_dizin(), sym + uz)


def onbellek_oku(sym):
    y = _yol(sym)
    if not os.path.exists(y):
        return None
    try:
        d = pd.read_parquet(y) if _PARQUET else pd.read_csv(y, compression="gzip")
        d["date"] = pd.to_datetime(d["date"])
        return d[GEREK].sort_values("date").reset_index(drop=True)
    except Exception:
        return None


def onbellek_yaz(sym, df):
    y = _yol(sym)
    gecici = y + ".tmp"
    try:
        if _PARQUET:
            df.to_parquet(gecici, index=False)
        else:
            df.to_csv(gecici, index=False, compression="gzip")
        os.replace(gecici, y)
    except Exception as ex:
        print(f"  onbellek yazilamadi ({sym}): {ex}")


def duzenle(df):
    """Ham yfinance cercevesini standart gunluk cerceveye cevirir."""
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance surumune ve group_by degerine gore alan adlari bazen 0.,
        # bazen son seviyede olur (('Close','AAA') vs ('AAA','Close')).
        # Seviyeyi varsaymak yerine OHLCV adlarini iceren seviyeyi buluyoruz.
        alanlar = {"open", "high", "low", "close", "volume", "adj close"}
        secili = 0
        for sv in range(df.columns.nlevels):
            adlar = {str(x).lower() for x in df.columns.get_level_values(sv)}
            if len(alanlar & adlar) >= 4:
                secili = sv
                break
        df.columns = [c[secili] for c in df.columns]
    df.columns = [str(c).lower() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    df = df.reset_index()
    df.columns = [str(c).lower() for c in df.columns]
    if "date" not in df.columns:
        for aday in ("datetime", "index"):
            if aday in df.columns:
                df = df.rename(columns={aday: "date"})
                break
    if not all(k in df.columns for k in GEREK):
        return None
    df = df[GEREK].dropna()
    if len(df) == 0:
        return None
    df["date"] = pd.to_datetime(df["date"])
    try:
        if getattr(df["date"].dt, "tz", None) is not None:
            df["date"] = df["date"].dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    df["date"] = df["date"].dt.normalize()
    return df.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def _indir(tickerlar, period, grup=True, deneme=2):
    if yf is None:
        return None
    for i in range(deneme):
        try:
            return yf.download(" ".join(tickerlar), period=period, auto_adjust=True,
                               progress=False, group_by="ticker" if grup else "column",
                               threads=len(tickerlar) > 1)
        except Exception:
            if i + 1 < deneme:
                time.sleep(1.5)
    return None


def tek_indir(tic, period=None, deneme=2):
    ham = _indir([tic], period or AYAR.veri.gecmis, grup=False, deneme=deneme)
    return duzenle(ham)


def _ortusme_uyumlu(eski, yeni, tolerans):
    """Ortusen tarihlerde kapanislar birbirini tutuyor mu?"""
    ort = eski.merge(yeni, on="date", suffixes=("_e", "_y"))
    if len(ort) < 3:
        return True, 0.0
    a = ort["close_e"].to_numpy(dtype=float)
    b = ort["close_y"].to_numpy(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        sapma = np.abs(b / np.where(a == 0, np.nan, a) - 1)
    en_buyuk = float(np.nanmax(sapma)) if len(sapma) else 0.0
    return en_buyuk <= tolerans, en_buyuk


def _birlestir(eski, yeni):
    b = pd.concat([eski, yeni], ignore_index=True)
    return b.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)


def eod_getir(semboller, zorla_tam=False, sessiz=False):
    """Sembol -> gunluk OHLCV cercevesi. Onbellegi kullanir, artimli tazeler.

    Donus: (veri_sozlugu, hatali_liste, istatistik_sozlugu)
    """
    ayar = AYAR.veri
    onbellek_var = bool(ayar.onbellek_aktif) and not zorla_tam
    veri, hatali = {}, []
    ist = {"onbellek": 0, "artimli": 0, "tam": 0, "yeniden_duzeltme": 0}

    onbellekler = {}
    tam_gerek, artimli_gerek = [], []
    for s in semboller:
        d = onbellek_oku(s) if onbellek_var else None
        if d is not None and len(d) >= ayar.min_bar:
            onbellekler[s] = d
            artimli_gerek.append(s)
        else:
            tam_gerek.append(s)

    def _kosu(liste, period, artimli):
        for i in range(0, len(liste), ayar.parca_boyu):
            parca = liste[i:i + ayar.parca_boyu]
            tickerlar = [s + ".IS" for s in parca]
            toplu = _indir(tickerlar, period)
            cok = toplu is not None and isinstance(toplu.columns, pd.MultiIndex)
            for s, tic in zip(parca, tickerlar):
                d = None
                if cok:
                    try:
                        if tic in toplu.columns.get_level_values(0):
                            d = duzenle(toplu[tic])
                    except Exception:
                        d = None
                elif toplu is not None and len(parca) == 1:
                    d = duzenle(toplu)
                if d is None:
                    d = tek_indir(tic, period)

                if artimli:
                    eski = onbellekler[s]
                    if d is None or len(d) == 0:
                        veri[s] = eski          # taze veri yok, onbellekle devam
                        ist["onbellek"] += 1
                        continue
                    uyumlu, sapma = _ortusme_uyumlu(eski, d, ayar.yeniden_duzeltme_tolerans)
                    if not uyumlu:
                        ist["yeniden_duzeltme"] += 1
                        if not sessiz:
                            print(f"  {s}: fiyatlar yeniden duzeltilmis (sapma %{sapma*100:.2f}) - tam yenileme")
                        tam = tek_indir(tic, ayar.gecmis)
                        if tam is not None and len(tam) >= ayar.min_bar:
                            veri[s] = tam
                            onbellek_yaz(s, tam)
                            ist["tam"] += 1
                            continue
                        veri[s] = eski
                        ist["onbellek"] += 1
                        continue
                    yeni = _birlestir(eski, d)
                    veri[s] = yeni
                    onbellek_yaz(s, yeni)
                    ist["artimli"] += 1
                else:
                    if d is not None and len(d) >= ayar.min_bar:
                        veri[s] = d
                        onbellek_yaz(s, d)
                        ist["tam"] += 1
                    else:
                        hatali.append(s)
            time.sleep(0.4)

    if artimli_gerek:
        _kosu(artimli_gerek, ayar.artimli_pencere, True)
    if tam_gerek:
        _kosu(tam_gerek, ayar.gecmis, False)

    # min_bar altinda kalanlari ele
    for s in list(veri):
        if len(veri[s]) < ayar.min_bar:
            hatali.append(s)
            veri.pop(s)
    return veri, hatali, ist


def endeks_getir():
    """XU100 kapanis serisi (onbellekli)."""
    tic = AYAR.veri.endeks
    ad = "_ENDEKS_" + tic.replace(".", "_")
    eski = onbellek_oku(ad) if AYAR.veri.onbellek_aktif else None
    yeni = tek_indir(tic, AYAR.veri.artimli_pencere if eski is not None else AYAR.veri.gecmis)
    if eski is not None and yeni is not None:
        uyumlu, _ = _ortusme_uyumlu(eski, yeni, AYAR.veri.yeniden_duzeltme_tolerans)
        d = _birlestir(eski, yeni) if uyumlu else (tek_indir(tic, AYAR.veri.gecmis) or eski)
    else:
        d = yeni if yeni is not None else eski
    if d is None or len(d) == 0:
        return None
    onbellek_yaz(ad, d)
    return d.set_index("date")["close"]
