#!/usr/bin/env python3
"""
Webtoon/Manga Chapter Downloader
Desteklenen siteler: Webtoons.com, MangaDex, Madara-theme (WordPress), Generic
"""

import os
import sys
import re
import time
import json
import argparse
import requests
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote
from bs4 import BeautifulSoup

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

# ─── Sabitler ───────────────────────────────────────────────────────────────

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/122.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
}

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECTS_DIR = REPO_ROOT / 'data' / 'projects'

# ─── Yardımcı Fonksiyonlar ───────────────────────────────────────────────────

def sanitize(name: str) -> str:
    """Klasör/dosya adı için geçersiz karakterleri temizle."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name)
    name = re.sub(r'\s+', ' ', name).strip(' ._')
    return name or 'bilinmiyor'

def get_ext(url: str, content_type: str = '') -> str:
    """URL veya Content-Type'tan dosya uzantısını belirle."""
    # URL'den uzantıyı dene
    path = urlparse(url).path.lower()
    for ext in ['.jpg', '.jpeg', '.webp', '.png', '.gif', '.avif']:
        if path.endswith(ext):
            return ext.lstrip('.')
    # Content-Type'dan dene
    ct_map = {
        'image/jpeg': 'jpg', 'image/jpg': 'jpg',
        'image/webp': 'webp', 'image/png': 'png',
        'image/gif': 'gif', 'image/avif': 'avif',
    }
    for mime, ext in ct_map.items():
        if mime in content_type:
            return ext
    return 'jpg'  # varsayılan

def make_session(url: str):
    """Siteye uygun HTTP session oluştur."""
    if HAS_CLOUDSCRAPER:
        session = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
        )
    else:
        session = requests.Session()
    session.headers.update(HEADERS)
    return session

def fetch(session, url: str, **kwargs) -> requests.Response:
    """İstek at, hata varsa fırlat."""
    resp = session.get(url, timeout=20, **kwargs)
    resp.raise_for_status()
    return resp

# ─── Site Tespiti ────────────────────────────────────────────────────────────

def detect_site(url: str, session) -> str:
    domain = urlparse(url).netloc.lower()
    if 'webtoons.com' in domain:
        return 'webtoons'
    if 'mangadex.org' in domain:
        return 'mangadex'
    # Madara teması tespiti: sayfayı çek ve kontrol et
    try:
        resp = fetch(session, url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        if (soup.select_one('.reading-content') or
                soup.select_one('.entry-content') or
                soup.find('body', class_=re.compile(r'manga|webtoon', re.I))):
            return 'madara'
    except Exception:
        pass
    return 'generic'

# ─── WEBTOONS.COM ────────────────────────────────────────────────────────────

class WebtoonsScraper:
    BASE = 'https://www.webtoons.com'

    def __init__(self, session):
        self.session = session
        self.session.headers.update({'Referer': self.BASE})

    def _parse_episode_params(self, url):
        """URL'den title_no ve episode_no çek."""
        from urllib.parse import parse_qs
        qs = parse_qs(urlparse(url).query)
        title_no = qs.get('title_no', [None])[0]
        ep_no = qs.get('episode_no', [None])[0]
        return title_no, ep_no

    def get_info(self, url):
        title_no, ep_no = self._parse_episode_params(url)
        resp = fetch(self.session, url)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Webtoon adı
        title_el = (soup.select_one('.subj') or
                    soup.select_one('h1.subj') or
                    soup.select_one('meta[property="og:title"]'))
        title = (title_el.get('content') if title_el and title_el.name == 'meta'
                 else title_el.get_text()) if title_el else 'Webtoon'
        title = title.split(' - ')[0].strip()

        # Tüm bölüm listesi
        episodes = []
        ep_list_url = f'{self.BASE}/episodeList?titleNo={title_no}'
        try:
            list_resp = fetch(self.session, ep_list_url)
            list_soup = BeautifulSoup(list_resp.text, 'html.parser')
            for li in list_soup.select('#_listUl li'):
                a = li.select_one('a')
                name_el = li.select_one('.sub-title, .episode-name')
                if a and a.get('href'):
                    ep_url = a['href']
                    ep_name = name_el.get_text(strip=True) if name_el else a.get_text(strip=True)
                    qs2 = parse_qs(urlparse(ep_url).query)
                    ep_n = qs2.get('episode_no', ['?'])[0]
                    episodes.append({'no': ep_n, 'name': ep_name, 'url': ep_url})
        except Exception:
            # Liste çekilemedi, sadece mevcut bölümü ekle
            ep_soup = soup.select_one('.episode_cont, .episode-subtitle')
            ep_name = ep_soup.get_text(strip=True) if ep_soup else f'Bölüm {ep_no}'
            episodes = [{'no': ep_no, 'name': ep_name, 'url': url}]

        return {'title': sanitize(title), 'episodes': list(reversed(episodes))}

    def get_images(self, ep_url):
        resp = fetch(self.session, ep_url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        imgs = soup.select('#_imageList img, .viewer_img img, ._images img')
        urls = []
        for img in imgs:
            src = img.get('data-url') or img.get('data-src') or img.get('src', '')
            if src and src.startswith('http'):
                urls.append(src)
        return urls


# ─── MANGADEX ────────────────────────────────────────────────────────────────

class MangaDexScraper:
    API = 'https://api.mangadex.org'

    def __init__(self, session):
        self.session = session

    def _chapter_id(self, url):
        # https://mangadex.org/chapter/{uuid}
        m = re.search(r'/chapter/([a-f0-9\-]+)', url)
        return m.group(1) if m else None

    def _manga_id_from_chapter(self, chapter_id):
        resp = fetch(self.session, f'{self.API}/chapter/{chapter_id}',
                     params={'includes[]': 'manga'})
        data = resp.json()['data']
        for rel in data.get('relationships', []):
            if rel['type'] == 'manga':
                return rel['id']
        return None

    def get_info(self, url):
        chapter_id = self._chapter_id(url)
        if not chapter_id:
            raise ValueError('MangaDex chapter ID bulunamadı.')

        manga_id = self._manga_id_from_chapter(chapter_id)

        # Manga adı
        manga_resp = fetch(self.session, f'{self.API}/manga/{manga_id}')
        manga_data = manga_resp.json()['data']
        attrs = manga_data['attributes']
        title = (attrs['title'].get('tr') or
                 attrs['title'].get('en') or
                 next(iter(attrs['title'].values()), 'Manga'))

        # Bölüm listesi (Türkçe veya İngilizce)
        episodes = []
        for lang in ['tr', 'en']:
            ep_resp = fetch(self.session, f'{self.API}/chapter',
                            params={
                                'manga': manga_id,
                                'translatedLanguage[]': lang,
                                'order[chapter]': 'asc',
                                'limit': 500,
                            })
            chapters = ep_resp.json().get('data', [])
            if chapters:
                for ch in chapters:
                    a = ch['attributes']
                    ch_no = a.get('chapter', '?')
                    ch_title = a.get('title') or f'Bölüm {ch_no}'
                    episodes.append({
                        'no': ch_no,
                        'name': sanitize(ch_title),
                        'id': ch['id'],
                        'url': f'https://mangadex.org/chapter/{ch["id"]}',
                    })
                break

        return {'title': sanitize(title), 'episodes': episodes}

    def get_images(self, ep_url):
        chapter_id = self._chapter_id(ep_url)
        resp = fetch(self.session, f'{self.API}/at-home/server/{chapter_id}')
        data = resp.json()
        base = data['baseUrl']
        ch_hash = data['chapter']['hash']
        files = data['chapter']['data']  # yüksek kalite
        return [f'{base}/data/{ch_hash}/{f}' for f in files]


# ─── MADARA (WordPress) ───────────────────────────────────────────────────────

class MadaraScraper:

    def __init__(self, session, url):
        self.session = session
        parsed = urlparse(url)
        self.base = f'{parsed.scheme}://{parsed.netloc}'
        self.url = url

    def _get_manga_slug(self, url):
        """URL'den manga slug'ını çıkar."""
        # /manga/slug/bolum-1/ veya /webtoon/slug/bolum-1/ gibi
        m = re.search(r'(?:manga|webtoon|series|comic)/([^/]+)', urlparse(url).path)
        return m.group(1) if m else None

    def get_info(self, url):
        resp = fetch(self.session, url)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Webtoon adı
        title_el = (soup.select_one('.post-title h1') or
                    soup.select_one('h1.entry-title') or
                    soup.select_one('meta[property="og:title"]') or
                    soup.select_one('h1'))
        title = (title_el.get('content') if title_el and title_el.name == 'meta'
                 else title_el.get_text()) if title_el else 'Webtoon'
        title = sanitize(title.strip())

        # Manga ana sayfası URL'si
        manga_url = None
        canonical = soup.find('link', rel='canonical')
        if canonical:
            manga_url = canonical.get('href', '')
        if not manga_url:
            slug = self._get_manga_slug(url)
            if slug:
                manga_url = f'{self.base}/manga/{slug}/'

        # Bölüm listesi - Madara'nın AJAX endpoint'i
        episodes = []
        post_id = None
        post_id_el = soup.find(id=re.compile(r'manga-chapters-holder|wp-manga-chapter'))
        if post_id_el:
            post_id = post_id_el.get('data-id')

        if not post_id:
            # meta veya body'den post ID dene
            body = soup.find('body')
            if body:
                classes = ' '.join(body.get('class', []))
                m = re.search(r'postid-(\d+)', classes)
                if m:
                    post_id = m.group(1)

        if post_id:
            ajax_url = f'{self.base}/wp-admin/admin-ajax.php'
            ajax_resp = self.session.post(ajax_url, data={
                'action': 'manga_get_chapters',
                'manga': post_id,
            }, timeout=20)
            ajax_soup = BeautifulSoup(ajax_resp.text, 'html.parser')
            chapter_items = ajax_soup.select('li.wp-manga-chapter')
        else:
            # AJAX çalışmadıysa sayfadan direkt çek
            chapter_items = soup.select('li.wp-manga-chapter, .chapters-list li')

        for li in reversed(chapter_items):
            a = li.select_one('a')
            if not a:
                continue
            ch_url = a.get('href', '')
            ch_name = a.get_text(strip=True)
            no_match = re.search(r'(\d+\.?\d*)', ch_name)
            ch_no = no_match.group(1) if no_match else '?'
            episodes.append({'no': ch_no, 'name': sanitize(ch_name), 'url': ch_url})

        if not episodes:
            # Hiç bulanamadıysa sadece mevcut bölümü al
            ep_name_el = soup.select_one('.chapter-heading h1, .c-chapter-header h1, h1')
            ep_name = ep_name_el.get_text(strip=True) if ep_name_el else 'Bölüm 1'
            episodes = [{'no': '1', 'name': sanitize(ep_name), 'url': url}]

        return {'title': title, 'episodes': episodes}

    def get_images(self, ep_url):
        resp = fetch(self.session, ep_url)
        soup = BeautifulSoup(resp.text, 'html.parser')
        container = (soup.select_one('.reading-content') or
                     soup.select_one('.entry-content') or
                     soup.select_one('#chapter-video'))
        if not container:
            container = soup

        imgs = container.select('img')
        urls = []
        for img in imgs:
            src = (img.get('data-src') or img.get('data-lazy-src') or
                   img.get('data-srcset', '').split()[0] or img.get('src', ''))
            src = src.strip()
            if src and src.startswith('http') and any(
                    ext in src.lower() for ext in ['jpg', 'jpeg', 'webp', 'png', 'gif', 'avif']):
                urls.append(src)
        return urls


# ─── GENERIC ─────────────────────────────────────────────────────────────────

class GenericScraper:

    def __init__(self, session, url):
        self.session = session
        self.url = url
        self.base = '{0.scheme}://{0.netloc}'.format(urlparse(url))

    def get_info(self, url):
        resp = fetch(self.session, url)
        soup = BeautifulSoup(resp.text, 'html.parser')

        title_el = (soup.select_one('meta[property="og:title"]') or
                    soup.select_one('title'))
        title = (title_el.get('content') if title_el and title_el.name == 'meta'
                 else title_el.get_text()) if title_el else 'Webtoon'
        title = sanitize(title.split('|')[0].split(' - ')[0].strip())

        # Tek bölüm olarak dön
        ep_name_el = soup.select_one('h1, h2')
        ep_name = ep_name_el.get_text(strip=True) if ep_name_el else 'Bölüm'
        episodes = [{'no': '1', 'name': sanitize(ep_name), 'url': url}]

        return {'title': title, 'episodes': episodes}

    def get_images(self, ep_url):
        resp = fetch(self.session, ep_url)
        soup = BeautifulSoup(resp.text, 'html.parser')

        # Tüm img taglerini bul, büyük olanları (muhtemelen sayfa görselleri) filtrele
        candidates = []
        for img in soup.find_all('img'):
            src = (img.get('data-src') or img.get('data-lazy-src') or
                   img.get('data-srcset', '').split()[0] or img.get('src', ''))
            src = src.strip()
            if not src or not src.startswith('http'):
                continue
            # Boyut filtresi - küçük ikonları at
            w = img.get('width', '0')
            h = img.get('height', '0')
            try:
                w, h = int(w), int(h)
                if w < 100 or h < 100:
                    continue
            except ValueError:
                pass
            if any(ext in src.lower() for ext in ['jpg', 'jpeg', 'webp', 'png', 'gif']):
                candidates.append(src)

        return candidates


# ─── Downloader ───────────────────────────────────────────────────────────────

def download_image(session, img_url: str, save_path: Path, referer: str = ''):
    """Tek bir resmi indir."""
    if save_path.exists():
        return  # Var olan dosyayı atla

    headers = {}
    if referer:
        headers['Referer'] = referer

    resp = session.get(img_url, headers=headers, timeout=30, stream=True)
    resp.raise_for_status()

    ct = resp.headers.get('Content-Type', '')
    ext = get_ext(img_url, ct)

    # Uzantı yoksa ya da yanlışsa düzelt
    if not save_path.suffix or save_path.suffix.lstrip('.') not in ['jpg','jpeg','webp','png','gif','avif']:
        save_path = save_path.with_suffix(f'.{ext}')

    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, 'wb') as f:
        for chunk in resp.iter_content(8192):
            f.write(chunk)


def download_episode(scraper, ep: dict, output_dir: Path, delay: float = 0.3):
    """Bir bölümün tüm resimlerini indir."""
    ep_dir = output_dir / ep['name'] / 'Orjinal'
    ep_dir.mkdir(parents=True, exist_ok=True)

    print(f'\n  📥 {ep["name"]}')
    try:
        img_urls = scraper.get_images(ep['url'])
    except Exception as e:
        print(f'  ❌ Resimler alınamadı: {e}')
        return 0

    if not img_urls:
        print('  ⚠️  Resim bulunamadı.')
        return 0

    downloaded = 0
    for i, img_url in enumerate(img_urls, 1):
        ext = img_url.split('.')[-1].split('?')[0].lower()
        if ext not in ['jpg', 'jpeg', 'webp', 'png', 'gif', 'avif']:
            ext = 'jpg'
        save_path = ep_dir / f'{i:03d}.{ext}'
        try:
            download_image(scraper.session, img_url, save_path, referer=ep['url'])
            print(f'     [{i:3d}/{len(img_urls)}] {save_path.name}', end='\r')
            downloaded += 1
        except Exception as e:
            print(f'\n  ⚠️  [{i}/{len(img_urls)}] Hata: {e}')
        time.sleep(delay)

    print(f'     ✅ {downloaded}/{len(img_urls)} resim indirildi          ')
    return downloaded


# ─── Ana Program ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Webtoon/Manga İndirici')
    parser.add_argument('--url', required=True, help='Bölüm veya webtoon URL\'si')
    parser.add_argument('--list-only', action='store_true', help='Sadece bölüm listesini göster')
    parser.add_argument('--mode', choices=['single', 'range', 'specific', 'all', 'last'],
                        default='single', help='İndirme modu')
    parser.add_argument('--start', type=int, default=1, help='Aralık başlangıcı (range modu)')
    parser.add_argument('--end', type=int, default=9999, help='Aralık sonu (range modu)')
    parser.add_argument('--chapters', type=str, default='', help='Virgülle ayrılmış bölüm numaraları')
    parser.add_argument('--output', type=str, default='', help='Çıktı dizini (varsayılan: repo data/projects dizini)')
    parser.add_argument('--delay', type=float, default=0.3, help='İstekler arası gecikme (saniye)')
    parser.add_argument('--site', type=str, default='', help='Site tipi: webtoons/mangadex/madara/generic')
    args = parser.parse_args()

    session = make_session(args.url)
    session.headers['Referer'] = args.url

    # Site tipini belirle
    print('🔍 Site tespit ediliyor...')
    site_type = args.site if args.site else detect_site(args.url, session)
    print(f'   Site: {site_type}')

    # Scraper seç
    if site_type == 'webtoons':
        scraper = WebtoonsScraper(session)
    elif site_type == 'mangadex':
        scraper = MangaDexScraper(session)
    elif site_type == 'madara':
        scraper = MadaraScraper(session, args.url)
    else:
        scraper = GenericScraper(session, args.url)
        # Generic'te site madara olabilir, dene
        try:
            test_resp = fetch(session, args.url)
            test_soup = BeautifulSoup(test_resp.text, 'html.parser')
            if test_soup.select_one('.reading-content, .wp-manga-chapter'):
                scraper = MadaraScraper(session, args.url)
                site_type = 'madara'
                print('   Madara teması tespit edildi.')
        except Exception:
            pass

    # Bilgileri çek
    print('📚 Webtoon bilgileri alınıyor...')
    try:
        info = scraper.get_info(args.url)
    except Exception as e:
        print(f'❌ Bilgiler alınamadı: {e}')
        sys.exit(1)

    title = info['title']
    episodes = info['episodes']

    print(f'\n{"─"*50}')
    print(f'  Webtoon : {title}')
    print(f'  Bölümler: {len(episodes)} adet')
    print(f'{"─"*50}')

    # Sadece liste modu
    if args.list_only:
        print('\nBÖLÜM LİSTESİ:')
        for i, ep in enumerate(episodes, 1):
            print(f'  {i:4d}. {ep["name"]} [{ep["no"]}]  →  {ep["url"]}')
        # JSON olarak da çıkar (Claude'un parse etmesi için)
        out = {'title': title, 'episodes': episodes}
        print('\n__JSON_START__')
        print(json.dumps(out, ensure_ascii=False))
        print('__JSON_END__')
        return

    # İndirilecek bölümleri seç
    to_download = []
    if args.mode == 'single':
        # URL'deki bölümü bul
        current_url = args.url.rstrip('/')
        matched = [ep for ep in episodes if ep['url'].rstrip('/') == current_url]
        to_download = matched if matched else episodes[:1]
    elif args.mode == 'last':
        to_download = episodes[-1:]
    elif args.mode == 'all':
        to_download = episodes
    elif args.mode == 'range':
        to_download = episodes[args.start - 1:args.end]
    elif args.mode == 'specific':
        wanted = set(args.chapters.split(','))
        to_download = [ep for ep in episodes if ep['no'] in wanted]
        if not to_download:
            print(f'⚠️  Belirtilen bölümler bulunamadı: {args.chapters}')
            sys.exit(1)

    # Çıktı dizini
    base_dir = Path(args.output).expanduser().resolve() if args.output else DEFAULT_PROJECTS_DIR
    output_dir = base_dir / title
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f'\n📁 Hedef klasör: {output_dir}')
    print(f'📋 İndirilecek bölüm sayısı: {len(to_download)}\n')

    total_imgs = 0
    for i, ep in enumerate(to_download, 1):
        print(f'[{i}/{len(to_download)}]', end=' ')
        count = download_episode(scraper, ep, output_dir, delay=args.delay)
        total_imgs += count

    print(f'\n{"─"*50}')
    print(f'✅ Tamamlandı!')
    print(f'   İndirilen bölüm: {len(to_download)}')
    print(f'   Toplam resim   : {total_imgs}')
    print(f'   Konum          : {output_dir}')
    print(f'{"─"*50}')


if __name__ == '__main__':
    main()
