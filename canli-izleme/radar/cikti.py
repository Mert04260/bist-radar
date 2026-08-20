# -*- coding: utf-8 -*-
"""JSON cikti katmani - frontend'in okudugu veri sozlesmesi.

data.json su sekmeleri besler:
  radar        -> mevcut ana ekran (gunun sinyalleri)
  piyasa       -> Piyasa Nabzi sekmesi (rejim, genislik, sektor isi haritasi)
  detay        -> Hisse Detayi sekmesi (sembol bazli drill-down)
  performans   -> Performans sekmesi (equity, guven arali, dilim analizi)
  arsiv        -> Arsiv sekmesi (tum gecmis sinyaller)
  saglik       -> Sistem Sagligi sekmesi (veri tazeligi, kapsama)
Her bolum bagimsizdir; frontend sadece ihtiyaci olani okuyabilir.
"""
import json
import os

import numpy as np
import pandas as pd

from .ayar import AYAR


def yaz(yol, nesne):
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as fh:
        json.dump(nesne, fh, ensure_ascii=False, indent=1, default=_donustur)
    os.replace(gecici, yol)
    return yol


def _donustur(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return str(o.date())
    return str(o)


def piyasa_bolumu(rejim_t, genislik_t, sektor_t, gun, yogun=None):
    """Piyasa Nabzi sekmesi."""
    out = {"rejim": None, "genislik": None, "sektor": [], "yogunlasma": yogun}
    if rejim_t is not None:
        alt = rejim_t.loc[rejim_t.index <= gun]
        if len(alt):
            s = alt.iloc[-1]
            out["rejim"] = {
                "etiket": str(s["etiket"]), "puan": float(s["puan"]),
                "degisim": None if pd.isna(s["degisim"]) else float(s["degisim"]),
                "sma_ustunde": bool(s["kapanis"] > s["sma"]) if pd.notna(s["sma"]) else None,
                "zirveden": None if pd.isna(s["dusus"]) else round(float(s["dusus"]) * 100, 2),
                "seri": [round(float(x), 1) for x in alt["kapanis"].tail(60).tolist()],
                "puan_seri": [float(x) for x in alt["puan"].tail(60).tolist()],
                "tarihler": [str(pd.Timestamp(t).date()) for t in alt.index[-60:]],
            }
    if genislik_t is not None:
        alt = genislik_t.loc[genislik_t.index <= gun]
        if len(alt):
            s = alt.iloc[-1]
            out["genislik"] = {
                "sma20_ust": None if pd.isna(s["sma20_ust"]) else float(s["sma20_ust"]),
                "sma50_ust": None if pd.isna(s["sma50_ust"]) else float(s["sma50_ust"]),
                "yukselen": None if pd.isna(s["yukselen"]) else float(s["yukselen"]),
                "yeni_zirve": None if pd.isna(s["yeni_zirve"]) else float(s["yeni_zirve"]),
                "ad_orani": None if pd.isna(s["ad_orani"]) else float(s["ad_orani"]),
                "seri": [None if pd.isna(x) else float(x) for x in alt["sma20_ust"].tail(60).tolist()],
            }
    if sektor_t is not None:
        alt = sektor_t.loc[sektor_t.index <= gun]
        if len(alt):
            son = alt.iloc[-1].dropna().sort_values(ascending=False)
            out["sektor"] = [{"ad": str(k), "getiri": round(float(v) * 100, 2)}
                             for k, v in son.items()]
    return out


def detay_bolumu(ZEN, semboller, sim_al, ayar=None):
    """Hisse Detayi sekmesi - sembol bazli drill-down verisi."""
    ayar = ayar or AYAR
    n = int(ayar.cikti.seri_uzunluk)
    out = {}
    for s in semboller:
        e = ZEN.get(s)
        if e is None or len(e) == 0:
            continue
        r = e.iloc[-1]
        sim = sim_al(s)
        kuyruk = e.tail(n)
        out[s] = {
            "tarihler": [str(pd.Timestamp(t).date()) for t in kuyruk["date"]],
            "kapanis": [round(float(x), 2) for x in kuyruk["close"]],
            "hacim": [float(x) for x in kuyruk["volume"]],
            "s20": [None if pd.isna(x) else round(float(x), 2) for x in kuyruk["s20"]],
            "s50": [None if pd.isna(x) else round(float(x), 2) for x in kuyruk["s50"]],
            "gosterge": {
                "rsi": None if pd.isna(r["rsi"]) else round(float(r["rsi"]), 1),
                "mfi": None if pd.isna(r["mfi"]) else round(float(r["mfi"]), 1),
                "cmf": None if pd.isna(r["cmf"]) else round(float(r["cmf"]), 3),
                "atr": None if pd.isna(r["atr"]) else round(float(r["atr"]), 2),
                "vr": None if pd.isna(r["vr"]) else round(float(r["vr"]), 2),
                "rs": None if pd.isna(r["rs"]) else round(float(r["rs"]) * 100, 2),
                "rs_sektor": None if pd.isna(r.get("rs_sektor", np.nan)) else round(float(r["rs_sektor"]) * 100, 2),
            },
            "benzer": sim,
        }
    return out


def performans_bolumu(biten, ayar=None):
    """Performans sekmesi - karne, equity, guven araliklari, dilim analizi."""
    from . import istatistik as ist
    if not biten:
        return {"karne": None, "yorum": "Henuz kapanmis sinyal yok."}
    kayitlar = [dict(x) for x in biten if x.get("getiri") is not None]
    for k in kayitlar:
        k["getiri"] = float(k["getiri"])
    getiriler = [k["getiri"] for k in kayitlar]
    basari = sum(1 for x in getiriler if x > 0)
    sirali = sorted(kayitlar, key=lambda z: (z.get("cikis_tarih") or z["date"]))
    karsi = ist.karsilastirma(kayitlar)
    return {
        "karne": {
            "adet": len(kayitlar),
            "isabet": ist.wilson(basari, len(kayitlar)),
            "getiri": ist.ortalama_ci(getiriler),
            "profil": ist.profil(getiriler),
        },
        "equity": ist.equity(sirali, int((ayar or AYAR).skor.ufuk)),
        "karsilastirma": karsi,
        "yorum": ist.yorumla(karsi),
        "skor_dilimi": ist.dilim_analizi(kayitlar),
        "rejim_kirilim": ist.kirilim(kayitlar, "rejim"),
        "sektor_kirilim": ist.kirilim(kayitlar, "sektor")[:12],
        "cikis_kirilim": ist.kirilim(kayitlar, "cikis_tipi"),
    }


def arsiv_bolumu(satirlar, limit=400):
    """Arsiv sekmesi - tum sinyaller, frontend'de filtrelenebilir."""
    alanlar = ("date", "sym", "sektor", "skor", "rejim", "giris", "giris_tarih",
               "hedef", "stop", "cikis", "cikis_tipi", "cikis_tarih",
               "getiri", "endeks_getiri", "sonuc")
    return [{k: s.get(k) for k in alanlar} for s in satirlar][-limit:]


def saglik_bolumu(ist_veri, hatali, bayat, likit_disi, iptal, ek=None):
    """Sistem Sagligi sekmesi."""
    out = {
        "onbellek": ist_veri.get("onbellek", 0),
        "artimli": ist_veri.get("artimli", 0),
        "tam_indirme": ist_veri.get("tam", 0),
        "yeniden_duzeltme": ist_veri.get("yeniden_duzeltme", 0),
        "alinamayan": len(hatali),
        "alinamayan_liste": sorted(hatali)[:30],
        "bayat_sembol": len(bayat),
        "likit_disi": len(likit_disi),
        "iptal_sinyal": iptal,
    }
    if ek:
        out.update(ek)
    return out
