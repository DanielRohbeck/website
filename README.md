# danielrohbeck.de

Personal profile and work samples of Daniel Rohbeck. English at `/`, German at `/de/`.

## Structure

| Folder | Content |
|---|---|
| `src/content.py`, `src/content_de.py` | All texts (EN, DE) |
| `src/site.py` | Generator: layout, CSS, JS, legal pages, images in web sizes |
| `src/assets/` | Photos, portrait and fonts (source files) |
| `docs/` | Built site, served by GitHub Pages. Do not edit by hand. |

## Change something

1. Edit the texts in `src/content.py` / `src/content_de.py` (or layout in `src/site.py`).
2. Build: `python3 src/site.py` (writes `docs/`; needs Pillow, fonttools, brotli).
3. Commit `src/` and `docs/` together.

`INDEXING = False` in `src/site.py` keeps the site out of search engines (noindex on every page).
Set it to `True` and rebuild to go public.

Photos: Unsplash licence, credits on the images and in the imprint. Fonts: Archivo and IBM Plex Mono (SIL Open Font License).
