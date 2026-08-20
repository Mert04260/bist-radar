# -*- coding: utf-8 -*-
"""Performans istatistikleri.

Buradaki isin ozu su: cikplak isabet orani yaniltir. 20 islemde %60 isabet,
gercek oranin %38-%78 arasinda bir yerde oldugu anlamina gelir. Wilson guven
araligi bunu acikca gosterir; benchmark ise "ayni gunlerde hicbir sey secmeden
ne olurdu" sorusunu cevaplar.
"""
import math

import numpy as np


def wilson(basari, toplam, z=1.96):
    """Oran icin Wilson skor guven araligi (yuzde olarak)."""
    if not toplam:
        return None
    p = basari / toplam
    payda = 1 + z * z / toplam
    merkez = (p + z * z / (2 * toplam)) / payda
    yari = z * math.sqrt(p * (1 - p) / toplam + z * z / (4 * toplam * toplam)) / payda
    return {
        "oran": round(p * 100, 1),
        "alt": round(max(0.0, merkez - yari) * 100, 1),
        "ust": round(min(1.0, merkez + yari) * 100, 1),
        "n": int(toplam),
    }


def ortalama_ci(getiriler, z=1.96):
    """Ortalama getiri + standart hataya dayali guven araligi."""
    g = np.asarray([x for x in getiriler if x is not None and np.isfinite(x)], dtype=float)
    if len(g) < 2:
        return None
    ort = float(g.mean())
    se = float(g.std(ddof=1)) / math.sqrt(len(g))
    return {"ort": round(ort, 2), "alt": round(ort - z * se, 2),
            "ust": round(ort + z * se, 2), "std": round(float(g.std(ddof=1)), 2),
            "n": int(len(g))}


def t_istatistik(getiriler):
    """Ortalama getirinin sifirdan farkli olma gucu (kaba t degeri)."""
    g = np.asarray([x for x in getiriler if x is not None and np.isfinite(x)], dtype=float)
    if len(g) < 3 or g.std(ddof=1) == 0:
        return None
    return round(float(g.mean() / (g.std(ddof=1) / math.sqrt(len(g)))), 2)


def equity(kayitlar, ufuk=3, sermaye=100_000.0, alan="getiri"):
    """Portfoy sermaye egrisi.

    Modelleme varsayimi (onemli): sermaye ufuk gunune bolunur, her gun
    1/ufuk'u o gunun sinyalleri arasinda esit dagitilir. Yani ayni anda en
    fazla ufuk kadar gunun pozisyonu acik olur.

    Onceki naif model her sinyali *sirayla* %100 sermaye ile isleme sokuyordu;
    gunde 6 sinyal uretilen bir sistemde bu, ortalama islem -%0.4 iken toplam
    -%97 gibi tamamen yaniltici bir egri cikariyordu.
    """
    if not kayitlar:
        return None
    gunluk = {}
    for k in kayitlar:
        if isinstance(k, dict):
            g, tarih = k.get(alan), k.get("date")
        else:
            g, tarih = k, None
        if g is None or not np.isfinite(float(g)):
            continue
        gunluk.setdefault(tarih or len(gunluk), []).append(float(g))

    seri, tarihler = [], []
    bakiye = tepe = float(sermaye)
    max_dd = 0.0
    for tarih in sorted(gunluk, key=lambda x: str(x)):
        ort = float(np.mean(gunluk[tarih]))
        bakiye *= (1 + (ort / 100.0) / max(int(ufuk), 1))
        tepe = max(tepe, bakiye)
        max_dd = min(max_dd, bakiye / tepe - 1)
        seri.append(round(bakiye, 2))
        tarihler.append(str(tarih))
    return {
        "seri": seri, "tarihler": tarihler, "son": round(bakiye, 2),
        "toplam_getiri": round((bakiye / float(sermaye) - 1) * 100, 2),
        "max_dusus": round(max_dd * 100, 2),
        "periyot": len(seri),
        "varsayim": f"sermaye {ufuk} gune bolunur, gun ici sinyaller esit agirlikli",
    }


def profil(getiriler):
    """Kazanc/kayip profili: profit factor, beklenti, en iyi/en kotu."""
    g = np.asarray([x for x in getiriler if x is not None and np.isfinite(x)], dtype=float)
    if len(g) == 0:
        return None
    kaz, kay = g[g > 0], g[g <= 0]
    brut_k = float(kaz.sum()) if len(kaz) else 0.0
    brut_z = float(abs(kay.sum())) if len(kay) else 0.0
    return {
        "adet": int(len(g)),
        "ort_kazanc": round(float(kaz.mean()), 2) if len(kaz) else 0.0,
        "ort_kayip": round(float(kay.mean()), 2) if len(kay) else 0.0,
        "en_iyi": round(float(g.max()), 2),
        "en_kotu": round(float(g.min()), 2),
        "profit_factor": round(brut_k / brut_z, 2) if brut_z > 0 else None,
        "beklenti": round(float(g.mean()), 2),
    }


def dilim_analizi(kayitlar, alan="skor", kenarlar=(72, 80, 88, 101)):
    """Skor dilimine gore performans - 88+ gercekten daha mi iyi?"""
    out = []
    alt = kenarlar[0]
    for ust in kenarlar[1:]:
        grup = [k for k in kayitlar
                if k.get(alan) is not None and alt <= float(k[alan]) < ust]
        if grup:
            g = [float(k["getiri"]) for k in grup]
            basari = sum(1 for x in g if x > 0)
            out.append({"dilim": f"{alt}-{ust-1}", "adet": len(grup),
                        "isabet": wilson(basari, len(grup)),
                        "ort_getiri": round(float(np.mean(g)), 2)})
        alt = ust
    return out


def kirilim(kayitlar, alan):
    """Herhangi bir alana gore (rejim, sektor, cikis_tipi) kirilim."""
    gruplar = {}
    for k in kayitlar:
        gruplar.setdefault(k.get(alan) or "?", []).append(float(k["getiri"]))
    out = []
    for ad, g in sorted(gruplar.items(), key=lambda x: -len(x[1])):
        basari = sum(1 for x in g if x > 0)
        out.append({"ad": ad, "adet": len(g),
                    "isabet": round(basari / len(g) * 100, 1),
                    "ort_getiri": round(float(np.mean(g)), 2)})
    return out


def karsilastirma(kayitlar):
    """Sinyaller vs benchmark: endeks ve 'ayni gun uygun tum adaylar'."""
    sinyal = [float(k["getiri"]) for k in kayitlar if k.get("getiri") is not None]
    endeks = [float(k["endeks_getiri"]) for k in kayitlar if k.get("endeks_getiri") is not None]
    havuz = [float(k["havuz_getiri"]) for k in kayitlar if k.get("havuz_getiri") is not None]
    out = {"sinyal": ortalama_ci(sinyal), "endeks": ortalama_ci(endeks),
           "havuz": ortalama_ci(havuz), "t": t_istatistik(sinyal)}
    if out["sinyal"] and out["havuz"]:
        fark = [float(k["getiri"]) - float(k["havuz_getiri"]) for k in kayitlar
                if k.get("havuz_getiri") is not None and k.get("getiri") is not None]
        out["havuz_ustu"] = ortalama_ci(fark)
        out["havuz_ustu_t"] = t_istatistik(fark)
    if out["sinyal"] and out["endeks"]:
        fark = [float(k["getiri"]) - float(k["endeks_getiri"]) for k in kayitlar
                if k.get("endeks_getiri") is not None and k.get("getiri") is not None]
        out["endeks_ustu"] = ortalama_ci(fark)
    return out


def yorumla(karsi):
    """Istatistigi tek cumlelik dile cevirir - sayilara bakmadan da anlasilsin."""
    if not karsi or not karsi.get("sinyal"):
        return "Henuz yorum yapacak kadar kapanmis sinyal yok."
    n = karsi["sinyal"]["n"]
    if n < 30:
        return (f"Sadece {n} kapanmis sinyal var. Bu sayida sonuc sansla gercek "
                f"beceriyi ayirt etmeye yetmez; en az 30-50 islem birikmeden "
                f"karneye guvenme.")
    hu = karsi.get("havuz_ustu")
    if hu is None:
        return f"{n} sinyal kapandi; karsilastirma havuzu hesaplanamadi."
    if hu["alt"] > 0:
        return (f"{n} sinyalde secim, ayni gun uygun olan tum hisselerin "
                f"ortalamasini %{hu['ort']:+.2f} geciyor ve guven araligi "
                f"tamamen sifirin ustunde - anlamli bir secicilik var.")
    if hu["ust"] < 0:
        return (f"{n} sinyalde secim, rastgele secimin gerisinde kaliyor "
                f"(%{hu['ort']:+.2f}). Skorlama su haliyle deger katmiyor.")
    return (f"{n} sinyalde havuz ustu getiri %{hu['ort']:+.2f} ama guven araligi "
            f"sifiri iceriyor ({hu['alt']:+.2f} / {hu['ust']:+.2f}) - yani secimin "
            f"gercekten ise yaradigi henuz istatistiksel olarak gosterilemiyor.")
