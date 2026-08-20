# -*- coding: utf-8 -*-
"""Telegram bildirimi."""
import os
import urllib.parse
import urllib.request

from .ayar import AYAR


def telegram(mesaj, zorla=False):
    if not AYAR.bildirim.telegram_aktif and not zorla:
        print("Bildirim kapali. Mesaj:\n" + mesaj)
        return False
    tok = os.environ.get("TELEGRAM_TOKEN", "").strip().replace("\n", "").replace("\r", "")
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip().replace("\n", "").replace("\r", "")
    if not tok or not cid:
        print("Telegram ayarli degil. Mesaj:\n" + mesaj)
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    veri = urllib.parse.urlencode({"chat_id": cid, "text": mesaj}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=veri), timeout=25)
        print("Telegram gonderildi.")
        return True
    except Exception as ex:
        print("Telegram hatasi:", ex)
        return False
