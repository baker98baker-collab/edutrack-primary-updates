# Daily TikTok Qur'an Nature Bot · بوت تيك توك اليومي (طبيعة + تلاوة)

Produces and uploads one short vertical (9:16, 1080×1920) video per day: a random
nature clip + a **pre‑verified** Qur'an recitation (mp3) + the Arabic verse text
burned on screen, synced to the audio. By default it uploads the result to your
TikTok **inbox as a draft**, so you review and tap Post yourself.

> ### الأمانة — Trust
> النص القرآني والتلاوة **تُجهّز وتُراجَع يدويًا من قِبَلك**. هذا البرنامج **لا يولّد ولا
> يعدّل ولا يجلب** أي نص قرآني أو صوت — يقرأ فقط ملفاتك الموثّقة. أي تلاوة تنقصها
> ملف الصوت أو نصها الموثّق (`text_ar`) **تُتجاوَز ولا تُنشر**.
>
> The Qur'anic text and audio are prepared and verified **by you, by hand**. This
> program never generates, edits, fetches, or transliterates scripture — it only
> reads your verified files. Any entry missing its audio or verified `text_ar` is
> skipped, never posted.

---

## How it works (pipeline)

1. **Pick recitation** — read `assets/recitations/metadata.json`, keep entries that
   have an audio file + verified `text_ar` + duration ≤ `duration.max_seconds`,
   and rotate through them (no immediate repeats). The chosen recitation's full
   length sets the video length, so the ayah is never cut.
2. **Fetch nature clip** — Pexels (portrait) first, automatic Pixabay fallback.
3. **Subtitles** — generate an `.ass` file rendered by **libass** (correct Arabic
   shaping/joining + RTL). `drawtext` is deliberately not used.
4. **Compose** — one ffmpeg pass: scale/crop to 1080×1920, loop the clip to match
   the audio, mux the recitation, burn the subtitles → `output/<date>_<id>.mp4`.
5. **Upload** — TikTok Content Posting API, "upload to inbox" (draft) flow.

## Prerequisites

- **Python 3.9+** and the pip deps: `pip install -r requirements.txt`
- **ffmpeg + ffprobe**, built with **libass / HarfBuzz / FriBidi** (standard
  builds include these). Verify: `ffmpeg -version` and `ffmpeg -filters | grep ass`.
  - Debian/Ubuntu: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
- **An Arabic font** in `assets/fonts/` (e.g. [Amiri](https://github.com/alif-type/amiri/releases)
  or [Scheherazade New](https://software.sil.org/scheherazade/)). Its family name
  must match `subtitles.font_name` in your config (default `Amiri`).
- **API keys**: Pexels and/or Pixabay (free). TikTok developer app (see below).

## Setup

```bash
cd tiktok-quran-bot
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                       # fill in API keys + TikTok creds
cp config.example.json config.json         # tweak duration, style, providers
cp assets/recitations/metadata.example.json assets/recitations/metadata.json
```

Then:
1. Drop an Arabic font into `assets/fonts/`.
2. Put your verified `.mp3` recitations in `assets/recitations/` and describe each
   in `metadata.json` (schema below). Fill `text_ar` with your **verified** text.

### `metadata.json` schema

```json
{
  "recitations": [
    {
      "id": "unique-id",
      "file": "unique-id.mp3",
      "reciter": "your record",
      "surah": "your record",
      "ayah_range": "1-3",
      "text_ar": "النص العربي الموثّق للآية",
      "segments": [
        { "start": 0.0, "end": 4.5, "text_ar": "مقطع متزامن (اختياري)" }
      ]
    }
  ]
}
```

- `text_ar` (required): shown for the whole clip when no `segments` are given.
- `segments` (optional): per‑phrase timings for synced subtitles. Times in seconds.

## TikTok app setup (one time)

1. Create an app at <https://developers.tiktok.com/>, add the **Content Posting
   API** product, and enable the **`video.upload`** scope (inbox/draft flow).
2. Add your TikTok account as a **target user** in the app's sandbox.
3. Register a **redirect URI** exactly matching `TIKTOK_REDIRECT_URI` in `.env`
   (default `http://localhost:8723/callback`).
4. Obtain a refresh token once, on a machine with a browser:
   ```bash
   python scripts/get_refresh_token.py            # scope video.upload
   ```
   Paste the printed `TIKTOK_REFRESH_TOKEN=...` into `.env`.

> **Draft vs. direct:** the default `tiktok.publish_mode` is `inbox` — the video
> lands in your TikTok notifications/inbox and you finish posting in the app.
> `direct` mode auto‑posts but requires TikTok **app audit** approval to post
> publicly; unaudited apps can only direct‑post privately (`SELF_ONLY`).

## Run

```bash
python main.py --no-publish     # produce the MP4 only (great for first test)
python main.py                  # produce + upload draft to TikTok inbox
python main.py --dry-run -v     # produce only, keep temp files, verbose logs
```

## Schedule (daily)

**Linux/macOS cron** — post at 09:00 every day:
```cron
0 9 * * * /full/path/to/tiktok-quran-bot/scripts/run_daily.sh >> /full/path/to/tiktok-quran-bot/logs/cron.log 2>&1
```
`run_daily.sh` handles `cd`, virtualenv activation, PATH, and per‑day logging.

**Windows Task Scheduler** — create a Basic Task, trigger Daily, action:
`python.exe` with arguments `main.py`, "Start in" set to the project folder.

## Configuration highlights (`config.json`)

| Key | Meaning |
|-----|---------|
| `duration.max_seconds` | Recitations longer than this are skipped (cap). |
| `duration.target_seconds` | Informational target (~15s). |
| `stock.providers` | Order to try, e.g. `["pexels","pixabay"]`. |
| `stock.query_terms` | Nature search terms (one picked at random). |
| `subtitles.font_name` / `font_size` / `alignment` | Text style (alignment 2=bottom‑center, 5=middle). |
| `recitation.selection_mode` | `random_no_repeat` (default) or `sequential`. |
| `tiktok.publish_mode` | `inbox` (default) or `direct`. |

## Tests

```bash
pytest -q      # pure-logic tests: selection, .ass generation, ffmpeg cmd, picking
```
These need no ffmpeg, network, or keys.

## Attribution

Pexels and Pixabay are free but ask for credit. Each run logs the source provider
and author of the clip used — keep those if you want to attribute.

## Layout

```
main.py                 pipeline orchestrator (CLI)
config.example.json     tunables
.env.example            secrets template
src/config.py           config + secrets loading
src/recitation.py       select verified recitation, rotation
src/stock_video.py      Pexels → Pixabay fetch
src/subtitles.py        .ass generation (libass)
src/compose.py          single ffmpeg composition
src/tiktok.py           OAuth refresh + inbox/direct upload
src/media.py            ffprobe/ffmpeg helpers
scripts/get_refresh_token.py   one-time OAuth (PKCE) helper
scripts/run_daily.sh    cron wrapper
tests/                  pure-logic unit tests
```
