# MERT RADAR v6

BIST tarama, kagit-uzerinde izleme, gun ici anomali ve backtest sistemi.

## Ne degisti (v5 -> v6)

v5 tek dosyaydi ve **yalnizca ileri dogru** calisiyordu: sinyal uretiyor, karne
tutuyordu ama "bu skorlama gercekten ise yariyor mu" sorusunu cevaplayamiyordu.
v6'nin butun amaci bu soruyu olculebilir hale getirmek.

| Yenilik | Neden |
|---|---|
| Modul ayrimi (`radar/` paketi) | Her parca tek basina test edilebilir; davranis v5 ile ayni |
| `config.yaml` | Esik denemek icin kod duzenlemek gerekmiyor |
| Onbellek (parquet / csv.gz) | Her kosuda 128x2 yil indirmek yok; backtest'i mumkun kilan sey bu |
| Yeniden-duzeltme tespiti | Temettu/bolunme sonrasi eski+yeni fiyat karisirsa seride sahte sicrama olusur - yakalanip tam yenileme yapilir |
| `backtest` modu | Walk-forward; ileri bakis yok, canli sistemle ayni cikis cekirdegi |
| Wilson guven araligi | "20 islemde %60 isabet" aslinda "%38-%78 arasi" demek; karne artik bunu soyluyor |
| Havuz benchmark'i | O gun filtreleri gecen TUM adaylarin ortalamasi. Secim gercekten deger katiyor mu? |
| Piyasa rejimi + genislik | Dusus piyasasinda al sinyali uretmeyi engeller; en yuksek getirili tek ekleme adayi |
| Sektor RS + yogunlasma uyarisi | 6 sinyalin 4'u bankaysa bu 4 bahis degil, buyuk olcude 1 bahis |
| Anomali arsivi + karnesi | Gun ici tespitler loglanir; "hacim patlamasindan 1/3/5 gun sonra ne oldu" olculur |
| Tavan/taban kilidi tespiti | BIST'e ozgu: fiyat kilitliyken gostergeler yaniltir |
| Islem maliyeti modeli | Komisyon + kayma dusulmus net getiri |

## Kurulum

```bash
pip install -r requirements.txt
```

`pyarrow` opsiyoneldir; yoksa onbellek `csv.gz` olarak tutulur (biraz yavas, ayni sonuc).

## Kullanim

```bash
python mert_radar.py                  # gun sonu taramasi (varsayilan)
python mert_radar.py gun-ici          # gun ici anomali taramasi
python mert_radar.py backtest         # walk-forward backtest
python mert_radar.py anomali-karne    # arsivlenen anomalilerin getirisi

# secenekler
--test              # uretim dosyalarini ezme (*.test.json), bildirim gonderme
--sembol 20         # ilk 20 sembolle sinirla (hizli deneme)
--baslangic 2024-01-01
--rejim-kapali      # backtest'te rejim filtresini devre disi birak (A/B icin)
--zorla-tam         # onbellegi yok say, tum gecmisi yeniden indir
--config yol.yaml
```

Eski cagri sekli de calisir: `python mert_radar.py --gun-ici --test`

## Ilk kosu

```bash
python mert_radar.py --test --sembol 20     # once kucuk bir dilimle dene
python mert_radar.py --zorla-tam            # onbellegi doldur (bir kez, yavas)
python mert_radar.py backtest               # temel olcumu al
```

Backtest'te bakilacak tek sayi **havuz ustu getiri**dir. Guven araligi sifiri
iceriyorsa skorlama henuz kanitlanmis bir edge uretmiyor demektir - bu durumda
yeni gosterge eklemek yerine mevcut olani duzeltmek gerekir.

## Dosyalar

| Dosya | Nerede | Ne |
|---|---|---|
| `data.json` | repo koku | frontend ana veri |
| `intraday.json` | repo koku | gun ici anomaliler |
| `backtest.json` | repo koku | backtest sonucu |
| `signals.csv` | paket dizini | sinyal defteri (**en degerli varlik - silme**) |
| `anomali_arsiv.csv` | paket dizini | gun ici anomali logu |
| `intraday_state.json` | paket dizini | tekrar alarm engeli |
| `onbellek/` | paket dizini | fiyat onbellegi (silinebilir, yeniden olusur) |

### GitHub Actions notu

`signals.csv`, `anomali_arsiv.csv` ve `intraday_state.json` kosular arasinda
**kalici olmali**. Commit'liyorsan `.gitignore`'a alma. `onbellek/` dizinini ise
`actions/cache` ile tutmak en iyisi; kaybolursa sistem calismaya devam eder,
sadece ilk kosu yavaslar.

## data.json sozlesmesi (sekmeler)

Her bolum bagimsizdir; frontend yalnizca ihtiyaci olani okuyabilir.
Mevcut arayuzun okudugu `radar`, `karne`, `karne_seri`, `gecmis`, `uyarilar`
alanlari **korunmustur** - v6 mevcut sayfayi kirmaz.

| Bolum | Sekme | Icerik |
|---|---|---|
| `radar` | Ana ekran | gunun sinyalleri (mevcut) |
| `piyasa` | Piyasa Nabzi | `rejim` (etiket/puan/seri), `genislik` (SMA20 ustu %, A/D), `sektor` (isi haritasi), `yogunlasma` |
| `detay` | Hisse Detayi | sembol -> fiyat/hacim/SMA serileri, gosterge anlik degerleri, `benzer.dagilim` histogrami |
| `performans` | Performans | `karne.isabet` (Wilson), `equity`, `karsilastirma`, `skor_dilimi`, `rejim_kirilim`, `cikis_kirilim`, `yorum` |
| `arsiv` | Arsiv | tum sinyaller, frontend'de filtrelenebilir |
| `saglik` | Sistem Sagligi | onbellek/indirme sayaclari, alinamayan semboller, bayat, likit disi |
| `anomali_karne` | Anomali sekmesi | anomali tipine gore 1/3/5 gun sonraki getiri |

`performans.yorum` ve `backtest.yorum` insan diliyle yazilmis tek cumlelik
ozetlerdir; dogrudan ekrana basilabilir.

## Onemli modelleme varsayimlari

- **Giris** ertesi gun acilisi, **cikis** stop / hedef / sure (UFUK bar sonu kapanisi).
- Ayni barda stop ve hedef birlikte tetiklenirse muhafazakar davranilir: STOP.
- Hedef/stop sinyal gunu kapanisindan hesaplanir, gerçek girise yeniden cipalanir
  (gece gap'i seviyeleri anlamsiz kilmasin diye).
- **Equity egrisi** sermayeyi UFUK gune boler, her gunun sinyallerine esit agirlik
  verir. Her sinyali sirayla %100 sermayeyle isleyen naif model, gunde 6 sinyal
  ureten bir sistemde tamamen yaniltici egriler cikarir.
- Gun ici hacim tabani **ayni saat dilimi** ortalamasidir. Acilis bari yapisal
  olarak 3-5 kat hacimlidir; duz ortalama kullanilirsa her sabah sahte alarm uretilir.

## Test

```bash
python test_uctan_uca.py    # sahte piyasa uretip tum modlari kosturur (ag gerekmez)
python test_onbellek.py     # onbellek + yeniden-duzeltme tespiti
```

`test_uctan_uca.py` rastgele uretilmis bir piyasada kosar. Orada isabet oraninin
%50 civarinda ve havuz ustu getirinin sifire yakin cikmasi **beklenen** sonuctur -
rastgele veride edge olmamalidir. Backtest bu veride kar gosteriyorsa motorda
ileri bakis kacagi var demektir.

## Arayuz (index.html)

Mevcut tasarim korundu; uzerine 5 sekme eklendi. Sekmeler **veriye gore
gorunur**: `data.json`'da `piyasa` bolumu yoksa Piyasa Nabzi sekmesi hic
cikmaz. Yani eski v5 `data.json` ile de sorunsuz calisir, sadece yeni
sekmeler gorunmez.

| Sekme | Ne gosterir |
|---|---|
| Gun Sonu | mevcut ekran + sektor etiketi, rejim cezasi, guven araligi, detaya link |
| Gun Ici | mevcut ekran + bayat veri uyarisi, kilit tipi, anomali karnesi |
| Piyasa Nabzi | rejim gostergesi ve serisi, genislik metrikleri, sektor isi haritasi, sinyal dagilimi |
| Hisse Detayi | sembol secici, kapanis/SMA20/SMA50 katmanli grafik, hacim, gostergeler, skor kirilimi, benzer-gun histogrami, o hissenin gecmis sinyalleri |
| Performans | Wilson guven araligi, kazanc profili, **havuz ustu karsilastirma grafigi**, sermaye egrisi, skor dilimi tablosu, rejim/cikis/sektor kirilimlari |
| Arsiv | tum sinyaller, isabet/iska/acik/iptal filtreleri, hisseye tiklayinca detay |
| Sistem | veri kapsamasi, onbellek sayaclari, defter durumu, gun ici besleme sagligi |

Performans sekmesindeki **havuz ustu** satiri en onemli gorseldir: cubuk
tamamen sifirin sagindaysa skorlama gercekten is goruyor, sifiri kesiyorsa
henuz kanitlanmamis demektir.

### Yerel onizleme

`ornek/` klasorunde sentetik veriyle uretilmis bir `data.json` / `intraday.json`
var. Bunlar **depo kokune kopyalanmamalidir** - gercek verinin uzerine yazarlar.
Sadece yerel onizleme icin:

```bash
cp ornek/*.json .            # gecici
python -m http.server 8000   # http://localhost:8000
rm data.json intraday.json   # onizlemeden sonra sil
```

### Arayuz testi

```bash
node test_arayuz.js
```

Tarayici gerektirmez. Her sekmeyi dort senaryoda (tam v6 verisi, eski v5
verisi, hic veri yok, bos radar + bayat gun ici) render edip `undefined`,
`NaN`, cokme var mi diye denetler.
