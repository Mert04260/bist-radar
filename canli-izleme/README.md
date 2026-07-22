# BIST Radar — Canli Izleme (Paper Trading)

Her sabah 07:30'da (hafta ici) otomatik calisir:
radar taramasi yapar, sonucu Telegram'a gonderir,
3 gun sonra sinyalleri degerlendirip karneyi `signals.csv`de tutar.

## Kurulum (tek seferlik)
1. Bu klasordeki TUM dosyalari GitHub deposuna yukle
   (`.github/workflows/radar.yml` dahil — klasor yapisi korunmali)
2. Depo > Settings > Secrets and variables > Actions > New repository secret:
   - `TELEGRAM_TOKEN`  = BotFather'in verdigi token
   - `TELEGRAM_CHAT_ID` = senin chat id'in
3. Actions sekmesi > "BIST Radar - Sabah Taramasi" > Run workflow (ilk test)

⚠️ Hicbir cikti yatirim tavsiyesi degildir.
