# Webtoon Editor

Yerel çalışan webtoon çeviri ve düzenleme stüdyosu. Arayüz React + Vite, API Flask ile çalışır. AI model isimleri ve görevleri sistem dokümanındaki gibi bırakılmıştır: RT-DETR V2, PaddleOCR-VL 1.5, Gemini ve IOPaint.

## Kurulum

```bash
python3.11 -m venv .venv-ai
.venv-ai/bin/python -m pip install -U pip setuptools wheel
.venv-ai/bin/python -m pip install -r backend/requirements-ai.txt
npm install
```

## Çalıştırma

Terminal 1:

```bash
.venv-ai/bin/python -m backend.app
```

Terminal 2:

```bash
npm run dev
```

Arayüz varsayılan olarak `http://127.0.0.1:5173`, API `http://127.0.0.1:5000` adresinde çalışır.
Başka cihazlardan erişim gerektiğinde bunu bilinçli olarak açın:

```bash
WEBTOON_HOST=0.0.0.0 WEBTOON_CORS_ORIGINS=http://localhost:5173 .venv-ai/bin/python -m backend.app
npm run dev -- --host 0.0.0.0
```

## Proje Klasörü

Görselleri şu yapıda yerleştirin:

```text
data/projects/
  WebtoonAdi/
    Bolum01/
      Orjinal/
        001.png
        002.png
```

Bölüm açıldığında `Duzenlenmis`, `Bolum Verisi`, `Yedekler` ve `Ciktilar` klasörleri otomatik oluşturulur. Orijinal görseller değiştirilmez.

## Webtoon Downloader Skill

`webtoon-downloader/` klasörü bölüm URL'lerinden sayfa görsellerini indiren yardımcı skill'dir. Varsayılan çıktı yolu `data/projects` olduğu için indirilen bölümler editörde doğrudan görünür.

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode single
```

## Güvenlik ve Yayınlama Notları

- RT-DETR V2 varsayılan olarak `ogkalu/comic-text-and-bubble-detector` modelini kullanır ve yalnızca yazı bölgelerini (`text_bubble`, `text_free`) seçer. Balon gövdesini silmez.
- Gemini için önerilen yöntem `.env` dosyasında `GEMINI_API_KEY` kullanmaktır. `.env.example` şablondur; gerçek `.env` GitHub'a gönderilmez.
- Tight Spot BB gibi yerel fontlar için `.env` içinde `WEBTOON_TIGHT_SPOT_BB_PATH=/tam/yol/font.ttf` tanımlayın veya fontu arayüzden yükleyin.
- Ayarlar menüsünden eklenen keyler yalnızca yerel yedek kullanım içindir ve `data/settings.json` içinde saklanır. `.env` içinde key varsa backend önce onu kullanır.
- IOPaint varsayılan olarak `lama` ve CPU ile çalışır. `IOPAINT_MODEL`, `AI_DEVICE` ve `INPAINT_PADDING` ile değiştirilebilir.
- Kaydetme işlemi çeviri metinlerini düzenlenmiş görsellerin üzerine işler ve önce yedek alır.
- `data/settings.json`, `data/projects/`, `data/fonts/`, `.venv*`, `node_modules/` ve `dist/` GitHub'a eklenmemelidir. `.gitignore` bu dosyaları varsayılan olarak dışarıda bırakır.
