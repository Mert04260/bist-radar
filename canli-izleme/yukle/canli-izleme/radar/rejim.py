# -*- coding: utf-8 -*-
"""Piyasa rejimi, genislik (breadth) ve sektor gucu.

Hepsi *seri* olarak bir kez hesaplanir; hem gunluk kosu hem backtest ayni
tablodan tarih bazli okur. Boylece backtest'te gun basina yeniden hesap yok
ve iki mod arasinda tanim farki olusmuyor.
"""
import numpy as np
import pandas as pd

from .ayar import AYAR
from .evren import sektor


def rejim_serisi(endeks, ayar=None):
    """Endeks kapanis serisinden gunluk rejim tablosu."""
    ayar = ayar or AYAR
    if endeks is None or len(endeks) < 60:
        return None
    e = endeks.dropna()
    sma = e.rolling(int(ayar.rejim.endeks_sma)).mean()
    zirve = e.rolling(60).max()
    egim = sma.diff(10)
    dusus = e / zirve - 1

    t = pd.DataFrame({"kapanis": e, "sma": sma, "egim": egim, "dusus": dusus})
    puan = (
        (t["kapanis"] > t["sma"]).astype(float) * 40
        + (t["egim"] > 0).astype(float) * 30
        + np.clip((t["dusus"] + float(ayar.rejim.dusus_esigi)) / float(ayar.rejim.dusus_esigi), 0, 1) * 30
    )
    t["puan"] = puan.round(1)
    t["etiket"] = np.where(t["puan"] >= 70, "OLUMLU",
                           np.where(t["puan"] >= 40, "NOTR", "RISKLI"))
    t["degisim"] = (t["kapanis"].pct_change(fill_method=None) * 100).round(2)
    return t


def genislik_serisi(ZEN):
    """Evren genelinde gunluk katilim gostergeleri."""
    if not ZEN:
        return None
    kapanis, s20, s50, zirve = {}, {}, {}, {}
    for s, e in ZEN.items():
        idx = e["date"]
        kapanis[s] = pd.Series(e["close"].to_numpy(), index=idx)
        s20[s] = pd.Series(e["s20"].to_numpy(), index=idx)
        s50[s] = pd.Series(e["s50"].to_numpy(), index=idx)
        zirve[s] = pd.Series(e["zirve60"].to_numpy(), index=idx)
    K = pd.DataFrame(kapanis).sort_index()
    A20 = pd.DataFrame(s20).reindex(K.index)
    A50 = pd.DataFrame(s50).reindex(K.index)
    Z = pd.DataFrame(zirve).reindex(K.index)

    gecerli = K.notna().sum(axis=1).replace(0, np.nan)
    gunluk = K.pct_change(fill_method=None)
    t = pd.DataFrame(index=K.index)
    t["adet"] = K.notna().sum(axis=1)
    t["sma20_ust"] = ((K > A20).sum(axis=1) / gecerli * 100).round(1)
    t["sma50_ust"] = ((K > A50).sum(axis=1) / gecerli * 100).round(1)
    t["yukselen"] = ((gunluk > 0).sum(axis=1) / gecerli * 100).round(1)
    t["yeni_zirve"] = ((K >= Z * 0.999).sum(axis=1) / gecerli * 100).round(1)
    t["ad_orani"] = ((gunluk > 0).sum(axis=1) / (gunluk < 0).sum(axis=1).replace(0, np.nan)).round(2)
    return t


def sektor_serisi(ZEN, ayar=None):
    """Sektor bazli ortalama N gunluk getiri tablosu (tarih x sektor)."""
    ayar = ayar or AYAR
    if not ZEN or not ayar.sektor.aktif:
        return None
    pencere = int(ayar.sektor.rs_pencere)
    getiriler = {}
    for s, e in ZEN.items():
        getiriler[s] = pd.Series(
            e["close"].pct_change(pencere, fill_method=None).to_numpy(), index=e["date"])
    G = pd.DataFrame(getiriler).sort_index()
    gruplar = {}
    for s in G.columns:
        gruplar.setdefault(sektor(s), []).append(s)
    return pd.DataFrame({sk: G[kols].mean(axis=1) for sk, kols in gruplar.items()})


def gun_rejimi(rejim_t, genislik_t, gun, ayar=None):
    """Belirli bir gunun rejim ozeti + sinyal bastirma karari."""
    ayar = ayar or AYAR
    ozet = {"etiket": "OLUMLU", "puan": 100.0, "endeks_puan": None,
            "genislik_puan": None, "bastir": False, "kaynak": "yok"}
    if not ayar.rejim.aktif:
        return ozet

    e_puan = None
    if rejim_t is not None:
        alt = rejim_t.loc[rejim_t.index <= gun]
        if len(alt):
            e_puan = float(alt["puan"].iloc[-1])

    g_puan = None
    if genislik_t is not None:
        alt = genislik_t.loc[genislik_t.index <= gun]
        if len(alt) and np.isfinite(alt["sma20_ust"].iloc[-1]):
            g_puan = float(alt["sma20_ust"].iloc[-1])

    parcalar = [p for p in (e_puan, g_puan) if p is not None]
    if not parcalar:
        return ozet
    puan = float(np.mean(parcalar))
    ozet.update({
        "puan": round(puan, 1),
        "endeks_puan": round(e_puan, 1) if e_puan is not None else None,
        "genislik_puan": round(g_puan, 1) if g_puan is not None else None,
        "etiket": "OLUMLU" if puan >= 70 else ("NOTR" if puan >= 40 else "RISKLI"),
        "bastir": puan < float(ayar.rejim.bastirma_esigi),
        "kaynak": "endeks+genislik" if len(parcalar) == 2 else ("endeks" if e_puan is not None else "genislik"),
    })
    return ozet


def yogunlasma(semboller, ayar=None):
    """Secilen sinyaller sektor bazinda yiginlasmis mi?"""
    ayar = ayar or AYAR
    sayim = {}
    for s in semboller:
        sk = sektor(s)
        sayim[sk] = sayim.get(sk, 0) + 1
    if not sayim:
        return {"dagilim": {}, "uyari": None}
    enb = max(sayim.items(), key=lambda x: x[1])
    uyari = None
    if enb[1] >= int(ayar.sektor.yogunlasma_uyari):
        uyari = (f"{len(semboller)} sinyalin {enb[1]}'i {enb[0]} sektorunde - "
                 f"bu {enb[1]} ayri bahis degil, buyuk olcude tek bahis")
    return {"dagilim": sayim, "uyari": uyari}
