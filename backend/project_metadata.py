import html
import json
import re
import unicodedata
from difflib import SequenceMatcher
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .storage import load_project_metadata, save_project_cover, save_project_metadata

ANILIST_ENDPOINT = "https://graphql.anilist.co"
MANGADEX_API_BASE = "https://api.mangadex.org"
MANGADEX_COVER_BASE = "https://uploads.mangadex.org/covers"
WEBTOON_SEARCH_URL = "https://www.webtoons.com/en/search"
MAX_COVER_BYTES = 12 * 1024 * 1024
USER_AGENT = "WebtoonTranslationStudio/1.0"

ANILIST_MEDIA_FIELDS = """
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
synonyms
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
"""

ANILIST_SEARCH_QUERY = f"""
query ($search: String, $page: Int, $perPage: Int) {{
  Page(page: $page, perPage: $perPage) {{
    media(search: $search, type: MANGA, sort: SEARCH_MATCH) {{
      {ANILIST_MEDIA_FIELDS}
    }}
  }}
}}
"""

ANILIST_MEDIA_QUERY = f"""
query ($id: Int) {{
  Media(id: $id, type: MANGA) {{
    {ANILIST_MEDIA_FIELDS}
  }}
}}
"""


def search_project_metadata(project_id: str, query: str | None = None, provider: str = "all") -> dict[str, Any]:
    search = (query or project_id).strip()
    if not search:
        raise ValueError("Metadata araması için başlık gerekli.")

    providers = ["mangadex", "webtoon", "anilist"] if provider in {"", "all"} else [provider]
    candidates: list[dict[str, Any]] = []
    errors = []
    for item in providers:
        try:
            if item == "mangadex":
                candidates.extend(mangadex_candidates(search))
            elif item == "webtoon":
                candidates.extend(webtoon_candidates(search))
            elif item == "anilist":
                candidates.extend(anilist_candidates(search))
            else:
                raise ValueError(f"Desteklenmeyen metadata kaynağı: {item}")
        except RuntimeError as error:
            errors.append({"provider": item, "message": str(error)})

    for candidate in candidates:
        candidate["score"] = score_candidate(search, candidate_titles(candidate))
    candidates.sort(key=lambda candidate: (candidate.get("score", 0), candidate.get("provider") == "mangadex"), reverse=True)
    return {"query": search, "provider": provider or "all", "candidates": candidates[:12], "errors": errors}


def fetch_and_store_project_metadata(
    project_id: str,
    query: str | None = None,
    provider: str = "anilist",
    source_id: str | int | None = None,
) -> dict[str, Any]:
    if not source_id:
        return {"needsSelection": True, **search_project_metadata(project_id, query, provider)}

    if provider == "anilist":
        media = fetch_anilist_media_by_id(int(source_id))
        metadata = metadata_from_anilist(project_id, media)
        cover_url = best_anilist_cover_url(media)
    elif provider == "mangadex":
        media = fetch_mangadex_manga(str(source_id))
        metadata = metadata_from_mangadex(project_id, media)
        cover_url = best_mangadex_cover_url(media)
    elif provider == "webtoon":
        media = fetch_webtoon_series(str(source_id))
        metadata = metadata_from_webtoon(project_id, media)
        cover_url = media.get("coverUrl", "")
    else:
        raise ValueError(f"Desteklenmeyen metadata kaynağı: {provider}")

    saved = save_project_metadata(project_id, metadata)
    if cover_url:
        try:
            content, content_type = download_cover(cover_url)
            saved = save_project_cover(project_id, content, cover_url, content_type)
        except RuntimeError as error:
            saved["coverError"] = str(error)
    return saved


def graphql_request(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
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
    return data


def fetch_anilist_media_by_id(source_id: int) -> dict[str, Any]:
    media = (graphql_request(ANILIST_MEDIA_QUERY, {"id": source_id}).get("data") or {}).get("Media")
    if not isinstance(media, dict):
        raise ValueError("AniList üzerinde sonuç bulunamadı.")
    return media


def anilist_candidates(search: str) -> list[dict[str, Any]]:
    data = graphql_request(ANILIST_SEARCH_QUERY, {"search": search, "page": 1, "perPage": 10})
    media_items = ((data.get("data") or {}).get("Page") or {}).get("media") or []
    return [candidate_from_anilist(media) for media in media_items if isinstance(media, dict)]


def fetch_anilist_media(search: str) -> dict[str, Any]:
    candidates = anilist_candidates(search)
    if not candidates:
        raise ValueError(f"AniList üzerinde sonuç bulunamadı: {search}")
    return fetch_anilist_media_by_id(int(candidates[0]["sourceId"]))


def mangadex_request(path: str, params: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    query = f"?{urlencode(params or [])}" if params else ""
    request = Request(f"{MANGADEX_API_BASE}{path}{query}", headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MangaDex isteği başarısız oldu: HTTP {error.code} {detail[:180]}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"MangaDex'e ulaşılamadı: {error}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError("MangaDex yanıtı çözümlenemedi.") from error
    if data.get("result") not in {None, "ok"}:
        raise RuntimeError(f"MangaDex metadata hatası: {data.get('result')}")
    return data


def mangadex_includes() -> list[tuple[str, str]]:
    return [("includes[]", "author"), ("includes[]", "artist"), ("includes[]", "cover_art")]


def mangadex_candidates(search: str) -> list[dict[str, Any]]:
    data = mangadex_request("/manga", [("title", search), ("limit", "10"), *mangadex_includes()])
    items = data.get("data") or []
    return [candidate_from_mangadex(item) for item in items if isinstance(item, dict)]


def fetch_mangadex_manga(source_id: str) -> dict[str, Any]:
    data = mangadex_request(f"/manga/{source_id}", mangadex_includes())
    manga = data.get("data")
    if not isinstance(manga, dict):
        raise ValueError("MangaDex üzerinde sonuç bulunamadı.")
    return manga


def webtoon_request(url: str) -> str:
    request = Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        raise RuntimeError(f"WEBTOON isteği başarısız oldu: HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise RuntimeError(f"WEBTOON'a ulaşılamadı: {error}") from error


def webtoon_candidates(search: str) -> list[dict[str, Any]]:
    url = f"{WEBTOON_SEARCH_URL}?{urlencode({'keyword': search})}"
    parser = WebtoonSearchParser()
    parser.feed(webtoon_request(url))
    return [candidate_from_webtoon(item) for item in parser.items]


def fetch_webtoon_series(source_url: str) -> dict[str, Any]:
    if not source_url.startswith("https://www.webtoons.com/"):
        raise ValueError("WEBTOON kaynak adresi geçersiz.")
    parser = WebtoonDetailParser()
    parser.feed(webtoon_request(source_url))
    data = parser.data
    data["sourceUrl"] = data.get("sourceUrl") or source_url
    data["sourceId"] = title_no_from_url(source_url)
    if not data.get("title"):
        raise ValueError("WEBTOON sayfasından başlık okunamadı.")
    return data


def metadata_from_anilist(project_id: str, media: dict[str, Any]) -> dict[str, Any]:
    title = media.get("title") or {}
    synonyms = unique_titles(media.get("synonyms") or [])
    staff = author_artist_from_staff(media.get("staff") or {})
    year = ((media.get("startDate") or {}).get("year")) or ""
    tags = sorted(
        [tag for tag in media.get("tags") or [] if isinstance(tag, dict) and tag.get("name")],
        key=lambda tag: int(tag.get("rank") or 0),
        reverse=True,
    )
    return {
        **(load_project_metadata(project_id) if project_id else {}),
        "title": title.get("english") or title.get("romaji") or title.get("native") or project_id,
        "originalTitle": title.get("native") or title.get("romaji") or "",
        "author": staff["author"],
        "artist": staff["artist"],
        "status": normalize_status(media.get("status") or ""),
        "year": str(year) if year else "",
        "description": clean_description(media.get("description") or ""),
        "synonyms": synonyms,
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


def metadata_from_mangadex(project_id: str, manga: dict[str, Any]) -> dict[str, Any]:
    attributes = manga.get("attributes") or {}
    titles = title_values(attributes)
    author, artist = creators_from_mangadex(manga.get("relationships") or [])
    title = localized_value(attributes.get("title") or {}, ("en", "tr")) or (titles[0] if titles else project_id)
    description = localized_value(attributes.get("description") or {}, ("en", "tr")) or first_localized_value(attributes.get("description") or {})
    return {
        **(load_project_metadata(project_id) if project_id else {}),
        "title": title,
        "originalTitle": original_title_from_mangadex(attributes),
        "author": author,
        "artist": artist or author,
        "status": normalize_status(attributes.get("status") or ""),
        "year": str(attributes.get("year") or ""),
        "description": clean_description(description),
        "synonyms": unique_titles(titles),
        "genres": mangadex_tag_names(attributes.get("tags") or [], {"genre"}),
        "tags": mangadex_tag_names(attributes.get("tags") or [], {"theme", "format"}),
        "source": {
            "provider": "mangadex",
            "id": manga.get("id"),
            "url": f"https://mangadex.org/title/{manga.get('id')}",
            "format": attributes.get("publicationDemographic") or "",
            "country": attributes.get("originalLanguage") or "",
        },
    }


def metadata_from_webtoon(project_id: str, data: dict[str, Any]) -> dict[str, Any]:
    author = data.get("author", "")
    return {
        **(load_project_metadata(project_id) if project_id else {}),
        "title": data.get("title") or project_id,
        "originalTitle": "",
        "author": author,
        "artist": author,
        "status": "",
        "year": "",
        "description": clean_description(data.get("description") or ""),
        "synonyms": unique_titles([data.get("title", "")]),
        "genres": [data["genre"]] if data.get("genre") else [],
        "tags": [data["webtoonType"]] if data.get("webtoonType") else ["WEBTOON"],
        "source": {
            "provider": "webtoon",
            "id": data.get("sourceId") or title_no_from_url(data.get("sourceUrl", "")),
            "url": data.get("sourceUrl") or "",
            "format": data.get("webtoonType") or "WEBTOON",
            "country": "en",
        },
    }


def candidate_from_anilist(media: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata_from_anilist("", media)
    return {
        "provider": "anilist",
        "sourceId": media.get("id"),
        "sourceUrl": media.get("siteUrl") or "",
        "coverUrl": best_anilist_cover_url(media),
        **candidate_payload(metadata),
    }


def candidate_from_mangadex(manga: dict[str, Any]) -> dict[str, Any]:
    metadata = metadata_from_mangadex("", manga)
    return {
        "provider": "mangadex",
        "sourceId": manga.get("id"),
        "sourceUrl": metadata.get("source", {}).get("url", ""),
        "coverUrl": best_mangadex_cover_url(manga),
        **candidate_payload(metadata),
    }


def candidate_from_webtoon(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": "webtoon",
        "sourceId": item.get("sourceUrl") or item.get("sourceId"),
        "sourceUrl": item.get("sourceUrl", ""),
        "coverUrl": item.get("coverUrl", ""),
        "title": item.get("title", ""),
        "originalTitle": "",
        "author": item.get("author", ""),
        "artist": item.get("author", ""),
        "status": "",
        "year": "",
        "description": "",
        "synonyms": unique_titles([item.get("title", "")]),
        "genres": [item["genre"]] if item.get("genre") else [],
        "tags": [item.get("webtoonType", "WEBTOON")],
    }


def candidate_payload(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": metadata.get("title", ""),
        "originalTitle": metadata.get("originalTitle", ""),
        "author": metadata.get("author", ""),
        "artist": metadata.get("artist", ""),
        "status": metadata.get("status", ""),
        "year": metadata.get("year", ""),
        "description": metadata.get("description", ""),
        "synonyms": metadata.get("synonyms", []),
        "genres": metadata.get("genres", []),
        "tags": metadata.get("tags", []),
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


def creators_from_mangadex(relationships: list[dict[str, Any]]) -> tuple[str, str]:
    author = ""
    artist = ""
    for relationship in relationships:
        if not isinstance(relationship, dict):
            continue
        name = ((relationship.get("attributes") or {}).get("name")) or ""
        if not name:
            continue
        if relationship.get("type") == "author" and not author:
            author = name
        if relationship.get("type") == "artist" and not artist:
            artist = name
    return author, artist


def title_values(attributes: dict[str, Any]) -> list[str]:
    values = []
    title = attributes.get("title") or {}
    if isinstance(title, dict):
        values.extend(title.values())
    for alt_title in attributes.get("altTitles") or []:
        if isinstance(alt_title, dict):
            values.extend(alt_title.values())
    return unique_titles(values)


def localized_value(values: dict[str, Any], languages: tuple[str, ...]) -> str:
    for language in languages:
        value = values.get(language)
        if value:
            return str(value).strip()
    return ""


def first_localized_value(values: dict[str, Any]) -> str:
    for value in values.values():
        if value:
            return str(value).strip()
    return ""


def original_title_from_mangadex(attributes: dict[str, Any]) -> str:
    original_language = attributes.get("originalLanguage")
    title = attributes.get("title") or {}
    if isinstance(title, dict) and original_language and title.get(original_language):
        return str(title[original_language]).strip()
    for alt_title in attributes.get("altTitles") or []:
        if isinstance(alt_title, dict) and original_language and alt_title.get(original_language):
            return str(alt_title[original_language]).strip()
    return ""


def mangadex_tag_names(tags: list[dict[str, Any]], groups: set[str]) -> list[str]:
    names = []
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        attributes = tag.get("attributes") or {}
        if attributes.get("group") not in groups:
            continue
        name = localized_value(attributes.get("name") or {}, ("en", "tr")) or first_localized_value(attributes.get("name") or {})
        if name:
            names.append(name)
    return names[:8]


class WebtoonSearchParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.capture_key = ""
        self.capture_tag = ""
        self.capture_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "_card_item" in classes:
            source_url = attributes.get("href", "")
            self.current = {
                "sourceUrl": source_url,
                "sourceId": source_url,
                "webtoonType": attributes.get("data-webtoon-type", "WEBTOON"),
                "genre": webtoon_genre_from_url(source_url),
            }
            return
        if self.current is None:
            return
        if tag == "img" and not self.current.get("coverUrl"):
            self.current["coverUrl"] = attributes.get("src", "")
        elif tag == "strong" and "title" in classes:
            self.start_capture("title", tag)
        elif tag == "div" and "author" in classes:
            self.start_capture("author", tag)

    def handle_data(self, data: str) -> None:
        if self.capture_key:
            self.capture_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture_key and tag == self.capture_tag:
            if self.current is not None:
                self.current[self.capture_key] = clean_text("".join(self.capture_parts))
            self.start_capture("", "")
            return
        if tag == "a" and self.current is not None:
            if self.current.get("title") and self.current.get("sourceUrl"):
                self.items.append(self.current)
            self.current = None

    def start_capture(self, key: str, tag: str) -> None:
        self.capture_key = key
        self.capture_tag = tag
        self.capture_parts = []


class WebtoonDetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.data: dict[str, Any] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "meta":
            return
        attributes = {key: value or "" for key, value in attrs}
        key = attributes.get("property") or attributes.get("name")
        content = html.unescape(attributes.get("content", "")).strip()
        if not key or not content:
            return
        if key == "og:title":
            self.data["title"] = content
        elif key == "og:description":
            self.data["description"] = content
        elif key == "og:image":
            self.data["coverUrl"] = content
        elif key == "og:url":
            self.data["sourceUrl"] = content
        elif key == "com-linewebtoon:webtoon:author":
            self.data["author"] = content
        elif key == "keywords":
            parts = [part.strip() for part in content.split(",") if part.strip()]
            if len(parts) > 1:
                self.data["genre"] = parts[1]


def webtoon_genre_from_url(source_url: str) -> str:
    match = re.search(r"/en/([^/]+)/", source_url)
    return match.group(1).replace("-", " ").title() if match else ""


def title_no_from_url(source_url: str) -> str:
    match = re.search(r"[?&]title_no=(\d+)", source_url)
    return match.group(1) if match else source_url


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def best_anilist_cover_url(media: dict[str, Any]) -> str:
    cover = media.get("coverImage") or {}
    return cover.get("extraLarge") or cover.get("large") or cover.get("medium") or ""


def best_mangadex_cover_url(manga: dict[str, Any]) -> str:
    manga_id = manga.get("id")
    for relationship in manga.get("relationships") or []:
        if not isinstance(relationship, dict) or relationship.get("type") != "cover_art":
            continue
        filename = (relationship.get("attributes") or {}).get("fileName")
        if manga_id and filename:
            return f"{MANGADEX_COVER_BASE}/{manga_id}/{filename}"
    return ""


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
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_status(value: str) -> str:
    return str(value or "").replace("_", " ").strip().title()


def unique_titles(values: list[Any]) -> list[str]:
    seen = set()
    titles = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = normalize_title(text)
        if key in seen:
            continue
        seen.add(key)
        titles.append(text)
    return titles


def candidate_titles(candidate: dict[str, Any]) -> list[str]:
    return unique_titles([candidate.get("title", ""), candidate.get("originalTitle", ""), *(candidate.get("synonyms") or [])])


def score_candidate(query: str, titles: list[str]) -> int:
    normalized_query = normalize_title(query)
    if not normalized_query:
        return 0
    query_tokens = set(normalized_query.split())
    best = 0
    for title in titles:
        normalized_title = normalize_title(title)
        if not normalized_title:
            continue
        if normalized_title == normalized_query:
            return 100
        best = max(best, int(SequenceMatcher(None, normalized_query, normalized_title).ratio() * 100))
        title_tokens = set(normalized_title.split())
        if query_tokens and title_tokens:
            best = max(best, min(92, int((len(query_tokens & title_tokens) / len(query_tokens)) * 100)))
        if normalized_query in normalized_title or normalized_title in normalized_query:
            length_ratio = min(len(normalized_query), len(normalized_title)) / max(len(normalized_query), len(normalized_title))
            best = max(best, int(82 + length_ratio * 14))
    return best


def normalize_title(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(character for character in text if not unicodedata.combining(character))
    text = text.lower().replace("’", "'").replace("ı", "i")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()
