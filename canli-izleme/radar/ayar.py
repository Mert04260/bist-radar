# -*- coding: utf-8 -*-
"""Merkezi ayar katmani.

Tum parametreler burada varsayilan degerleriyle durur; yaninda bir
config.yaml varsa o dosyadaki anahtarlar bunlarin uzerine yazilir.
Boylece esik denemesi yapmak icin kod duzenlemek gerekmez.
"""
import os
import copy

BETIK_DIZIN = os.path.dirname(os.path.abspath(__file__))
PAKET_UST = os.path.dirname(BETIK_DIZIN)


def _repo_koku(bas):
    d = bas
    for _ in range(4):
        if os.path.exists(os.path.join(d, "index.html")) or os.path.isdir(os.path.join(d, ".git")):
            return d
        ust = os.path.dirname(d)
        if ust == d:
            break
        d = ust
    return bas


VARSAYILAN = {
    "genel": {
        "surum": "v6",
        "tz": "Europe/Istanbul",
    },
    "veri": {
        "gecmis": "2y",
        "artimli_pencere": "3mo",   # onbellek tazelenirken indirilen pencere
        "parca_boyu": 25,
        "min_bar": 120,
        "onbellek_dizin": "onbellek",
        "onbellek_aktif": True,
        # Onbellekteki fiyatlarla yeni inen fiyatlar bu orandan fazla ayrilirsa
        # (temettu/bolunme sonrasi yeniden duzeltme) tam yenileme yapilir.
        "yeniden_duzeltme_tolerans": 0.005,
        "endeks": "XU100.IS",
    },
    "skor": {
        "esik": 72,
        "guven_esik": 88,
        "max_secim": 6,
        "min_islem_tl": 5_000_000,
        "ufuk": 3,
        "min_epizot": 10,
        "stop_hedef_aktif": True,
        "veri_yok_gun": 10,
    },
    "rejim": {
        "aktif": True,
        # Piyasa skoru bu degerin altindayken sinyaller bastirilir.
        "bastirma_esigi": 25,
        # Rejim notr/riskli iken hisse skorundan dusulen puan.
        "ceza": {"OLUMLU": 0.0, "NOTR": 3.0, "RISKLI": 8.0},
        "genislik_pencere": 20,
        "endeks_sma": 50,
        "dusus_esigi": 0.08,        # 60 gunluk zirveden bu kadar geri = zayif
    },
    "sektor": {
        "aktif": True,
        "yogunlasma_uyari": 3,      # ayni sektorden bu kadar sinyal = uyari
        "rs_pencere": 10,
    },
    "gunici": {
        "aralik": "15m",
        "aralik_dk": 15,
        "gecmis": "10d",
        "min_hacim_kat": 2.5,
        "min_hareket": 2.0,
        "gap_esik": 3.0,
        "gun_esik": 4.0,
        "max_liste": 12,
        "max_gecikme_dk": 45,
        "alarm_siddet": 1.5,
        "min_oran": 0.34,
        "min_slot_ornek": 3,
        "kaba_taban_carpani": 1.8,
        "arsiv_aktif": True,
    },
    "backtest": {
        "isinma_bar": 260,          # ilk bu kadar bar skorlanmaz
        "baslangic": None,          # "2024-01-01" gibi; None = isinma sonrasi
        "sermaye": 100_000.0,
        "komisyon_bps": 8.0,        # tek yon, baz puan (0.08%)
        "kayma_bps": 10.0,          # slipaj varsayimi
    },
    "cikti": {
        "gecmis_adet": 15,
        "seri_uzunluk": 30,
    },
    "bildirim": {
        "telegram_aktif": True,
    },
}


def _birlestir(taban, ust):
    for k, v in (ust or {}).items():
        if isinstance(v, dict) and isinstance(taban.get(k), dict):
            _birlestir(taban[k], v)
        else:
            taban[k] = v
    return taban


class Ayar(dict):
    """Nokta erisimli sozluk: ayar.skor.esik"""

    def __getattr__(self, ad):
        try:
            v = self[ad]
        except KeyError:
            raise AttributeError(ad)
        if isinstance(v, dict) and not isinstance(v, Ayar):
            # Sarmalayiciyi geri yaz: aksi halde ayar.bolum["anahtar"] = x
            # gecici bir kopyaya yazar ve degisiklik sessizce kaybolur.
            v = Ayar(v)
            self[ad] = v
        return v

    def __setattr__(self, ad, deger):
        self[ad] = deger


def yukle(yol=None, sessiz=False):
    cfg = copy.deepcopy(VARSAYILAN)
    aday = yol or os.path.join(PAKET_UST, "config.yaml")
    if os.path.exists(aday):
        try:
            import yaml
            with open(aday, encoding="utf-8") as fh:
                ust = yaml.safe_load(fh) or {}
            _birlestir(cfg, ust)
            if not sessiz:
                print(f"Ayar dosyasi yuklendi: {aday}")
        except ImportError:
            if not sessiz:
                print("UYARI: PyYAML yok, config.yaml yok sayildi (pip install pyyaml).")
        except Exception as ex:
            if not sessiz:
                print(f"UYARI: config.yaml okunamadi ({ex}), varsayilanlar kullaniliyor.")
    return Ayar(cfg)


AYAR = yukle(sessiz=True)
KOK = _repo_koku(PAKET_UST)
VERI_DIZIN = PAKET_UST


def yol_kok(ad):
    """Frontend'in okudugu dosyalar repo kokune yazilir."""
    return os.path.join(KOK, ad)


def yol_veri(ad):
    """Defter / arsiv / durum dosyalari paket dizinine yazilir."""
    return os.path.join(VERI_DIZIN, ad)


def cikti_yolu(ad, test_modu=False):
    if test_modu:
        govde, uzanti = os.path.splitext(ad)
        ad = govde + ".test" + uzanti
    return yol_kok(ad)
