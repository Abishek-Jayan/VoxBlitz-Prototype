# VoxBlitz: Streaming Search Engine

Search live Twitch streams by what is being *said*, not just by their titles and tags.

You enter a search query and a keyword. VoxBlitz finds matching live streams, listens to the most recent ~30 seconds of each one in parallel, asks Gemini whether the keyword was spoken, and returns results like a search engine: a link per match that jumps to the exact moment in the stream's VOD.

Placed 2nd in the North America Google Developer Groups On Campus Solution Challenge 2025. The challenge was to design real-time indexing and keyword search over many concurrent live audio streams. This repo is a working prototype of that idea; the pitch deck is here: [Solution Pitch Deck](https://docs.google.com/presentation/d/1w7FCVq04WD4TT19FcnLCJZKTR5FnZBPSC04IoeGGPj4/edit?usp=sharing)

## How it works

```
React UI ──POST /search_streams──▶ FastAPI
                                     │
        1. Find live streams ────────┤  Twitch Helix API (title/name matches, then categories)
        2. For each stream, in parallel:
             streamlink + ffmpeg ────┤  grab the last ~30s of audio (audio_only HLS)
             sliding window ─────────┤  newest 10s first, then the 10s before it, ...
             Gemini ─────────────────┤  "is the keyword spoken? give the timestamp"
        3. First hit stops that stream's search
        4. Hit -> VOD link ──────────┘  twitch.tv/videos/<id>?t=<offset> (Helix /videos)
                                     │
                     optional Firestore cache of results
```

- **Sliding window:** each stream is captured once (up to 30s), split into 10s windows, and checked newest to oldest until the keyword is found or the window limit is reached. A hit stops further Gemini calls for that stream.
- **Parallel:** all streams are processed concurrently; capture runs in a thread pool and Gemini calls run off the event loop.
- **Exact-moment links:** the keyword's position in the window is mapped to a time in the channel's in-progress VOD, with a 5 second lead-in. If the streamer has VODs disabled, the link falls back to the live stream.
- **Failures are not hits:** a Gemini or capture error never counts as a detection. Transient errors (429/5xx) are retried with backoff, honoring the API's retry-after.

## Setup

Requirements: Python 3.10+, Node 18+, [ffmpeg](https://ffmpeg.org/) (Windows: `winget install Gyan.FFmpeg`).

You need:
- A Twitch app (Client ID + Secret): https://dev.twitch.tv/console/apps
- A Gemini API key (free tier works): https://aistudio.google.com/apikey

```bash
cp .env.example .env        # then fill in CLIENT_ID, CLIENT_SECRET, API_KEY

python -m venv env
env/Scripts/activate        # macOS/Linux: source env/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8000

# in a second terminal
npm install
npm run dev                 # http://localhost:5173
```

Configuration (all optional, via `.env`):

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model used for keyword detection |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.1-flash-lite` | Tried on transient errors |
| `FIREBASE_KEY_PATH` | `voxblitz-70eca6003735.json` | Firestore service account key; without it, caching is off |
| `FFMPEG_PATH` | auto-detected | Set only if ffmpeg is not found on PATH |

## Using it

Enter a search query (a game/category name, a channel name, or a word in a stream title), a keyword, how many streams to check (5-30) and how far back to look (10-30s). Example that reliably returns hits: query `Software and Game Development`, keyword `the`.

You can also call the API directly:

```bash
curl -X POST localhost:8000/search_streams -H "Content-Type: application/json" \
  -d '{"query":"Software and Game Development","keyword":"the","max_results":8,"max_attempts":3}'
```

## Limits (this is a prototype)

- **~30s of history.** Twitch only keeps about 28 seconds of segments on the live playlist, so that is as far back as a search can look. Searching further back would need the VOD.
- **Gemini free-tier rate limits.** The free tier allows only a handful of requests per minute per model, so large searches are slow and some streams may be reported as not fully checked. A paid key removes this.
- **Twitch has no title search.** Stream discovery combines category search, channel-name search and a scan of the top ~300 live streams, so small streams with a matching title can be missed.
- **VOD links are approximate** (within a few seconds), and VODs can lag the live stream.
- **Language.** Detection quality depends on Gemini's handling of the stream's language; keywords are matched as spoken, not translated.
- **No evaluation yet.** Accuracy has not been measured against labeled audio, so precision and recall are unknown. Scale is also untested beyond 30 streams per search.
- Results are cached per query, so repeated searches can return stale "seconds ago" values.

## Stack

React 19, Vite, Tailwind CSS 4 · FastAPI, aiohttp, streamlink, ffmpeg · Gemini API · Firestore (optional)

## License

See [LICENSE](LICENSE).
