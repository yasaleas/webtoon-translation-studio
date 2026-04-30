# Project Handoff

Bu dosya yeni bir konuşmada proje bağlamını hızlıca geri yüklemek için tutulur. Yeni ajan önce bu dosyayı, sonra `README.md`, `SISTEM_DOKUMANI.md` ve `AGENTS.md` dosyalarını okumalıdır.

## Repository

- GitHub: `https://github.com/yasaleas/webtoon-translation-studio`
- Ana branch: `main`
- Son bilinen commit: `90f08fc Improve public README and branding`
- Uygulama adı: **Webtoon Translation Studio**
- Proje türü: Yerel çalışan AI destekli webtoon çeviri ve düzenleme stüdyosu.

## Current Architecture

- `frontend/src/main.jsx`: React arayüzünün ana iş akışı.
- `frontend/src/lib/api.js`: Flask API istemcisi.
- `frontend/src/styles/app.css`: ana UI stili.
- `backend/app.py`: Flask route tanımları.
- `backend/jobs.py`: detect, OCR, translate, inpaint, place, unplace ve save işleri.
- `backend/storage.py`: proje dosyaları, kutular, state, görsel render ve yedekleme.
- `backend/services/ai.py`: RT-DETR, PaddleOCR-VL, Gemini ve IOPaint entegrasyonları.
- `backend/settings.py`: yerel ayarlar ve Gemini key seçimi.
- `backend/fonts.py`: sistem fontları, yüklenen fontlar ve opsiyonel yerel fontlar.
- `webtoon-downloader/`: bölüm URL'lerinden görsel indiren yardımcı araç.

## Important Decisions

- Tek aktif Python ortamı `.venv-ai`; eski `.venv` ve eski lightweight `requirements.txt` kaldırıldı.
- Python bağımlılık dosyası `backend/requirements-ai.txt`.
- Downloader bağımlılıkları da `.venv-ai` içine taşındı.
- Runtime verileri `data/` altında kalır ve Git'e girmez.
- Secret için önerilen yol `.env`; gerçek Gemini key GitHub'a gönderilmez.
- `.env` içindeki `GEMINI_API_KEY`, arayüzde kayıtlı keylerden önce kullanılır.
- Yerel Tight Spot BB fontu kodda hardcoded değildir; `WEBTOON_TIGHT_SPOT_BB_PATH` veya arayüzden font yükleme ile kullanılır.
- Varsayılan font fallback'i `noto-sans-black`.
- Repo public; telifli webtoon sayfaları, proje görselleri ve keyler commitlenmemeli.

## Implemented Feature Set

- Webtoon sayfalarını dikey okuyucu akışında gösterme.
- Yazı bölgelerini otomatik seçme; balon gövdesini değil yazı alanlarını hedefleme.
- Kutuları sayfa sırası ve yukarıdan aşağı konuma göre sıralama.
- Sağ panelde kutu listesi ve aktif kutu düzenleyici.
- Kutular için köşe modu; OCR, silme ve yerleştirme aynı geometriyi kullanır.
- Tek kutu veya tüm kutular için OCR, temizleme, yerleştirme ve yerleşimi kaldırma.
- Seçili kutuyu orijinal görselden geri yükleme.
- Gemini çevirisini sayfa gruplarına bölerek gönderme.
- Varsayılan font ve font boyutu ayarı.
- Arayüzden `.ttf` ve `.otf` font yükleme.
- Perspektif, eğim, ölçek, renk, kontur, kalınlık ve hizalama ayarları.
- Kaydetmede manuel satır sonları ve boş satırları koruyan metin render akışı.
- Güvenlik için path validation, CORS sınırlama, `.env.example` ve `.gitignore`.

## Local Commands

Kurulum:

```bash
python3.11 -m venv .venv-ai
.venv-ai/bin/python -m pip install -U pip setuptools wheel
.venv-ai/bin/python -m pip install -r backend/requirements-ai.txt
npm install
cp .env.example .env
```

Çalıştırma:

```bash
.venv-ai/bin/python -m backend.app
npm run dev
```

Doğrulama:

```bash
npm run build
.venv-ai/bin/python -m compileall backend webtoon-downloader
npm audit --audit-level=moderate
```

Downloader örneği:

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode single
```

## Before Changing Code

1. `git status --short --branch` çalıştır.
2. Kullanıcının yerel runtime dosyalarına dokunma: `.env`, `.venv-ai/`, `data/`, `node_modules/`, `dist/`.
3. AI model isimlerini veya temel model rollerini kullanıcı açıkça istemeden değiştirme.
4. UI değişikliklerinde profesyonel, yoğun ama okunabilir bir editör deneyimini koru.
5. Değişiklik sonrası en azından `npm run build` ve Python `compileall` çalıştır.

## Suggested Next Feature Areas

- Daha iyi iş kuyruğu görünümü ve uzun AI işlerinde iptal/tekrar dene kontrolleri.
- Proje/bölüm içe aktarma ekranı.
- Kutular için çoklu seçim ve toplu stil düzenleme.
- Kaydetme öncesi çıktı önizleme ve fark kontrolü.
- Model indirme/hazırlık durumunu arayüzde gösteren setup ekranı.
- Gemini çevirileri için kalite kontrol, yeniden çevir ve terim sözlüğü desteği.
