import asyncio
import streamlink
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import concurrent.futures
import os
import aiohttp
import logging
from ffmpeg import FFmpeg, Progress
from google import genai
from google.genai.types import Part
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import hashlib
import datetime
import io
import re
import shutil
import glob
import wave

load_dotenv()

# Initialize Firebase
FIREBASE_KEY_PATH = os.getenv("FIREBASE_KEY_PATH", "voxblitz-70eca6003735.json")
db = None
if os.path.exists(FIREBASE_KEY_PATH):
    firebase_admin.initialize_app(credentials.Certificate(FIREBASE_KEY_PATH))
    db = firestore.client()

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Twitch API credentials
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")




app = FastAPI()

# Define the origins that should be allowed to make cross-origin requests
origins = [
    "http://localhost:5173",  
    "http://127.0.0.1:5173",  
]

# Add CORS middleware to the application
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # List of allowed origins
    allow_credentials=True,  # Allow cookies and credentials
    allow_methods=["*"],     # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],     # Allow all headers
)




GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
GEMINI_FALLBACK_MODELS = os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.1-flash-lite").split(",")
client = genai.Client(api_key=os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY"))

# Pydantic model for request body
class SearchQuery(BaseModel):
    query: str
    keyword: str
    max_results: int = 10
    max_attempts: int = 3  # how many 10s windows to check, newest first

async def with_retries(fn, *args, attempts=4, delay=1.0):
    """Retry transient network failures (e.g. flaky DNS) with a short backoff."""
    for i in range(attempts):
        try:
            return await fn(*args)
        except aiohttp.ClientConnectionError:
            if i == attempts - 1:
                raise
            await asyncio.sleep(delay * (i + 1))


async def get_access_token(client_id, client_secret):
    """Get an OAuth app access token from Twitch."""
    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            return data["access_token"]


def generate_doc_id(query: str, keyword: str,max_results: str) -> str:
    """Generate a unique document ID for the query and keyword pair."""
    # Use a hash to create a consistent, unique ID
    combined = f"{query.lower()}_{keyword.lower()}_{max_results}"
    return hashlib.md5(combined.encode()).hexdigest()


async def check_cached_results(query: str, keyword: str, max_results:str) -> list:
    """Check Firestore for cached results for the query and keyword."""
    if db is None:
        return None
    doc_id = generate_doc_id(query, keyword,max_results)
    doc_ref = db.collection("voxblitz").document(doc_id)
    doc = await asyncio.to_thread(doc_ref.get)
    if doc.exists:
        logger.info(f"Found cached results for query: {query}, keyword: {keyword}")
        return doc.to_dict().get("results", [])
    return None

async def store_results(query: str, keyword: str, max_results:str, results: list):
    """Store results in Firestore under the query and keyword."""
    if db is None:
        return
    doc_id = generate_doc_id(query, keyword,max_results)
    doc_ref = db.collection("voxblitz").document(doc_id)
    if not (await asyncio.to_thread(doc_ref.get)).exists:

        await asyncio.to_thread(doc_ref.set, {
            "query": query,
            "keyword": keyword,
            "results": results,
            "created_at": datetime.datetime.now()
        })
        logger.info(f"Stored results for query: {query}, keyword: {keyword}")

TITLE_SCAN_PAGES = 3  # pages of 100 top live streams to scan for title matches


def _stream_entry(user_id, user_login, user_name):
    return {
        "user_name": user_name,
        "stream_url": f"https://www.twitch.tv/{user_login}",
        "user_id": user_id,
    }


async def get_live_streams(search_query, client_id, access_token, max_results):
    """Find live streams for a free-text query.

    Twitch has no title search, so combine: streams whose title/name contains the query
    (scanned from the top live streams), live channels whose name matches, and live
    streams in categories that match the query. Title/name matches rank first.
    """
    base = "https://api.twitch.tv/helix/"
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {access_token}"}
    needle = search_query.lower().strip()
    ranked, seen = [], set()

    def add(entry):
        if entry["user_id"] not in seen:
            seen.add(entry["user_id"])
            ranked.append(entry)

    async with aiohttp.ClientSession(headers=headers) as session:
        async def get(path, **params):
            async with session.get(base + path, params=params) as response:
                response.raise_for_status()
                return await response.json()

        # 1. title / channel-name matches among the top live streams
        cursor = None
        for _ in range(TITLE_SCAN_PAGES):
            params = {"first": 100}
            if cursor:
                params["after"] = cursor
            page = await get("streams", **params)
            for st in page.get("data", []):
                if needle in st["title"].lower() or needle in st["user_login"].lower():
                    add(_stream_entry(st["user_id"], st["user_login"], st["user_name"]))
            cursor = page.get("pagination", {}).get("cursor")
            if not cursor:
                break

        # 2. live channels whose name matches (reaches below the top-300 scan)
        data = (await get("search/channels", query=search_query, live_only="true", first=max_results)).get("data", [])
        for ch in data:
            add(_stream_entry(ch["id"], ch["broadcaster_login"], ch["display_name"]))

        # 3. live streams in categories matching the query
        cats = (await get("search/categories", query=search_query, first=3)).get("data", [])
        for cat in cats:
            page = await get("streams", game_id=cat["id"], first=max_results)
            for st in page.get("data", []):
                add(_stream_entry(st["user_id"], st["user_login"], st["user_name"]))

    logger.info(f"Found {len(ranked)} live streams for '{search_query}'")
    return ranked[:max_results]


MAX_STREAMS = 30  # keeps one search within a sane Gemini quota
MAX_WINDOWS = 3  # the live playlist only holds ~28s
SAMPLE_RATE = 16000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # mono, 16-bit
WINDOW_SECONDS = 10
HLS_SEGMENT_SECONDS = 2
MAX_BACKLOG_SEGMENTS = 14  # Twitch keeps only ~28s of segments on the live playlist
MIN_WINDOW_SECONDS = 5  # drop a leftover slice shorter than this
CAPTURE_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=32)


def find_ffmpeg():
    """FFMPEG_PATH, then PATH, then WinGet's install dir (a shell opened before install lacks it on PATH)."""
    env_path = os.getenv("FFMPEG_PATH")
    if env_path:
        return env_path
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.getenv("LOCALAPPDATA")
    if local:
        links = os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe")
        if os.path.exists(links):
            return links
        pkgs = glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "ffmpeg.exe"), recursive=True)
        if pkgs:
            return pkgs[0]
    raise RuntimeError("ffmpeg not found: install it or set FFMPEG_PATH in .env")


def capture_recent_audio(stream_url, seconds):
    """Grab up to `seconds` of the most recent audio, ending at the live edge.

    The live playlist is short, so the result may be shorter than requested.
    Returns raw 16 kHz mono s16le PCM bytes.
    """
    last_err = None
    for _ in range(3):  # streamlink's Twitch lookup can fail transiently (DNS etc.)
        try:
            streams = streamlink.Streamlink().streams(stream_url)
            break
        except Exception as e:
            last_err = e
    else:
        raise last_err
    quality = "audio_only" if "audio_only" in streams else "worst"
    url = streams[quality].to_url()

    segments = min(MAX_BACKLOG_SEGMENTS, -(-seconds // HLS_SEGMENT_SECONDS))
    ff = (
        FFmpeg(find_ffmpeg())
        .input(url, {"live_start_index": str(-segments)})
        .output("pipe:1", {"f": "s16le", "ac": "1", "ar": str(SAMPLE_RATE), "t": str(seconds)})
    )
    return ff.execute()


def split_windows(pcm, window_seconds=WINDOW_SECONDS, max_windows=3):
    """Slice PCM into windows, newest first.

    Yields (seconds_from_window_start_to_end_of_capture, window_length_seconds, wav_bytes).
    """
    size = window_seconds * BYTES_PER_SECOND
    end = len(pcm)
    for k in range(max_windows):
        if end <= 0:
            break
        start = max(0, end - size)
        chunk = pcm[start:end]
        length = len(chunk) / BYTES_PER_SECOND
        if k > 0 and length < MIN_WINDOW_SECONDS:
            break
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(chunk)
        yield (len(pcm) - start) / BYTES_PER_SECOND, length, buf.getvalue()
        end = start


def parse_timestamp(text):
    """First mm:ss or h:mm:ss in Gemini's reply, in seconds; None if there is none."""
    m = re.search(r"(?:(\d+):)?(\d{1,2}):(\d{2})", text or "")
    if not m:
        return None
    return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + int(m.group(3))


def fmt_hms(total):
    """Seconds -> Twitch's ?t= format, e.g. 1h2m3s."""
    h, rem = divmod(max(0, int(total)), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m}m{sec}s"


async def get_current_vod(user_id, client_id, access_token):
    """The channel's in-progress broadcast VOD, or None if the streamer has VODs off."""
    url = "https://api.twitch.tv/helix/videos"
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {access_token}"}
    params = {"user_id": user_id, "type": "archive", "first": 1}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data = (await response.json()).get("data", [])
    if not data:
        return None
    created = datetime.datetime.fromisoformat(data[0]["created_at"].replace("Z", "+00:00"))
    return {"url": data[0]["url"], "created_at": created}


async def detect_keyword(audio_samples, keyword):
    """
    Detect if the keyword is spoken in the audio bytes using Gemini 2.0 Flash.
    """
    # Create an audio part from the bytes. Use 'audio/wav' as MIME type for PCM s16le.
    audio_part = Part.from_bytes(data=audio_samples, mime_type="audio/wav")

    # Construct the prompt to ask Gemini to analyze the audio for the keyword.
    prompt = f"Analyze the provided audio. Is the word '{keyword}' explicitly spoken in this audio? Respond with just the timestamp that word was spoken in if it is, and 'NO' if it is not. Only respond with the timestamp or 'NO'."
    
    models = [GEMINI_MODEL] + [m for m in GEMINI_FALLBACK_MODELS if m != GEMINI_MODEL]
    last_exc = None
    for attempt in range(4):
        # Retry transient errors (429/5xx) with backoff, rotating through fallback models
        model = models[attempt % len(models)]
        try:
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=model,
                contents=[prompt, audio_part],
            )
            gemini_output = (response.text or "").strip().upper()
            logger.info(f"Gemini output for keyword '{keyword}' ({model}): {gemini_output}")
            return gemini_output
        except Exception as e:
            last_exc = e
            code = getattr(e, "code", None)
            if code not in (429, 500, 503, 504):
                break
            m = re.search(r"retry in ([\d.]+)s", str(e))
            delay = min(float(m.group(1)), 30) if m else 2 ** attempt
            logger.warning(f"Gemini {model} transient error {code}, retrying in {delay:.0f}s")
            await asyncio.sleep(delay)
    logger.error(f"Error calling Gemini API for keyword detection with audio: {last_exc}")
    raise last_exc


async def process_stream(stream, keyword, vod_lookup, max_attempts=3):
    """Sliding window over one stream: check the latest 10s, then the 10s before it, and so on."""
    user_name = stream["user_name"]
    stream_url = stream["stream_url"]
    base = {"user_name": user_name, "stream_url": stream_url}
    loop = asyncio.get_running_loop()
    try:
        pcm = await asyncio.wait_for(
            loop.run_in_executor(
                CAPTURE_POOL, capture_recent_audio, stream_url, max_attempts * WINDOW_SECONDS
            ),
            timeout=120.0,
        )
    except Exception as e:
        logger.error(f"Capture failed for {user_name}: {e!r}")
        return {**base, "keyword_detected": False, "reason": f"Capture failed: {str(e)[:200]}"}
    captured_at = datetime.datetime.now(datetime.timezone.utc)
    if not pcm:
        return {**base, "keyword_detected": False, "reason": "No audio captured"}

    last_error = None
    checked = 0
    for k, (back, length, wav) in enumerate(split_windows(pcm, max_windows=max_attempts)):
        logger.info(f"Window {k + 1}/{max_attempts} for {user_name} ({length:.0f}s, starts {back:.0f}s back)")
        try:
            result = await detect_keyword(wav, keyword)
        except Exception as e:
            last_error = str(e)
            continue
        checked += 1
        offset = parse_timestamp(result)
        if offset is None:  # "NO", or anything that isn't a timestamp
            continue
        seconds_ago = max(0, back - offset)
        spoken_at = captured_at - datetime.timedelta(seconds=seconds_ago)
        out = {
            **base,
            "keyword_detected": True,
            "timestamp": result,
            "seconds_ago": round(seconds_ago),
            "spoken_at": spoken_at.isoformat(),
            "link": stream_url,
            "link_type": "live",
        }
        vod = await vod_lookup(stream["user_id"])
        if vod:
            vod_seconds = (spoken_at - vod["created_at"]).total_seconds() - 5  # 5s lead-in
            out["link"] = f"{vod['url']}?t={fmt_hms(vod_seconds)}"
            out["link_type"] = "vod"
        return out

    reason = f"Keyword not detected in {checked} window(s) of {WINDOW_SECONDS}s"
    if last_error:
        reason += f" (last error: {last_error[:200]})"
    return {**base, "keyword_detected": False, "reason": reason}


@app.post("/search_streams")
async def search_streams(query: SearchQuery):
    """API endpoint to search Twitch streams and detect keyword."""
    try:

        query.max_results = min(max(query.max_results, 1), MAX_STREAMS)
        query.max_attempts = min(max(query.max_attempts, 1), MAX_WINDOWS)
        cached_results = await check_cached_results(query.query, query.keyword,f"{query.max_results}_{query.max_attempts}")
        if cached_results:
            logger.info(f"Returning cached results for query: {query.query}, keyword: {query.keyword}")
            return cached_results


        # Get access token
        access_token = await with_retries(get_access_token, CLIENT_ID, CLIENT_SECRET)

        # Fetch streams
        streams = await with_retries(
            get_live_streams, query.query, CLIENT_ID, access_token, query.max_results
        )

        if not streams:
            raise HTTPException(
                status_code=404, detail="No streams found for the query"
            )

        # Process streams concurrently
        vod_cache = {}

        async def vod_lookup(user_id):
            if user_id not in vod_cache:
                try:
                    vod_cache[user_id] = await with_retries(
                        get_current_vod, user_id, CLIENT_ID, access_token
                    )
                except Exception as e:
                    logger.warning(f"VOD lookup failed for {user_id}: {e}")
                    vod_cache[user_id] = None
            return vod_cache[user_id]

        max_attempts = query.max_attempts
        tasks = [process_stream(stream, query.keyword, vod_lookup, max_attempts) for stream in streams]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Format response
        response = []
        for result in results:
            if isinstance(result, Exception):
                response.append({"error": str(result)})
            else:
                if result["keyword_detected"]:
                    logger.info(
                        f"True: Keyword '{query.keyword}' detected in stream {result['user_name']}"
                    )
                response.append(result)

        await store_results(query.query, query.keyword, f"{query.max_results}_{query.max_attempts}", response)

        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


# Run the server with: uvicorn filename:app --host 0.0.0.0 --port 8000
