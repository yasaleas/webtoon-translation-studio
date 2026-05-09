import html
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .storage import load_project_metadata, save_project_cover, save_project_metadata

ANILIST_ENDPOINT = "https://graphql.anilist.co"
MAX_COVER_BYTES = 12 * 1024 * 1024
USER_AGENT = "WebtoonTranslationStudio/1.0"

ANILIST_MEDIA_QUERY = """
query ($search: String) {
  Media(search: $search, type: MANGA) {
    id
    siteUrl
    title {
      romaji
      english
      native
    }
    description(asHtml: false)
    coverImage {
      extraLarge
      large
      medium
      color
    }
    startDate {
      year
    }
    status
    format
    countryOfOrigin
    genres
    tags {
      name
      rank
    }
    staff(perPage: 12) {
      edges {
        role
        node {
          name {
            full
            native
          }
        }
      }
    }
  }
}
"""


def fetch_and_store_project_metadata(project_id: str, query: str | None = None, provider: str = "anilist") -> dict[str, Any]:
    if provider != "anilist":
        raise ValueError("Şimdilik sadece AniList metadata kaynağı destekleniyor.")
    search = (query or project_id).strip()
    if not search:
        raise ValueError("Metadata araması için başlık gerekli.")

    media = fetch_anilist_media(search)
    metadata = metadata_from_anilist(project_id, media)
    saved = save_project_metadata(project_id, metadata)

    cover_url = best_cover_url(media)
    if cover_url:
        try:
            content, content_type = download_cover(cover_url)
            saved = save_project_cover(project_id, content, cover_url, content_type)
        except RuntimeError as error:
            saved["coverError"] = str(error)
    return saved


def fetch_anilist_media(search: str) -> dict[str, Any]:
    payload = json.dumps({"query": ANILIST_MEDIA_QUERY, "variables": {"search": search}}).encode("utf-8")
    request = Request(
        ANILIST_ENDPOINT,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AniList isteği başarısız oldu: HTTP {error.code} {detail[:180]}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"AniList'e ulaşılamadı: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("AniList yanıtı çözümlenemedi.") from error

    if data.get("errors"):
        message = data["errors"][0].get("message") if isinstance(data["errors"][0], dict) else str(data["errors"][0])
        raise RuntimeError(f"AniList metadata hatası: {message}")
    media = (data.get("data") or {}).get("Media")
    if not isinstance(media, dict):
        raise ValueError(f"AniList üzerinde sonuç bulunamadı: {search}")
    return media


def metadata_from_anilist(project_id: str, media: dict[str, Any]) -> dict[str, Any]:
    title = media.get("title") or {}
    staff = author_artist_from_staff(media.get("staff") or {})
    year = ((media.get("startDate") or {}).get("year")) or ""
    tags = sorted(
        [tag for tag in media.get("tags") or [] if isinstance(tag, dict) and tag.get("name")],
        key=lambda tag: int(tag.get("rank") or 0),
        reverse=True,
    )
    return {
        **load_project_metadata(project_id),
        "title": title.get("english") or title.get("romaji") or title.get("native") or project_id,
        "originalTitle": title.get("native") or title.get("romaji") or "",
        "author": staff["author"],
        "artist": staff["artist"],
        "status": normalize_status(media.get("status") or ""),
        "year": str(year) if year else "",
        "description": clean_description(media.get("description") or ""),
        "genres": [str(item) for item in (media.get("genres") or [])[:8]],
        "tags": [str(tag["name"]) for tag in tags[:8]],
        "source": {
            "provider": "anilist",
            "id": media.get("id"),
            "url": media.get("siteUrl") or "",
            "format": media.get("format") or "",
            "country": media.get("countryOfOrigin") or "",
        },
    }


def author_artist_from_staff(staff: dict[str, Any]) -> dict[str, str]:
    author = ""
    artist = ""
    first_name = ""
    for edge in staff.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        role = str(edge.get("role") or "").lower()
        name = (((edge.get("node") or {}).get("name") or {}).get("full")) or ""
        if not name:
            continue
        if not first_name:
            first_name = name
        if not author and any(token in role for token in ("story", "author", "original", "creator")):
            author = name
        if not artist and any(token in role for token in ("art", "artist")):
            artist = name
    return {"author": author or first_name, "artist": artist or author or first_name}


def best_cover_url(media: dict[str, Any]) -> str:
    cover = media.get("coverImage") or {}
    return cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""


def download_cover(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=25) as response:
            content_type = response.headers.get("Content-Type", "")
            content = response.read(MAX_COVER_BYTES + 1)
    except HTTPError as error:
        raise RuntimeError(f"Kapak görseli indirilemedi: HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"Kapak görseline ulaşılamadı: {error}") from error
    if len(content) > MAX_COVER_BYTES:
        raise RuntimeError("Kapak görseli çok büyük.")
    return content, content_type


def clean_description(value: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_status(value: str) -> str:
    text = str(value or "").replace("_", " ").strip().title()
    return text
