# -*- coding: utf-8 -*-
"""Walk-forward backtest.

Tasarim kurallari:
  - Her gun yalnizca o gune kadarki veriyle skorlanir; ileri bakis yok.
    (Gostergelerdeki shift(1) ve benzer_gun'un e.iloc[:i] siniri bunu saglar.)
  - Giris ertesi acilis, cikis stop/hedef/sure - canli sistemle ayni cekirdek.
  - Her sinyalin yaninda iki benchmark kaydedilir:
      endeks_getiri : ayni pencerede XU100
      havuz_getiri  : o gun filtreleri gecen TUM adaylarin ortalama getirisi
    Ikincisi kritik: "secmek" gercekten deger katiyor mu sorusunun cevabi.
  - Islem maliyeti (komisyon + kayma) net getiride dusulur.
"""
import numpy as np
import pandas as pd

from .ayar import AYAR
from .defter import cikis_tara
from .evren import sektor
from .rejim import gun_rejimi
from .skor import benzer_gun, rejim_uygula, skorla
from . import istatistik as ist

ALANLAR = ("open", "high", "low", "close", "rsi", "s20", "s50", "vr", "vz",
           "islem_tl", "mfi", "cmf", "kap_yeri", "bm", "macd", "macd_sig",
           "mh", "atr", "ext", "mom5", "rs", "rs_sektor")


def _diziler(ZEN):
    paket = {}
    for s, e in ZEN.items():
        d = {a: e[a].to_numpy(dtype=float) for a in ALANLAR if a in e.columns}
        d["_tarih"] = e["date"].to_numpy()
        d["_konum"] = {t: i for i, t in enumerate(e["date"])}
        paket[s] = d
    return paket


def _satir(d, i):
    return {a: d[a][i] for a in ALANLAR if a in d}


def calistir(ZEN, endeks=None, rejim_t=None, genislik_t=None, ayar=None,
             rejim_zorla=None, baslangic=None, ilerleme=True):
    ayar = ayar or AYAR
    ufuk = int(ayar.skor.ufuk)
    esik = float(ayar.skor.esik)
    max_secim = int(ayar.skor.max_secim)
    min_tl = float(ayar.skor.min_islem_tl)
    maliyet = 2 * (float(ayar.backtest.komisyon_bps) + float(ayar.backtest.kayma_bps)) / 100.0

    paket = _diziler(ZEN)
    gunler = sorted({t for d in paket.values() for t in d["_konum"]})
    isinma = int(ayar.backtest.isinma_bar)
    bas = baslangic or ayar.backtest.baslangic
    ilk = isinma
    if bas:
        hedef_g = pd.Timestamp(bas)
        ilk = max(ilk, next((k for k, g in enumerate(gunler) if g >= hedef_g), ilk))
    son = len(gunler) - ufuk - 1
    if son <= ilk:
        return {"hata": "Backtest icin yeterli gecmis yok."}

    kayitlar, gun_ozet = [], []
    bastirilan = 0
    for k in range(ilk, son):
        gun = gunler[k]
        rej = gun_rejimi(rejim_t, genislik_t, gun, ayar)
        if rejim_zorla is not None:
            rej = dict(rej)
            rej["bastir"] = False if rejim_zorla == "kapali" else rej["bastir"]

        adaylar = []
        havuz = []
        for s, d in paket.items():
            i = d["_konum"].get(gun)
            if i is None or i + ufuk >= len(d["close"]) or i < 60:
                continue
            if not np.isfinite(d["rsi"][i]) or not np.isfinite(d["s50"][i]):
                continue
            if not np.isfinite(d["islem_tl"][i]) or d["islem_tl"][i] < min_tl:
                continue
            giris_h = d["open"][i + 1]
            if giris_h <= 0:
                continue
            havuz.append(d["close"][i + ufuk] / giris_h - 1)
            r = _satir(d, i)
            f = skorla(r, ayar)
            if rejim_zorla != "kapali":
                rejim_uygula(f, rej["etiket"], ayar)
            else:
                f["ceza"] = 0.0
            adaylar.append((f["S"], s, f, i))

        havuz_ort = float(np.mean(havuz)) * 100 if havuz else None
        endeks_g = None
        if endeks is not None:
            try:
                pencere = endeks.loc[(endeks.index >= gunler[k + 1]) & (endeks.index <= gunler[k + ufuk])].dropna()
                if len(pencere) >= 2 and float(pencere.iloc[0]) > 0:
                    endeks_g = (float(pencere.iloc[-1]) / float(pencere.iloc[0]) - 1) * 100
            except Exception:
                endeks_g = None

        gun_ozet.append({"date": str(pd.Timestamp(gun).date()), "aday": len(adaylar),
                         "rejim": rej["etiket"], "rejim_puan": rej["puan"],
                         "havuz": round(havuz_ort, 2) if havuz_ort is not None else None})

        if rej.get("bastir"):
            bastirilan += 1
            continue

        adaylar.sort(key=lambda x: (-x[0], x[1]))
        secilen = [a for a in adaylar if a[0] >= esik][:max_secim]

        for skorv, sym, f, i in secilen:
            d = paket[sym]
            e = ZEN[sym]
            sim = benzer_gun(e, i, ayar)
            giris = float(d["open"][i + 1])
            hedef = stop = None
            if sim:
                kap = float(d["close"][i])
                hedef = round(kap * (1 + sim["avg_up"] / 100), 2)
                stop = round(kap * (1 - sim["avg_dn"] / 100), 2)
                # canli sistemdeki gibi girise cipala
                if kap > 0:
                    hedef = round(hedef / kap * giris, 2)
                    stop = round(stop / kap * giris, 2)
            bulunan = cikis_tara(d["open"], d["low"], d["high"], d["close"], i,
                                 giris, hedef, stop, ufuk,
                                 bool(ayar.skor.stop_hedef_aktif))
            if bulunan is None:
                continue
            cikis, tip, j = bulunan
            brut = (cikis / giris - 1) * 100
            kayitlar.append({
                "date": str(pd.Timestamp(gun).date()),
                "sym": sym, "sektor": sektor(sym),
                "skor": float(skorv), "ham_skor": float(f["ham"]),
                "rejim": rej["etiket"],
                "giris": round(giris, 2), "cikis": cikis, "cikis_tipi": tip,
                "getiri": round(brut, 2),
                "net_getiri": round(brut - maliyet, 2),
                "endeks_getiri": round(endeks_g, 2) if endeks_g is not None else None,
                "havuz_getiri": round(havuz_ort, 2) if havuz_ort is not None else None,
                "sim_epizot": sim["epizot"] if sim else None,
            })
        if ilerleme and (k - ilk) % 100 == 0:
            print(f"  ... {pd.Timestamp(gun).date()} | islem: {len(kayitlar)}")

    return _ozetle(kayitlar, gun_ozet, gunler[ilk], gunler[son - 1], bastirilan, ayar)


def _ozetle(kayitlar, gun_ozet, ilk_gun, son_gun, bastirilan, ayar):
    if not kayitlar:
        return {"hata": "Hic islem uretilmedi - esikler cok siki olabilir.",
                "gun": len(gun_ozet), "bastirilan_gun": bastirilan}

    brut = [k["getiri"] for k in kayitlar]
    net = [k["net_getiri"] for k in kayitlar]
    basari = sum(1 for x in brut if x > 0)

    risksiz = [k for k in kayitlar if k["rejim"] != "RISKLI"]
    ab = None
    if risksiz and len(risksiz) != len(kayitlar):
        rb = [k["getiri"] for k in risksiz]
        ab = {
            "tum": {"adet": len(kayitlar), "isabet": ist.wilson(basari, len(kayitlar)),
                    "ort": round(float(np.mean(brut)), 2)},
            "riskli_haric": {"adet": len(risksiz),
                             "isabet": ist.wilson(sum(1 for x in rb if x > 0), len(rb)),
                             "ort": round(float(np.mean(rb)), 2)},
        }

    return {
        "donem": {"bas": str(pd.Timestamp(ilk_gun).date()),
                  "son": str(pd.Timestamp(son_gun).date()),
                  "gun": len(gun_ozet), "bastirilan_gun": bastirilan},
        "adet": len(kayitlar),
        "isabet": ist.wilson(basari, len(kayitlar)),
        "getiri": ist.ortalama_ci(brut),
        "net_getiri": ist.ortalama_ci(net),
        "maliyet_bps": 2 * (float(ayar.backtest.komisyon_bps) + float(ayar.backtest.kayma_bps)),
        "profil": ist.profil(brut),
        "equity": ist.equity(kayitlar, int(ayar.skor.ufuk),
                             float(ayar.backtest.sermaye), alan="net_getiri"),
        "karsilastirma": ist.karsilastirma(kayitlar),
        "yorum": ist.yorumla(ist.karsilastirma(kayitlar)),
        "skor_dilimi": ist.dilim_analizi(kayitlar),
        "rejim_kirilim": ist.kirilim(kayitlar, "rejim"),
        "sektor_kirilim": ist.kirilim(kayitlar, "sektor")[:12],
        "cikis_kirilim": ist.kirilim(kayitlar, "cikis_tipi"),
        "rejim_ab": ab,
        "islemler": kayitlar[-300:],
        "gun_ozet": gun_ozet[-500:],
    }
