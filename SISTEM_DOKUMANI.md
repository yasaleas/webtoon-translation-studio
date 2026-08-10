# Webtoon Editor - Sistem Dokumani

## 1. Genel Amac

Webtoon Editor, webtoon sayfalarindaki yazilari tespit etmek, OCR ile okumak, Gemini ile cevirmek, metin bolgelerini temizlemek ve cevirileri sayfalara yerlestirmek icin gelistirilmis yerel bir duzenleme aracidir. Sistem kullanicinin bilgisayarinda calisir; proje gorselleri, bolum verileri, yedekler ve ayarlar yerel `data/` klasorunde tutulur.

## 2. Mimari

- **On yuz**: React + Vite. Ana uygulama `frontend/src/main.jsx`, API istemcisi `frontend/src/lib/api.js`, stil dosyasi `frontend/src/styles/app.css` icindedir.
- **Arka yuz**: Flask. Rotalar `backend/app.py`, is kuyrugu `backend/jobs.py`, dosya ve gorsel islemleri `backend/storage.py`, ayarlar `backend/settings.py`, font yonetimi `backend/fonts.py` icindedir.
- **AI katmani**: `backend/services/ai.py` RT-DETR, PaddleOCR-VL, Gemini ve IOPaint entegrasyonlarini yonetir.
- **Downloader skill**: `webtoon-downloader/` verilen bolum URL'lerinden sayfa gorsellerini indirir ve varsayilan olarak `data/projects` altina kaydeder.

## 3. Klasor Yapisi

```text
data/projects/
  WebtoonAdi/
    BolumAdi/
      Orjinal/
        001.png
      Duzenlenmis/
      Bolum Verisi/
      Yedekler/
      Ciktilar/
```

`Orjinal` dosyalari degistirilmez. Sistem calisma kopyalarini `Duzenlenmis` altina alir. Kutu koordinatlari, OCR metinleri, ceviriler, font ayarlari ve yerlestirme durumlari `Bolum Verisi/state.json` icinde saklanir.

## 4. Temel Is Akisi

1. Kullanici proje ve bolum secer.
2. Sayfalar webtoon okuma akisina benzer sekilde sirali olarak gosterilir.
3. Yazilar otomatik tespit edilir veya kullanici kutulari elle cizer.
4. OCR, secili kutu veya tum kutular icin calistirilabilir.
5. Ceviri Gemini ile yapilir. Ayarlardaki "Bolum parcalama" secenegi, bolum sayfalarini esit gruplara ayirarak gereksiz API istegi olusmasini azaltir.
6. Temizleme IOPaint ile kutu bolgesinde yapilir. Kose modu varsa maske bu sekle gore uygulanir.
7. Ceviriler tum kutulara veya yalniz secili kutuya yerlestirilebilir. Yerlestirme geri alinabilir.
8. Kaydetme sadece `placed` durumundaki kutulari gorselin uzerine kalici olarak basar.

## 5. Kutu ve Metin Ozellikleri

Kutular sayfa sirasi, yukseklik ve yatay konuma gore otomatik siralanir. Her kutuda kaynak metin, ceviri, durum, stil, font, font boyutu, kontur, renk, kalinlik ve perspektif/kose bilgisi tutulur. Kose modu OCR, temizleme ve ceviri yerlestirme icin ayni geometriyi kullanir. Ceviri metnindeki manuel satirlar ve bos satirlar kaydetme sirasinda korunur.

## 6. Ayarlar

Ayar menusu su alanlari yonetir:

- Gemini API key durumu, hazir listeden veya serbest model ID ile model secimi, hedef dil, timeout ve bolum parcalama.
- Varsayilan font ve font boyutu.
- Kullanici fontu yukleme.
- RT-DETR model, tespit esigi ve hedef label secimi.
- OCR dili.
- IOPaint modeli, cihaz ve maske payi.
- Opsiyonel reader senkronizasyon hedefi.

Gemini key ve kullanici fontlari arayuzden eklenir. Bu degerler yerel `data/settings.json` ve `data/fonts/` altinda kalir; GitHub'a gonderilmez. Ortam degiskenleri ileri kullanim icin desteklenir, fakat temel kurulum icin ayri bir `.env` dosyasi gerekli degildir.

## 7. Guvenlik ve GitHub Hazirligi

GitHub'a yayinlamadan once su kurallar uygulanmalidir:

- Gercek API key, token veya ozel gorsel commitlenmemelidir.
- `.gitignore` `data/settings.json`, `data/projects/`, `data/fonts/`, `.venv*`, `node_modules/`, `dist/` ve kisisel `reader/` klasorlerini disarida birakir.
- Flask varsayilan olarak `127.0.0.1` uzerinden calisir. Dis agdan erisim icin bilincli olarak `WEBTOON_HOST=0.0.0.0` verilmelidir.
- CORS varsayilan olarak sadece yerel Vite adreslerine aciktir. Gerekirse `WEBTOON_CORS_ORIGINS` ile sinirli origin listesi verilir.
- API path parametrelerinde mutlak path, `..`, `/` ve `\` reddedilir. Bu, proje disi dosyalara erisim riskini azaltir.
- Font yukleme boyutu `WEBTOON_MAX_UPLOAD_MB` ile sinirlidir.

## 8. Calistirma
 
Masaüstü Kontrol Paneli ile çalıştırma:
```bash
./studio.sh
```

Manuel çalıştırma:
```bash
python3.11 -m venv .venv-ai
.venv-ai/bin/python -m pip install -U pip setuptools wheel
.venv-ai/bin/python -m pip install -r backend/requirements-ai.txt
npm install
.venv-ai/bin/python -m backend.app
npm run dev
```

Downloader skill ornegi:

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode single
```

Varsayilan adresler:

- API: `http://127.0.0.1:5000`
- Arayuz: `http://127.0.0.1:5173`

## 9. Dogrulama

Yayin oncesi en az su komutlar calistirilmelidir:

```bash
.venv-ai/bin/python -m compileall backend
npm run build
rg -n "AI[z]a|api[K]ey|P[R]IVATE[ ]K[E]Y|B[E]GIN .* K[E]Y|to[K]en|pass[W]ord" . -g '!node_modules/**' -g '!.venv*/**' -g '!data/projects/**' -g '!dist/**'
```

Son komut gizli bilgi taramasi icindir; gercek sirlar commitlenmeden once temizlenmelidir.
