# SC Memories Downloader

Downloader for Snapchat “Download My Data” exports:
downloads the signed ZIPs, extracts them, and copies media files to a single `media/` folder.

## What’s included

- Dark “SC-style” UI (gray + yellow)
- Per-ZIP progress:
  - `%` completed
  - `MB` downloaded
  - `MB/s` download rate
- Per-ZIP controls (in the `Control` column):
  - Click left half: pause / resume
  - Click right half: stop (that ZIP only)
- Pause/Resume support across runs:
  - partial files are saved as `downloads/*.zip.part`
  - when filenames match, downloads continue even if the signed URL changes
- URL refresh:
  - by default the app refreshes the export URLs on every run (requires Playwright login)

## Requirements

- Python 3.x
- Playwright (only needed if you want the app to refresh URLs automatically)

Install dependencies:

```powershell
pip install playwright
python -m playwright install chromium
```

## Run

Refresh URLs (default behavior):

```powershell
python .\Downloader.py
```

If you already have `urls.txt` and want to skip the browser scraping step:

```powershell
python .\Downloader.py --skip-fetch-urls --urls-file .\urls.txt
```

### Optional flags

- `--skip-fetch-urls`: do not scrape export URLs
- `--urls-file`: path to `urls.txt` (default: `urls.txt` next to the script)
- `--min-urls`: minimum number of ZIP links to wait for when scraping
- `--timeout-sec`: scraping timeout in seconds
- `--write-urls-file`: save scraped URLs into `urls.txt`
  - note: this contains signed export links, so keeping it is optional

## Output folders

- `downloads/`: ZIP downloads (and `*.part` while downloading)
- `extracted/`: extracted ZIP contents
- `media/`: copied media files (images/videos) collected from the extracted data

## Privacy

The project does not embed signed ZIP URLs in code.
Signed URLs are normally fetched at runtime and are not stored in `urls.txt` unless you use `--write-urls-file`.

