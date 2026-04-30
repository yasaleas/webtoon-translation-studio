---
name: webtoon-downloader
description: Download webtoon or manga chapters from the internet and save them as image files. Use this skill whenever the user provides a chapter URL and wants to download webtoon/manga chapters locally. Supports Webtoons.com, MangaDex, Madara-theme WordPress sites, and generic comic/webtoon sites. Trigger when user mentions downloading webtoons, manga chapters, comic images from a URL, or bulk-saving episodes from any comic site.
---

# Webtoon Downloader Skill

Verilen bir bölüm URL'sinden webtoon/manga bölümlerini indirip Webtoon Editor proje yapısına kaydeder.

## Klasör Yapısı (değiştirme)

```
data/projects/
└── {webtoon_adı}/
    └── {bölüm_adı}/
        └── Orjinal/
            ├── 001.jpg
            ├── 002.webp
            └── ...
```

Webtoon adı ve bölüm adı siteden çekilen gerçek isimlerdir. Dosya uzantıları orijinal formata göre belirlenir (jpg, webp, png, vb.).

---

## Genel Akış

1. Bağımlılıkları kur
2. URL'yi al → siteyi tespit et → webtoon adı + bölüm listesini çek
3. **Kullanıcıya hangi bölümleri indireceğini sor** (aşağıya bak)
4. Seçilen bölümleri indir ve kaydet
5. Özet göster

---

## Adım 1: Bağımlılıklar

Bu repo için bağımlılıklar ana `.venv-ai` ortamına `backend/requirements-ai.txt` üzerinden kurulur. Downloader `requests`, `beautifulsoup4` ve opsiyonel `cloudscraper` kullanır.

---

## Adım 2: Downloader Script'i Çalıştır

Script dosyası repo kökündeki `webtoon-downloader/scripts/downloader.py` konumundadır. Repo kökünden `.venv-ai/bin/python` ile çalıştır.

### Site Tespiti

| URL İçeriği | Site Tipi |
|---|---|
| `webtoons.com` | `webtoons` |
| `mangadex.org` | `mangadex` |
| Diğerleri | `auto` (Madara tespiti yapılır, yoksa generic) |

---

## Adım 3: Kullanıcıya Bölüm Seçimi Sor

Script bölüm listesini döndürdükten sonra **kullanıcıya şu seçenekleri sun**:

> Hangi bölümleri indirmek istersin?
> 1. Tüm bölümler ({toplam} bölüm)
> 2. Belirli bir aralık (örn: 1-20)
> 3. Sadece belirli bölümler (örn: 5, 12, 30)
> 4. Sadece en son bölüm
> 5. Verilen URL'deki tek bölüm

Kullanıcı cevapladıktan sonra indirmeyi başlat.

---

## Script Kullanım Örnekleri

```bash
# Sadece bölüm listesini çek (indirme yok)
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --list-only

# Tek bölüm indir (URL'deki bölüm)
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode single

# Aralık indir
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode range --start 1 --end 20

# Belirli bölümler
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode specific --chapters "5,12,30"

# Tümünü indir
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode all

# Çıktı klasörü belirt (varsayılan: data/projects)
.venv-ai/bin/python webtoon-downloader/scripts/downloader.py --url "https://..." --mode all --output "/hedef/klasor"
```

---

## Hata Yönetimi

- **403 / Cloudflare hatası**: cloudscraper kullan, gerekirse `--delay 2` ekle
- **Resim yüklenmiyor**: Referer header'ını kaynak URL olarak ayarla
- **Bölüm listesi boş**: Generic mod için sayfayı manuel parse et, `<img>` taglerinden büyük resimleri filtrele (>100px)
- **Rate limit**: Her istek arası `time.sleep(0.5)` uygula

---

## Önemli Notlar

- İndirme klasörü: kullanıcının belirttiği yol, yoksa repo içindeki `data/projects`
- Dosya isimleri: sıra numarası formatında `001`, `002`, ... + orijinal uzantı
- Var olan dosyalar atlanır (yeniden indirilmez)
- İndirme sırasında ilerlemeyi konsola yaz: `[3/45] Bölüm 12 - sayfa 003.webp`
