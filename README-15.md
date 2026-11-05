# ManhwaIndo API by Nat

API scraper **ManhwaIndo** (`https://www.manhwaindo.my`)

## Fitur
- Search komik
- Daftar / explore + sampul
- Detail: judul, sampul, sinopsis, genre, status
- Daftar chapter lengkap
- Gambar chapter (filter iklan)

## Deploy Vercel
1. Buat repo GitHub baru
2. Upload semua file di folder ini (root repo)
3. Import project di Vercel → Deploy

## Endpoint

| Method | Path | Keterangan |
|--------|------|------------|
| GET | `/` | Status API |
| GET | `/api/latest?page=1` | Update / rekomendasi |
| GET | `/api/explore?page=1` | Katalog |
| GET | `/api/search?q=eleceed` | Cari |
| GET | `/api/detail/eleceed` | Detail + chapter |
| GET | `/api/chapter?url=...` | Gambar chapter |
| GET | `/api/chapter?id=505708` | Gambar via post ID |
| GET | `/api/genres` | Daftar genre |
| GET | `/api/genres/{slug} (API: /api/genre/{slug})?page=1` | Komik per genre |

## Contoh
```
/api/search?q=solo
/api/detail/eleceed
/api/chapter?url=https://www.manhwaindo.my/eleceed-chapter-424/
/api/genres
```

Version: 1.2.2 — chapter images hanya panel manga (tanpa cover/tracking).

By: Nat
