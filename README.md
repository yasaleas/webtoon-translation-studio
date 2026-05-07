# Webtoon Translation Studio

Yerel çalışan, AI destekli webtoon çeviri ve düzenleme stüdyosu. Bölüm görsellerini webtoon okuma sitelerindeki gibi dikey akışta açar, yazı bölgelerini seçer, OCR ile metni okur, Gemini ile çevirir, eski yazıları temizler ve yeni çevirileri sayfalara yerleştirir.

Bu proje internet üzerinden herkese açık bir editör değildir. Görseller, bölüm verileri, fontlar, yedekler ve ayarlar kullanıcının bilgisayarındaki `data/` klasöründe tutulur.

## Öne Çıkan Özellikler

- Webtoon sayfalarını tek akışta, okuma sitesi düzeninde görüntüleme.
- RT-DETR V2 ile yazı bölgelerini otomatik seçme.
- PaddleOCR-VL 1.5 ile seçili kutulardan metin okuma.
- Gemini API ile sayfa gruplarına bölerek çeviri alma.
- IOPaint LaMa ile sadece seçili yazı alanlarını temizleme.
- Tek kutu veya tüm kutular için OCR, temizleme, yerleştirme ve yerleşimi kaldırma.
- Kutuları sayfa sırası ve yukarıdan aşağıya konuma göre otomatik sıralama.
- Köşe modu ile kutu geometrisini Photoshop benzeri köşe tutamaçlarıyla düzeltme.
- Perspektif, eğim, ölçek, renk, kontur, kalınlık, font ve font boyutu düzenleme.
- Varsayılan font ve font boyutunu ayarlardan belirleme.
- Arayüzden `.ttf` ve `.otf` font yükleme.
- Seçili kutuyu orijinal görselden geri yükleme.
- Kaydetmeden önce yedek alma ve çıktı görsellerini yerel klasörde üretme.
- Bölüm URL'lerinden görsel indirmek için `webtoon-downloader` yardımcı aracı.

## Gereksinimler

- Linux ortamı. Proje bu yapı üzerinde geliştirilmiştir.
- Python 3.11.
- Node.js 20 veya daha yeni bir sürüm.
- Git.
- Gemini API key. Çeviri için gereklidir ve arayüzdeki Ayarlar menüsünden eklenir.
- AI modelleri için yeterli disk alanı. İlk çalıştırmada bazı modeller indirilebilir.

GPU zorunlu değildir. Varsayılan ayar CPU'dur. CUDA kurulumu hazırsa cihaz ayarı arayüzden değiştirilebilir.

## Hızlı Kurulum

Repoyu klonlayın:

```bash
git clone https://github.com/yasaleas/webtoon-translation-studio.git
cd webtoon-translation-studio
```

Python ortamını kurun:

```bash
python3.11 -m venv .venv-ai
.venv-ai/bin/python -m pip install -U pip setuptools wheel
.venv-ai/bin/python -m pip install -r backend/requirements-ai.txt
```

Ön yüz bağımlılıklarını kurun:

```bash
npm install
```

## Çalıştırma

API sunucusunu başlatın:

```bash
.venv-ai/bin/python -m backend.app
```

Yeni bir terminalde arayüzü başlatın:

```bash
npm run dev
```

Tarayıcıdan açın:

```text
http://127.0.0.1:5173
```

API varsayılan olarak `http://127.0.0.1:5000` adresinde çalışır.

İlk açılışta sağ üstteki ayarlar menüsünden Gemini API key ekleyin. Font, OCR, çeviri, temizleme ve opsiyonel reader senkronizasyon ayarları aynı menüden düzenlenir.

## İlk Projeyi Hazırlama

Görselleri aşağıdaki yapıda yerleştirin:

```text
data/projects/
  WebtoonAdi/
    Bolum01/
      Orjinal/
        001.jpg
        002.jpg
        003.webp
```

Desteklenen düzenleme görsel formatları: `.jpg`, `.jpeg`, `.png`, `.webp`.

Bölüm açıldığında sistem şu klasörleri otomatik oluşturur:

```text
Duzenlenmis/     Düzenleme yapılan çalışma görselleri
Bolum Verisi/    Kutu, OCR, çeviri ve stil verileri
Yedekler/        Kaydetme ve geri alma yedekleri
Ciktilar/        Kaydedilmiş son çıktılar
```

`Orjinal`, `Orijinal` ve `Original` klasör adları desteklenir. Orijinal görseller değiştirilmez.

## Günlük Kullanım Akışı

1. Sol panelden webtoon ve bölüm seçin.
2. Sayfaları dikey akışta kontrol edin.
3. `Yazıları seç` ile metin bölgelerini otomatik çıkarın.
4. Gerekirse kutuları elle taşıyın veya köşe modu ile düzeltin.
5. `OCR` ile seçili bölgelerdeki metinleri okuyun.
6. Sağ panelde kaynak metni ve çeviri metnini kontrol edin.
7. `Çevir` ile Gemini çevirisini alın.
8. `Sil` ile eski yazıyı temizleyin.
9. `Yerleştir` ile çeviriyi görsel üzerine yerleştirin.
10. Font, boyut, renk, kontur, perspektif ve köşe ayarlarını düzenleyin.
11. `Kaydet` ile düzenlenmiş sayfaları çıktı olarak üretin.

Sağ paneldeki tekil kutu butonları sadece aktif kutu üzerinde çalışır. Üst araç çubuğundaki işlemler tüm bölüm akışı için kullanılır.

## AI ve Çeviri Ayarları

Ayarlar menüsünden şu değerler düzenlenebilir:

- Gemini model adı.
- İsterseniz hazır listeden, isterseniz doğrudan model ID yazarak Gemini/Gemma çeviri modeli seçimi.
- Hedef dil.
- Gemini API key kayıtları ve aktif key seçimi.
- Çeviriyi kaç parçaya bölerek göndereceği.
- Gemini timeout süresi.
- RT-DETR model adı, eşik değeri ve kullanılacak etiketler.
- OCR dili.
- IOPaint modeli, cihaz ve temizleme payı.
- Varsayılan font ailesi ve font boyutu.
- Opsiyonel reader senkronizasyon hedefi.

Arayüzden eklenen keyler yalnızca yerel `data/settings.json` dosyasında saklanır. Bu dosya GitHub'a gönderilmez.

## Font Yönetimi

Varsayılan sistem fontları otomatik listelenir. Webtoon tarzı özel fontlar için:

- Ayarlar menüsünden `.ttf` veya `.otf` font yükleyin.

Yüklenen fontlar `data/fonts/` altında tutulur ve GitHub'a gönderilmez.

## Webtoon Downloader

`webtoon-downloader/` klasörü bölüm URL'lerinden görselleri indirip doğrudan editörün okuyacağı `data/projects` yapısına kaydeder.

Tek bölüm indirme:

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode single
```

Bölüm listesini görme:

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --list-only
```

Aralık indirme:

```bash
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode range --start 1 --end 20
```

Desteklenen kaynaklar: Webtoons.com, MangaDex, Madara tabanlı siteler ve genel görsel sayfaları. Bazı sitelerde Cloudflare, oturum veya kaynak engeli nedeniyle indirme başarısız olabilir.

## Klasör Yapısı

```text
backend/                Flask API, AI işleri, ayarlar ve görsel işleme
frontend/src/           React arayüzü ve stiller
webtoon-downloader/     Bölüm indirme yardımcı aracı
data/                   Yerel projeler, ayarlar, fontlar ve çıktılar
SISTEM_DOKUMANI.md      Teknik sistem dokümanı
AGENTS.md               Katkı sağlayanlar için kısa rehber
```

`data/`, `.env*`, `.venv-ai/`, `node_modules/`, `dist/` ve kişisel `reader/` çalışma klasörü kaynak kod değildir. Bu klasörler `.gitignore` ile dışarıda bırakılır.

## Güvenlik Notları

- Gerçek API keyleri GitHub'a göndermeyin.
- Keyler arayüzden girildiğinde `data/settings.json` içinde yerel kalır.
- `data/projects/` içinde telifli veya özel içerikler olabilir; bu klasörü public repoya eklemeyin.
- Flask varsayılan olarak sadece `127.0.0.1` üzerinde çalışır.
- Dış ağdan erişim açılacaksa `WEBTOON_HOST` ve `WEBTOON_CORS_ORIGINS` bilinçli şekilde sınırlandırılmalıdır.
- Font yükleme boyutu `WEBTOON_MAX_UPLOAD_MB` ile sınırlandırılır.

## Sorun Giderme

Gemini timeout hatası alırsanız:

- Ayarlardan `Gemini timeout` değerini artırın.
- `Gemini page splits` değerini 2 veya 3 yapın.
- Çok uzun bölümlerde önce daha az sayfayı çevirin.

OCR veya tespit kötü sonuç verirse:

- Kutuyu elle düzeltin veya köşe modunu kullanın.
- RT-DETR eşik değerini ayarlardan değiştirin.
- `rtdetrTextLabels` değerinin `text_bubble,text_free` kaldığından emin olun.

Temizleme görselde görünmüyorsa:

- İş kuyruğunda `inpaint` hatasını kontrol edin.
- Kutunun gerçekten yazı alanını kapsadığını doğrulayın.
- Sayfayı yenilemek yerine uygulamadaki `Yenile` butonunu kullanın.

Font görünmüyorsa:

- Font dosyasının `.ttf` veya `.otf` olduğundan emin olun.
- Arayüzden yüklenen fontlar için API ve arayüzü yeniden başlatın.

OpenCV veya görüntü kütüphanesi hatası alırsanız Ubuntu tabanlı sistemlerde şu paketler gerekebilir:

```bash
sudo apt install libgl1 libglib2.0-0
```

## Geliştirme Komutları

Frontend production build:

```bash
npm run build
```

Frontend ön izleme:

```bash
npm run preview
```

Python dosyalarını hızlı kontrol:

```bash
.venv-ai/bin/python -m compileall backend webtoon-downloader
```

Bağımlılık güvenlik kontrolü:

```bash
npm audit --audit-level=moderate
```

## Yasal Kullanım

Bu araç yerel düzenleme ve çeviri iş akışını kolaylaştırmak için geliştirilmiştir. İndirdiğiniz veya düzenlediğiniz içeriklerin kullanım haklarından siz sorumlusunuz. Public GitHub reposuna telifli webtoon sayfaları, özel proje verileri veya API keyleri eklemeyin.
