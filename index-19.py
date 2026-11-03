"""
ManhwaIndo API by Nat
https://www.manhwaindo.my

Fitur:
- Search (AJAX manga_search)
- Latest / Explore (katalog + sampul)
- Detail: judul, sampul, sinopsis, genre, daftar chapter
- Chapter: gambar komik (filter iklan)
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

app = FastAPI(
    title="ManhwaIndo API by Nat",
    description="API komik ManhwaIndo: search, detail, chapter, genre. Iklan difilter.",
    version="1.2.1",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE = "https://www.manhwaindo.my"
TIMEOUT = 22.0
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
    "Referer": BASE + "/",
    "Origin": BASE,
}


def is_ad_image(url: str) -> bool:
    """True = iklan / bukan gambar komik."""
    u = (url or "").lower().strip()
    if not u.startswith("http"):
        return True
    # konten sah
    if "manga-images" in u or "/uploads/manga" in u:
        return u.endswith(".gif")
    if "imgx" in u and ("manga" in u or "thumbnail" in u):
        return False
    if "assets.shngm.id/thumbnail" in u:
        return False
    bad = (
        "logo", "icon", "emoji", "avatar", "gravatar", "spinner", "loading",
        "banner", "iklan", "/ad/", "adservice", "doubleclick", "slot", "casino",
        "promo", "88cdn", "wp-content/themes", "wp-includes", "cropped-manhwaindox",
        "facebook", "twitter", "pixel", "tracking", "gmbr.pro/uploads/",
        "upload.gmbr.pro", "i.88cdn", "advertisement", "bandar", "sigacor",
    )
    if any(b in u for b in bad):
        return True
    if u.endswith(".gif"):
        return True
    return False


def abs_url(url: Optional[str]) -> str:
    if not url:
        return ""
    url = str(url).strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    return urljoin(BASE + "/", url.lstrip("/"))


def slug_from_series_url(url: str) -> str:
    m = re.search(r"/series/([^/?#]+)", url or "")
    return (m.group(1) if m else "").strip("/")


def clean_title(title: str, slug: str = "") -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    t = re.sub(r"(?i)^\s*(ch\.?\s*\d+(?:\.\d+)?\s*)?(manga|manhwa|manhua)\s*", "", t).strip()
    t = re.sub(r"(?i)\s*ch\.?\s*\d+(?:\.\d+)?\s*$", "", t).strip()
    if not t or len(t) < 2:
        t = (slug or "").replace("-", " ").title()
    return t[:120]


def comic_item(title: str, slug: str, thumb: str = "", chapter: str = "") -> Dict[str, Any]:
    thumb = abs_url(thumb)
    if is_ad_image(thumb):
        thumb = ""
    if not thumb and slug:
        first = slug[0] if slug else "x"
        # fallback CDN umum (kadang .webp)
        thumb = f"https://imgx-id.gmbr.pro/uploads/manga-images/{first}/{slug}/thumbnail.jpg"
    return {
        "judul": clean_title(title, slug),
        "slug": slug,
        "thumbnail": thumb,
        "sampul": thumb,
        "chapter": str(chapter or ""),
        "url": f"{BASE}/series/{slug}/",
    }


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, headers={**HEADERS, "Accept": "text/html"})
    if r.status_code == 403:
        raise HTTPException(403, "Akses ditolak (403) oleh ManhwaIndo.")
    if r.status_code == 404:
        raise HTTPException(404, "Halaman tidak ditemukan.")
    r.raise_for_status()
    return r.text


def parse_series_id(html: str) -> Optional[str]:
    for pat in (
        r"seriesId\s*[:=]\s*[\"']?(\d+)",
        r"series\s*[:=]\s*[\"']?(\d+)",
        r"series=(\d+)",
        r"ChapterListConfig\s*=\s*\{[^}]*seriesId:\s*(\d+)",
        r'data-series=["\'](\d+)["\']',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1)
    return None


def extract_images_from_html(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[str] = []
    seen = set()
    nodes = soup.select(
        ".bm-reader img, #readerarea img, .readerarea img, "
        ".entry-content img, .chapter-content img, img"
    )
    for img in nodes:
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-lazy-src")
            or img.get("data-url")
            or img.get("data-original")
            or ""
        ).strip()
        src = abs_url(src)
        if not src or is_ad_image(src):
            continue
        if src.startswith("http://"):
            src = "https://" + src[len("http://"):]
        if src in seen:
            continue
        seen.add(src)
        out.append(src)
    return out


def parse_list_from_html(html: str, limit: int = 60) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    data: List[Dict[str, Any]] = []
    seen = set()
    for a in soup.select("a[href*='/series/']"):
        href = (a.get("href") or "").strip()
        slug = slug_from_series_url(href)
        if not slug or slug in seen or slug in ("series", "page", "explore"):
            continue
        img = a.find("img")
        title = (a.get("title") or "").strip()
        if not title and img is not None:
            title = (img.get("alt") or img.get("title") or "").strip()
        if not title:
            title = a.get_text(" ", strip=True)
        if clean_title(title, slug).lower() in ("series", "manga", "manhwa", "home", "lihat semua"):
            continue
        thumb = ""
        if img is not None:
            thumb = abs_url(img.get("src") or img.get("data-src") or img.get("data-lazy-src") or "")
        seen.add(slug)
        data.append(comic_item(title, slug, thumb))
        if len(data) >= limit:
            break
    return data


@app.get("/")
def root():
    return {
        "status": "online",
        "message": "ManhwaIndo API is running",
        "version": "1.2.1",
        "author": "Nat",
        "source": BASE,
        "endpoints": {
            "latest": "/api/latest?page=1",
            "explore": "/api/explore?page=1",
            "search": "/api/search?q=judul",
            "detail": "/api/detail/{slug}",
            "chapter": "/api/chapter?url=... atau ?id=POST_ID",
            "genres": "/api/genres",
        },
    }


@app.get("/api/latest")
async def latest(page: int = Query(1, ge=1)):
    """Komik terbaru / rekomendasi beranda + explore."""
    data: List[Dict[str, Any]] = []
    seen = set()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            if page <= 1:
                paths = ["/", "/explore/", "/series/"]
            else:
                paths = [f"/explore/page/{page}/", f"/series/page/{page}/"]
            for path in paths:
                if len(data) >= 48:
                    break
                try:
                    html = await fetch_text(client, BASE + path)
                except Exception:
                    continue
                for it in parse_list_from_html(html, limit=48):
                    if it["slug"] in seen:
                        continue
                    seen.add(it["slug"])
                    data.append(it)
                    if len(data) >= 48:
                        break
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Latest gagal: {e}")
    return {"status": True, "page": page, "total": len(data), "data": data}


@app.get("/api/explore")
async def explore(page: int = Query(1, ge=1)):
    """Katalog /explore/ (ribuan series)."""
    path = "/explore/" if page <= 1 else f"/explore/page/{page}/"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            html = await fetch_text(client, BASE + path)
            data = parse_list_from_html(html, limit=80)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Explore gagal: {e}")
    return {"status": True, "page": page, "total": len(data), "data": data}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1, description="Kata kunci judul")):
    """Cari komik (endpoint AJAX resmi ManhwaIndo)."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            r = await client.get(
                f"{BASE}/wp-admin/admin-ajax.php",
                params={"action": "manga_search", "q": q},
                headers={
                    **HEADERS,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
            )
            if r.status_code == 403:
                raise HTTPException(403, "Search diblokir (403).")
            r.raise_for_status()
            rows = r.json() or []
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Search gagal: {e}")

    data: List[Dict[str, Any]] = []
    seen = set()
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            slug = slug_from_series_url(row.get("url") or "")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            data.append(
                comic_item(
                    row.get("title") or "",
                    slug,
                    row.get("thumbnail") or "",
                    row.get("chapter") or "",
                )
            )
    return {"status": True, "query": q, "total": len(data), "data": data}


@app.get("/api/genres")
async def genres():
    """Daftar genre dari filter explore (checkbox) + link /genres/."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            html = await fetch_text(client, BASE + "/explore/")
            soup = BeautifulSoup(html, "html.parser")
            out: List[Dict[str, str]] = []
            seen = set()
            # checkbox name=genre[] value=action
            for inp in soup.select('input[name="genre[]"]'):
                gslug = (inp.get("value") or "").strip()
                if not gslug or gslug in seen:
                    continue
                label = inp.find_parent("label")
                name = ""
                if label is not None:
                    name = label.get_text(" ", strip=True)
                name = name or gslug.replace("-", " ").title()
                seen.add(gslug)
                out.append({
                    "nama": name[:60],
                    "slug": gslug,
                    "url": f"{BASE}/genres/{gslug}/",
                })
            # fallback link /genres/slug
            for a in soup.select("a[href*='/genres/'], a[href*='/genre/']"):
                href = (a.get("href") or "").strip()
                m = re.search(r"/genres?/([^/?#]+)", href)
                if not m:
                    continue
                gslug = m.group(1).strip("/")
                if not gslug or gslug in seen:
                    continue
                name = a.get_text(" ", strip=True) or gslug.replace("-", " ").title()
                seen.add(gslug)
                out.append({
                    "nama": name[:60],
                    "slug": gslug,
                    "url": f"{BASE}/genres/{gslug}/",
                })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Genres gagal: {e}")
    return {"status": True, "total": len(out), "data": out}


@app.get("/api/genre/{slug}")
async def genre_list(slug: str, page: int = Query(1, ge=1)):
    """Komik per genre (/genres/{slug}/)."""
    slug = slug.strip().strip("/")
    # situs memakai /genres/ bukan /genre/
    if page <= 1:
        paths = [f"/genres/{slug}/", f"/genre/{slug}/", f"/explore/?genre[]={slug}"]
    else:
        paths = [f"/genres/{slug}/page/{page}/", f"/genre/{slug}/page/{page}/"]
    data: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            for path in paths:
                try:
                    html = await fetch_text(client, BASE + path)
                    data = parse_list_from_html(html, limit=80)
                    if data:
                        break
                except Exception:
                    continue
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Genre list gagal: {e}")
    return {"status": True, "genre": slug, "page": page, "total": len(data), "data": data}


@app.get("/api/detail/{slug}")
async def detail(slug: str):
    """
    Detail komik:
    judul, sampul, sinopsis, genre, daftar chapter lengkap.
    """
    slug = slug.strip().strip("/")
    if slug.startswith("series/"):
        slug = slug.split("/", 1)[-1]

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            html = await fetch_text(client, f"{BASE}/series/{slug}/")
            soup = BeautifulSoup(html, "html.parser")

            title = ""
            h1 = soup.select_one("h1.bm-series__title, h1")
            if h1:
                title = h1.get_text(" ", strip=True)
            if not title:
                ogt = soup.find("meta", property="og:title")
                if ogt:
                    title = re.split(r"[–\-|]", (ogt.get("content") or ""), 1)[0].strip()
            title = clean_title(title, slug)

            thumb = ""
            im = soup.select_one(".bm-series__cover img, .bm-cover img, img.wp-post-image")
            if im is not None:
                thumb = abs_url(im.get("src") or im.get("data-src") or "")
            if not thumb:
                ogi = soup.find("meta", property="og:image")
                if ogi:
                    thumb = abs_url(ogi.get("content") or "")
            if is_ad_image(thumb):
                thumb = ""

            synopsis = ""
            for sel in (
                ".bm-synopsis__body",
                ".bm-synopsis",
                ".bm-series__desc",
                ".entry-content p",
                ".summary",
                ".description",
            ):
                el = soup.select_one(sel)
                if el:
                    synopsis = el.get_text(" ", strip=True)
                    synopsis = re.sub(r"(?i)^\s*sinopsis\s*", "", synopsis).strip()
                    if len(synopsis) > 40:
                        break
            if not synopsis:
                ogd = soup.find("meta", property="og:description") or soup.find(
                    "meta", attrs={"name": "description"}
                )
                if ogd:
                    synopsis = (ogd.get("content") or "").strip()

            genres: List[str] = []
            for a in soup.select("a[href*='/genres/'], a[href*='/genre/'], .bm-chip, .bm-chips a"):
                g = a.get_text(" ", strip=True)
                if g and len(g) < 40 and g.lower() not in ("genre", "genres"):
                    genres.append(g)
            genres = list(dict.fromkeys(genres))[:20]

            status = ""
            info_text = ""
            info = soup.select_one(".bm-series__info")
            if info:
                info_text = info.get_text(" ", strip=True)
                if re.search(r"(?i)ongoing", info_text):
                    status = "Ongoing"
                elif re.search(r"(?i)completed|tamat", info_text):
                    status = "Completed"

            series_id = parse_series_id(html)
            chapters: List[Dict[str, Any]] = []
            if series_id:
                try:
                    ch = await client.get(
                        f"{BASE}/wp-json/agc/v1/chapters",
                        params={"series": series_id},
                        headers={**HEADERS, "Accept": "application/json"},
                    )
                    if ch.status_code == 200:
                        rows = ch.json() or []
                        if isinstance(rows, list):
                            for row in rows:
                                if not isinstance(row, dict):
                                    continue
                                num = str(row.get("chapter") or "").strip()
                                cid = row.get("id")
                                url = abs_url(row.get("url") or "")
                                chapters.append({
                                    "id": str(cid) if cid is not None else "",
                                    "chapter": num,
                                    "title": f"Chapter {num}" if num else "Chapter",
                                    "url": url,
                                    "time": row.get("time") or "",
                                })
                except Exception:
                    chapters = []

            if not chapters:
                for a in soup.select("a[href*='-chapter-'], a[href*='chapter']"):
                    href = abs_url(a.get("href") or "")
                    if not href or "/series/" in href:
                        continue
                    t = a.get_text(" ", strip=True)
                    m = re.search(r"(\d+(?:\.\d+)?)", t) or re.search(
                        r"chapter-(\d+(?:\.\d+)?)", href, re.I
                    )
                    num = m.group(1) if m else ""
                    chapters.append({
                        "id": "",
                        "chapter": num,
                        "title": t or (f"Chapter {num}" if num else "Chapter"),
                        "url": href,
                        "time": "",
                    })
                seen_u = set()
                uniq = []
                for c in chapters:
                    if c["url"] in seen_u:
                        continue
                    seen_u.add(c["url"])
                    uniq.append(c)
                chapters = uniq

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Detail gagal: {e}")

    return {
        "status": True,
        "judul": title,
        "slug": slug,
        "thumbnail": thumb,
        "sampul": thumb,
        "sinopsis": synopsis[:2500],
        "genres": genres,
        "status": status,
        "series_id": series_id or "",
        "total_chapter": len(chapters),
        "chapters": chapters,
        "url": f"{BASE}/series/{slug}/",
    }


@app.get("/api/chapter")
async def chapter(
    id: str = Query("", description="WordPress post ID chapter"),
    url: str = Query("", description="URL halaman chapter penuh"),
):
    """Gambar halaman chapter (iklan otomatis dibuang)."""
    if not id and not url:
        raise HTTPException(400, "Berikan id= atau url=")
    page_url = abs_url(url) if url else ""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            if not page_url and id:
                page_url = f"{BASE}/?p={id}"
            html = await fetch_text(client, page_url)
            images = extract_images_from_html(html)
            if len(images) < 2 and id and "chapter" not in page_url.lower():
                soup = BeautifulSoup(html, "html.parser")
                canon = soup.find("link", rel="canonical")
                if canon and canon.get("href"):
                    page_url = abs_url(canon.get("href"))
                    html = await fetch_text(client, page_url)
                    images = extract_images_from_html(html)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Chapter gagal: {e}")

    if not images:
        raise HTTPException(404, "Gambar chapter kosong / semua terfilter sebagai iklan.")
    return {
        "status": True,
        "url": page_url,
        "total": len(images),
        "images": images,
        "gambar": images,
    }


handler = Mangum(app)
