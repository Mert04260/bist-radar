# -*- coding: utf-8 -*-
"""Skorlama, benzer-gun istatistigi ve gerekce metinleri."""
import numpy as np

from .ayar import AYAR
from .gostergeler import sayi as _s


def skorla(r, ayar=None):
    ayar = ayar or AYAR
    kirp = lambda v: float(np.clip(v, 0, 20))

    t = 0.0
    if _s(r["close"]) > _s(r["s20"]):
        t += 6
    if _s(r["close"]) > _s(r["s50"]):
        t += 4
    if _s(r["s20"]) > _s(r["s50"]):
        t += 4
    rs = r["rs"] if "rs" in r else None
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
            "ham": round(float(toplam), 1), "rs_var": bool(rs_var)}


def rejim_uygula(f, rejim_etiket, ayar=None):
    """Piyasa rejimine gore skoru cezalandirir. f yerinde degistirilir."""
    ayar = ayar or AYAR
    if not ayar.rejim.aktif:
        f["ceza"] = 0.0
        return f
    ceza = float(dict(ayar.rejim.ceza).get(rejim_etiket, 0.0))
    f["ceza"] = ceza
    f["S"] = round(max(0.0, f["ham"] - ceza), 1)
    return f


def benzer_gun(e, i, ayar=None):
    """Gecmiste benzer kosullu gunlerin ileri getiri dagilimi.

    Yalnizca i'den onceki barlara bakar; ortusen pencereler tek epizot sayilir.
    """
    ayar = ayar or AYAR
    ufuk = int(ayar.skor.ufuk)
    r = e.iloc[i]
    gecmis = e.iloc[:i]
    if len(gecmis) < 80 or not np.isfinite(_s(r["rsi"], np.nan)) or not np.isfinite(_s(r["vr"], np.nan)):
        return None
    s20 = _s(r["s20"], np.nan)
    s20_ust = bool(_s(r["close"], np.nan) > s20) if np.isfinite(s20) else False
    m = (
        gecmis["rsi"].sub(r["rsi"]).abs().lt(8)
        & gecmis["vr"].sub(r["vr"]).abs().lt(0.8)
        & (gecmis["close"].gt(gecmis["s20"]) == s20_ust)
    ).fillna(False)
    konumlar = np.flatnonzero(m.to_numpy())
    epizotlar, son = [], -10000
    for p in konumlar:
        if p - son > ufuk:
            epizotlar.append(p)
            son = p
    acilis = e["open"].to_numpy(dtype=float)
    kapanis = e["close"].to_numpy(dtype=float)
    n = len(e)
    getiriler = []
    for p in epizotlar:
        if p + ufuk < n and acilis[p + 1] > 0:
            getiriler.append(kapanis[p + ufuk] / acilis[p + 1] - 1)
    if len(getiriler) < int(ayar.skor.min_epizot):
        return None
    g = np.array(getiriler)
    yuk, dus = g[g > 0], g[g <= 0]
    return {
        "epizot": int(len(g)),
        "ham": int(len(konumlar)),
        "up": round(float((g > 0).mean() * 100), 1),
        "avg_up": round(float(yuk.mean() * 100), 2) if len(yuk) else 0.0,
        "avg_dn": round(float(abs(dus.mean()) * 100), 2) if len(dus) else 0.0,
        "medyan": round(float(np.median(g) * 100), 2),
        "dagilim": [round(float(x) * 100, 2) for x in g[-60:]],
    }


def sebepler(r, sim, f, piyasa=None):
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
    if np.isfinite(_s(r.get("rs_sektor"), np.nan)) and _s(r.get("rs_sektor")) > 0.02:
        s.append(f"Kendi sektorune gore %{_s(r['rs_sektor'])*100:.1f} daha guclu")
    if _s(r["close"]) > _s(r["s20"]) > _s(r["s50"]):
        s.append("Fiyat > SMA20 > SMA50: yukselen trend dizilimi")
    mf = _s(r["mfi"], 50)
    if mf >= 65:
        s.append(f"Para akisi gostergeleri olumlu (MFI {mf:.0f})")
    if sim:
        s.append(f"Benzer {sim['epizot']} bagimsiz epizodun %{sim['up']}'i yukselisle bitmis")
    if f.get("ceza"):
        s.append(f"UYARI: piyasa rejimi nedeniyle skordan {f['ceza']:.0f} puan dusuldu")
    return s[:8]
