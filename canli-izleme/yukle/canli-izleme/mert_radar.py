#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Giris noktasi (geriye donuk uyumlu kabuk).

Eski kullanim:  python mert_radar.py --gun-ici --test
Yeni kullanim:  python mert_radar.py gun-ici --test
Ikisi de calisir.
"""
import sys

ESKI = {"--gun-ici": "gun-ici", "--backtest": "backtest", "--anomali-karne": "anomali-karne"}


def _cevir(argv):
    out, mod = [], None
    for a in argv:
        if a in ESKI:
            mod = ESKI[a]
        else:
            out.append(a)
    return ([mod] if mod else []) + out


if __name__ == "__main__":
    from radar.cli import main
    sys.exit(main(_cevir(sys.argv[1:])))
