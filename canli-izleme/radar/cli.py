# -*- coding: utf-8 -*-
"""Komut satiri ve akis orkestrasyonu."""
import argparse
import json
import sys

import numpy as np
import pandas as pd

from . import backtest as bt
from . import cikti, defter, gunici, istatistik as ist, rejim as rj, veri as vr
from .ayar import AYAR, cikti_yolu, yukle
from .bildirim import telegram
from .evren import SEMBOLLER, sektor
from .gostergeler import sayi as _s, zenginlestir
from .skor import benzer_gun, rejim_uygula, sebepler, skorla


# ------------------------------------------------------------------ ortak

def veri_hazirla(semboller, ayar, zorla_tam=False):
    """Indirme + gosterge + rejim/genislik/sektor tablolari."""
    print(f"Veri hazirlaniyor ({len(semboller)} sembol)...")
    VERI, hatali, istv = vr.eod_getir(semboller, zorla_tam=zorla_tam)
    print(f"  onbellek: {istv['onbellek']} | artimli: {istv['artimli']} | "
          f"tam: {istv['tam']} | alinamayan: {len(hatali)}")
    if not VERI:
        return None
    endeks = vr.endeks_getir()
    if endeks is None:
        print("UYARI: endeks alinamadi - goreceli guc ve rejim sinirli calisacak.")

    # sektor serisi icin once kaba bir zenginlestirme gerekmez; sektor getirisi
    # dogrudan kapanislardan hesaplanir
    ZEN = {}
    for s, df in VERI.items():
        es = endeks.reindex(df["date"]).reset_index(drop=True) if endeks is not None else None
        ZEN[s] = zenginlestir(df, es)

    sektor_t = rj.sektor_serisi(ZEN, ayar)
    if sektor_t is not None:
        # sektore gore goreceli guc icin ikinci gecis
        for s, e in ZEN.items():
            sk = sektor(s)
            if sk in sektor_t.columns:
                ss = sektor_t[sk].reindex(e["date"]).reset_index(drop=True)
                e["rs_sektor"] = e["close"].pct_change(int(ayar.sektor.rs_pencere),
                                                       fill_method=None) - ss

    rejim_t = rj.rejim_serisi(endeks, ayar)
    genislik_t = rj.genislik_serisi(ZEN)
    return {"ZEN": ZEN, "endeks": endeks, "hatali": hatali, "ist": istv,
            "rejim_t": rejim_t, "genislik_t": genislik_t, "sektor_t": sektor_t}


# --------------------------------------------------------------- gun sonu

def gun_sonu(ayar, test_modu=False, sembol_limit=None, zorla_tam=False):
    sem = SEMBOLLER if not sembol_limit else SEMBOLLER[:sembol_limit]
    h = veri_hazirla(sem, ayar, zorla_tam)
    if h is None:
        print("HATA: hicbir sembol indirilemedi.")
        return 1
    ZEN, endeks = h["ZEN"], h["endeks"]

    piyasa_gunu = pd.Series([e["date"].iloc[-1] for e in ZEN.values()]).mode().iloc[0]
    bugun = piyasa_gunu.date()
    rej = rj.gun_rejimi(h["rejim_t"], h["genislik_t"], piyasa_gunu, ayar)
    print(f"  piyasa rejimi: {rej['etiket']} ({rej['puan']}) | kaynak: {rej['kaynak']}")

    adaylar, bayat, likit_disi = [], [], []
    for s, e in ZEN.items():
        r = e.iloc[-1]
        if r["date"] != piyasa_gunu:
            bayat.append(s)
            continue
        if not np.isfinite(_s(r["rsi"], np.nan)) or not np.isfinite(_s(r["s50"], np.nan)):
            continue
        if _s(r["islem_tl"], 0) < float(ayar.skor.min_islem_tl):
            likit_disi.append(s)
            continue
        f = rejim_uygula(skorla(r, ayar), rej["etiket"], ayar)
        adaylar.append((f["S"], s, f, r))
    adaylar.sort(key=lambda x: (-x[0], x[1]))

    secilen = [] if rej.get("bastir") else [a for a in adaylar if a[0] >= float(ayar.skor.esik)][:int(ayar.skor.max_secim)]
    print(f"  taranan: {len(adaylar)} | bayat: {len(bayat)} | likit disi: {len(likit_disi)} "
          f"| secilen: {len(secilen)}")

    _cache = {}

    def sim_al(sym):
        if sym not in _cache:
            try:
                _cache[sym] = benzer_gun(ZEN[sym], len(ZEN[sym]) - 1, ayar)
            except Exception:
                _cache[sym] = None
        return _cache[sym]

    # havuz getirisi: bugun icin henuz bilinmiyor, gecmis satirlar izlemede dolar
    satirlar, arsivlendi = defter.oku()
    mevcut = {(x["date"], x["sym"]) for x in satirlar}
    for skorv, sym, f, r in secilen:
        if (str(bugun), sym) in mevcut:
            continue
        sim = sim_al(sym)
        kap = float(r["close"])
        satirlar.append({
            "date": str(bugun), "sym": sym, "sektor": sektor(sym),
            "skor": skorv, "ham_skor": f["ham"], "rejim": rej["etiket"],
            "giris": None, "giris_tarih": "",
            "hedef": round(kap * (1 + sim["avg_up"] / 100), 2) if sim else None,
            "stop": round(kap * (1 - sim["avg_dn"] / 100), 2) if sim else None,
            "cikis": None, "cikis_tipi": "", "cikis_tarih": "",
            "getiri": None, "endeks_getiri": None, "havuz_getiri": None, "sonuc": "",
        })

    defter.izle(satirlar, ZEN, piyasa_gunu, endeks, ayar)
    defter.yaz(satirlar)
    biten, bekleyen, iptal = defter.bolumle(satirlar)

    yogun = rj.yogunlasma([s for _, s, _, _ in secilen], ayar)

    # ---- Telegram
    msg = f"MERT RADAR | {bugun}\nRejim: {rej['etiket']} ({rej['puan']}/100)\n"
    msg += f"Taranan: {len(adaylar)} -> Secilen: {len(secilen)}\n\n"
    if rej.get("bastir"):
        msg += "PIYASA REJIMI RISKLI - sinyal uretimi bastirildi.\n"
    elif not secilen:
        msg += "BUGUN ISLEM YAPMA - hicbir hisse esigi gecemedi.\n"
        if adaylar:
            msg += f"En yuksek: {adaylar[0][1]} {adaylar[0][0]}/100\n"
    else:
        for skorv, sym, f, r in secilen:
            atr = _s(r["atr"], 3)
            risk = "Dusuk" if atr < 2.5 else ("Orta" if atr < 4.5 else "Yuksek")
            im = "*" if skorv >= float(ayar.skor.guven_esik) else "-"
            msg += f"{im} {sym} {skorv}/100 | {risk} | {float(r['close']):.2f}\n"
        msg += f"\n* = {ayar.skor.guven_esik}+ guven dilimi\nGiris ertesi acilistan varsayilir.\n"
    if yogun.get("uyari"):
        msg += f"\nUYARI: {yogun['uyari']}\n"
    if biten:
        g = [float(x["getiri"]) for x in biten]
        w = ist.wilson(sum(1 for x in g if x > 0), len(g))
        msg += (f"\nKARNE ({len(biten)} kapanan, {len(bekleyen)} bekleyen)\n"
                f"Isabet: %{w['oran']} (guven araligi %{w['alt']}-%{w['ust']})\n"
                f"Ort. getiri: %{float(np.mean(g)):+.2f}\n")
        if len(biten) < 30:
            msg += "Not: 30 islemin altinda karne guvenilir degildir.\n"
    if endeks is None:
        msg += "\nUYARI: Endeks alinamadi.\n"
    if arsivlendi:
        msg += "\nEski defter arsivlendi. Karne sifirdan basliyor.\n"
    msg += "\nYatirim tavsiyesi degildir. Kagit-uzerinde izleme modu."
    print(msg)
    if not test_modu:
        telegram(msg)

    # ---- data.json
    radar = []
    for skorv, sym, f, r in secilen:
        sim = sim_al(sym)
        atr = _s(r["atr"], 3)
        kap = float(r["close"])
        radar.append({
            "sym": sym, "sektor": sektor(sym), "skor": float(skorv),
            "ham_skor": float(f["ham"]), "ceza": float(f.get("ceza", 0.0)),
            "risk": "Dusuk" if atr < 2.5 else ("Orta" if atr < 4.5 else "Yuksek"),
            "fiyat": round(kap, 2), "guven": bool(skorv >= float(ayar.skor.guven_esik)),
            "faktor": {"Trend": f["T"], "Hacim": f["H"], "Para": f["P"], "Teknik": f["K"]},
            "sebep": sebepler(r, sim, f),
            "benzer": sim,
            "hedef": round(kap * (1 + sim["avg_up"] / 100), 2) if sim else None,
            "stop": round(kap * (1 - sim["avg_dn"] / 100), 2) if sim else None,
            "seri": [round(float(x), 2) for x in ZEN[sym]["close"].tail(int(ayar.cikti.seri_uzunluk))],
        })

    detay_semboller = sorted({s for _, s, _, _ in secilen} |
                             {x["sym"] for x in satirlar[-40:] if x["sym"] in ZEN})
    endeks_obj = None
    if endeks is not None:
        iv = endeks.dropna()
        if len(iv) > 31:
            endeks_obj = {"degisim": round(float(iv.iloc[-1] / iv.iloc[-2] - 1) * 100, 2),
                          "seri": [round(float(x), 1) for x in iv.tail(60).tolist()]}

    web = {
        "surum": ayar.genel.surum,
        "mod": "gun-sonu",
        "guncelleme": pd.Timestamp.now(tz="UTC").tz_convert(AYAR.genel.tz).strftime("%d.%m.%Y %H:%M"),
        "tarih": str(bugun),
        "ufuk": int(ayar.skor.ufuk),
        "esik": float(ayar.skor.esik),
        "stop_hedef": bool(ayar.skor.stop_hedef_aktif),
        "taranan": len(adaylar),
        "evren": len(sem),
        "endeks": endeks_obj,
        "radar": radar,
        "piyasa": cikti.piyasa_bolumu(h["rejim_t"], h["genislik_t"], h["sektor_t"],
                                      piyasa_gunu, yogun),
        "detay": cikti.detay_bolumu(ZEN, detay_semboller, sim_al, ayar),
        "performans": cikti.performans_bolumu(biten, ayar),
        "arsiv": cikti.arsiv_bolumu(satirlar),
        "saglik": cikti.saglik_bolumu(h["ist"], h["hatali"], bayat, likit_disi, len(iptal),
                                      {"defter_arsivlendi": arsivlendi,
                                       "bekleyen": len(bekleyen),
                                       "rejim_bastirdi": bool(rej.get("bastir"))}),
        "anomali_karne": gunici.anomali_karnesi(ZEN),
        # geriye donuk uyumluluk (mevcut frontend bunlari okuyor)
        "karne": _eski_karne(biten, bekleyen, iptal),
        "karne_seri": _eski_karne_seri(biten),
        "gecmis": cikti.arsiv_bolumu(biten, int(ayar.cikti.gecmis_adet)),
        "uyarilar": {"endeks_yok": endeks is None, "bayat": len(bayat),
                     "likit_disi": len(likit_disi), "alinamayan": len(h["hatali"]),
                     "iptal": len(iptal), "defter_arsivlendi": arsivlendi},
    }
    yol = cikti.yaz(cikti_yolu("data.json", test_modu), web)
    print(f"data.json yazildi -> {yol}")
    return 0


def _eski_karne(biten, bekleyen, iptal):
    if not biten:
        return None
    g = [float(x["getiri"]) for x in biten]
    return {"adet": len(biten),
            "isabet": round(sum(1 for x in g if x > 0) / len(g) * 100, 1),
            "ort_getiri": round(float(np.mean(g)), 2),
            "bekleyen": len(bekleyen), "iptal": len(iptal)}


def _eski_karne_seri(biten):
    seri, dogru = [], 0
    for n, x in enumerate(sorted(biten, key=lambda z: z["date"]), 1):
        if x["sonuc"] == "ISABET":
            dogru += 1
        seri.append({"date": x["date"], "isabet": round(dogru / n * 100, 1), "adet": n})
    return seri


# ---------------------------------------------------------------- gun ici

def gun_ici(ayar, test_modu=False, sembol_limit=None):
    sem = SEMBOLLER if not sembol_limit else SEMBOLLER[:sembol_limit]
    print(f"GUN ICI tarama ({len(sem)} sembol, {ayar.gunici.aralik})...")
    veri, hatali = gunici.indir(sem)
    print(f"  veri alinan: {len(veri)} | alinamayan: {len(hatali)}")
    if not veri:
        print("HATA: gun ici veri alinamadi.")
        return 1

    gs_kapanis = {}
    try:
        with open(cikti_yolu("data.json"), encoding="utf-8") as fh:
            gs = json.load(fh)
        for r in gs.get("radar", []):
            gs_kapanis[r["sym"]] = r.get("fiyat")
    except Exception:
        pass

    simdi = pd.Timestamp.now(tz="UTC")
    anomaliler, en_yeni = [], None
    for s, d in veri.items():
        try:
            anomaliler.extend(gunici.anomali(s, d, simdi, gs_kapanis.get(s), ayar))
        except Exception:
            continue
        ts = d["ts"].iloc[-1]
        if en_yeni is None or ts > en_yeni:
            en_yeni = ts

    anomaliler.sort(key=lambda x: (-x["siddet"], x["sym"]))
    kisa = anomaliler[:int(ayar.gunici.max_liste)]

    gecikme = veri_saat = veri_gun = None
    if en_yeni is not None:
        gecikme = int((simdi - en_yeni).total_seconds() // 60)
        yerel = en_yeni.tz_convert(AYAR.genel.tz)
        veri_saat = yerel.strftime("%d.%m %H:%M")
        veri_gun = yerel.strftime("%Y-%m-%d")
    bayat = gecikme is None or gecikme > int(ayar.gunici.max_gecikme_dk)

    if not bayat and not test_modu:
        eklenen = gunici.arsivle(anomaliler)
        if eklenen:
            print(f"  anomali arsivine eklenen: {eklenen}")

    out = {
        "surum": ayar.genel.surum, "mod": "gun-ici",
        "guncelleme": simdi.tz_convert(AYAR.genel.tz).strftime("%d.%m.%Y %H:%M"),
        "veri_saat": veri_saat, "gecikme_dk": gecikme, "bayat": bool(bayat),
        "bar": ayar.gunici.aralik, "taranan": len(veri), "alinamayan": len(hatali),
        "anomali": kisa,
    }
    cikti.yaz(cikti_yolu("intraday.json", test_modu), out)
    print(f"intraday.json yazildi | anomali: {len(kisa)} | gecikme: {gecikme} dk | bayat: {bayat}")

    if bayat:
        print("Veri bayat - bildirim gonderilmiyor.")
        return 0

    gonderilmis = gunici.durum_oku(veri_gun or "")
    yeni = [(f"{a['sym']}|{a['tip']}", a) for a in kisa
            if a["siddet"] >= float(ayar.gunici.alarm_siddet)
            and f"{a['sym']}|{a['tip']}" not in gonderilmis]
    if yeni and not test_modu:
        msg = f"GUN ICI ANOMALI | {out['guncelleme']}\nVeri: {veri_saat} ({gecikme} dk once)\n\n"
        for _, a in yeni[:6]:
            msg += f"- {a['sym']} {a['fiyat']} | {a['baslik']}\n   {a['detay']}\n"
        msg += "\nVeri gecikmelidir. Yatirim tavsiyesi degildir."
        telegram(msg)
        gonderilmis.update(k for k, _ in yeni[:6])
        gunici.durum_yaz(veri_gun, gonderilmis)
    elif yeni:
        print(f"[test] gonderilecekti: {[k for k, _ in yeni]}")
    else:
        print("Yeni alarm yok.")
    return 0


# --------------------------------------------------------------- backtest

def backtest_calistir(ayar, sembol_limit=None, baslangic=None, rejim_zorla=None,
                      test_modu=False):
    sem = SEMBOLLER if not sembol_limit else SEMBOLLER[:sembol_limit]
    h = veri_hazirla(sem, ayar)
    if h is None:
        print("HATA: veri yok.")
        return 1
    print("Backtest kosuyor (walk-forward)...")
    sonuc = bt.calistir(h["ZEN"], h["endeks"], h["rejim_t"], h["genislik_t"],
                        ayar, rejim_zorla, baslangic)
    if sonuc.get("hata"):
        print("HATA:", sonuc["hata"])
        return 1
    yol = cikti.yaz(cikti_yolu("backtest.json", test_modu), sonuc)

    d, w = sonuc["donem"], sonuc["isabet"]
    print(f"\n=== BACKTEST {d['bas']} -> {d['son']} ===")
    print(f"Islem: {sonuc['adet']} | Bastirilan gun: {d['bastirilan_gun']}/{d['gun']}")
    print(f"Isabet: %{w['oran']} (guven araligi %{w['alt']} - %{w['ust']})")
    print(f"Brut ort: %{sonuc['getiri']['ort']:+.2f} | Net (maliyet dahil): %{sonuc['net_getiri']['ort']:+.2f}")
    e = sonuc["equity"]
    print(f"Sermaye: {e['toplam_getiri']:+.1f}% | Max dusus: {e['max_dusus']:.1f}%")
    k = sonuc["karsilastirma"]
    if k.get("havuz"):
        print(f"Havuz (secmeseydin): %{k['havuz']['ort']:+.2f}")
    if k.get("endeks"):
        print(f"Endeks: %{k['endeks']['ort']:+.2f}")
    print(f"\n{sonuc['yorum']}")
    print("\nSkor dilimine gore:")
    for s in sonuc["skor_dilimi"]:
        print(f"  {s['dilim']}: {s['adet']} islem | isabet %{s['isabet']['oran']} "
              f"(%{s['isabet']['alt']}-%{s['isabet']['ust']}) | ort %{s['ort_getiri']:+.2f}")
    if sonuc.get("rejim_ab"):
        a = sonuc["rejim_ab"]
        print(f"\nRejim A/B: tum {a['tum']['adet']} islem ort %{a['tum']['ort']:+.2f} | "
              f"RISKLI gunler haric {a['riskli_haric']['adet']} islem ort %{a['riskli_haric']['ort']:+.2f}")
    print(f"\nbacktest.json yazildi -> {yol}")
    return 0


def anomali_karne(ayar, sembol_limit=None):
    sem = SEMBOLLER if not sembol_limit else SEMBOLLER[:sembol_limit]
    h = veri_hazirla(sem, ayar)
    if h is None:
        return 1
    k = gunici.anomali_karnesi(h["ZEN"])
    if not k:
        print("Anomali arsivi bos veya eslesme yok. Gun ici tarama biriktikce dolacak.")
        return 0
    print("\n=== ANOMALI KARNESI (anomaliden sonraki getiri) ===")
    for satir in k:
        print(f"\n{satir['tip']}:")
        for u, v in satir["ufuk"].items():
            print(f"  {u} gun: {v['adet']} ornek | isabet %{v['isabet']['oran']} "
                  f"(%{v['isabet']['alt']}-%{v['isabet']['ust']}) | ort %{v['ort']:+.2f}")
    return 0


# -------------------------------------------------------------------- main

def main(argv=None):
    p = argparse.ArgumentParser(prog="radar", description="MERT RADAR - BIST tarama sistemi")
    p.add_argument("mod", nargs="?", default="gun-sonu",
                   choices=["gun-sonu", "gun-ici", "backtest", "anomali-karne"])
    p.add_argument("--test", action="store_true", help="uretim dosyalarini ezme, bildirim gonderme")
    p.add_argument("--sembol", type=int, default=None, help="ilk N sembolle sinirla")
    p.add_argument("--config", default=None, help="alternatif config.yaml yolu")
    p.add_argument("--baslangic", default=None, help="backtest baslangic tarihi (YYYY-AA-GG)")
    p.add_argument("--rejim-kapali", action="store_true", help="backtest'te rejim filtresini devre disi birak")
    p.add_argument("--zorla-tam", action="store_true", help="onbellegi yok say, tam gecmisi indir")
    a = p.parse_args(argv)

    ayar = yukle(a.config) if a.config else AYAR
    if a.test:
        ayar.bildirim["telegram_aktif"] = False

    if a.mod == "gun-ici":
        return gun_ici(ayar, a.test, a.sembol)
    if a.mod == "backtest":
        return backtest_calistir(ayar, a.sembol, a.baslangic,
                                 "kapali" if a.rejim_kapali else None, a.test)
    if a.mod == "anomali-karne":
        return anomali_karne(ayar, a.sembol)
    return gun_sonu(ayar, a.test, a.sembol, a.zorla_tam)


if __name__ == "__main__":
    sys.exit(main())
