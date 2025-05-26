import asyncio
import streamlink
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import concurrent.futures
import os
import aiohttp
import logging
from ffmpeg import FFmpeg, Progress
from google import genai
from google.genai.types import Part


# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Twitch API credentials
CLIENT_ID = "ycjfxdt8nuc7kcevjzinfa8l4xaxz4"
CLIENT_SECRET = "o99f3qzqhvl58z473ki89jtzfsrgz9"


app = FastAPI()


client = genai.Client(api_key="AIzaSyAkTu1APiM_33fZaVeNSXPkPU5v8nUKs2I")

# Pydantic model for request body
class SearchQuery(BaseModel):
    query: str
    keyword: str
    max_results: int = 5

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


async def get_live_streams(search_query, client_id, access_token, max_results):
    """Fetch live streams based on a search query."""
    url = "https://api.twitch.tv/helix/streams"
    headers = {"Client-ID": client_id, "Authorization": f"Bearer {access_token}"}
    params = {"first": max_results, "game_name": search_query}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            streams_data = data.get("data", [])
            if streams_data:
                logger.info(f"Found stream: {streams_data[0]}")
            else:
                logger.info("No streams found for the query")
            streams = [
                {
                    "user_name": stream["user_name"],
                    "stream_url": f'https://www.twitch.tv/{stream["user_login"]}',
                }
                for stream in streams_data
            ]
            return streams


def capture_audio_segment(stream_url, duration=120):
    """Capture a 10-second audio segment from a Twitch stream to feed into Tensorflow YAMNet."""
    # for attempt in range(max_attempts):
    # Initialize streamlink with options to handle HLS streams
    session = streamlink.Streamlink()
    session.set_option("hls-duration", duration)
    session.set_option("hls-live-edge", 4)
    # Configure FFmpeg options for Streamlink
    streams = session.streams(stream_url)



    # Prefer 'audio_only', fallback to 'worst'
    quality = "audio_only" if "audio_only" in streams else "worst"

    stream_new_url = streams[quality].to_url()

    f_fmpeg = (
        FFmpeg().input(stream_new_url).output("pipe:1", {"f":"wav", "ac":"1", "ar":"16000"})
    )
    @f_fmpeg.on("progress")
    def on_progress(progress: Progress):
        print(progress)
        if progress.time.seconds > duration + 5:
            f_fmpeg.terminate()
    audio_bytes = f_fmpeg.execute()
    return audio_bytes


async def detect_keyword(audio_samples, keyword):
    """
    Detect if the keyword is spoken in the audio bytes using Gemini 2.0 Flash.
    """
    # Create an audio part from the bytes. Use 'audio/wav' as MIME type for PCM s16le.
    audio_part = Part.from_bytes(data=audio_samples, mime_type="audio/wav")
    print("Did we reach here?")

    # Construct the prompt to ask Gemini to analyze the audio for the keyword.
    prompt = f"Analyze the provided audio. Is the word '{keyword}' explicitly spoken in this audio? Respond with just the timestamp that word was spoken in if it is, and 'NO' if it is not. Only respond with the timestamp or 'NO'."
    
    try:
        # Pass both the text prompt and the audio part to Gemini 2.0 Flash
        response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=[
        prompt,
        audio_part
        ]
        )
        print(response.text)
        gemini_output = response.text.strip().upper()
        logger.info(f"Gemini output for keyword '{keyword}': {gemini_output}")

        return gemini_output
    except Exception as e:
        logger.error(f"Error calling Gemini API for keyword detection with audio: {e}")
        return False


async def process_stream(stream, keyword):
    """Process a single stream: capture audio and detect keyword."""
    user_name = stream["user_name"]
    stream_url = stream["stream_url"]
    try:
        loop = asyncio.get_event_loop()
        max_workers = os.cpu_count() or 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            audio_samples = await asyncio.wait_for(
                loop.run_in_executor(pool, capture_audio_segment, stream["stream_url"]),
                timeout=600.0
            )
            logger.info(f"Audio samples for {stream['user_name']}: {'None' if audio_samples is None else len(audio_samples)}")
            if audio_samples is None:
                logger.warning(f"No audio captured for {user_name}.")
                return {"user_name": user_name, "keyword_detected": False, "reason": "No audio captured"}
            print("Audio samples is not None")
            # Detect keyword directly with Gemini 2.0 Flash using the audio bytes
            keyword_detected = await detect_keyword(audio_samples, keyword)                

            logger.info(f"Keyword detection for {user_name} complete. Detected: {keyword_detected}")
            return {"user_name": stream["user_name"], "keyword_detected": keyword_detected}
    except asyncio.TimeoutError:
        logger.error(f"Timeout processing stream {stream['user_name']}")
        return {"user_name": stream["user_name"], "keyword_detected": False}
    except Exception as e:
        logger.error(f"Error processing stream {stream['user_name']}: {str(e)}")
        return {"user_name": stream["user_name"], "keyword_detected": False}


@app.post("/search_streams")
async def search_streams(query: SearchQuery):
    """API endpoint to search Twitch streams and detect keyword."""
    try:
        # Get access token
        access_token = await get_access_token(CLIENT_ID, CLIENT_SECRET)

        # Fetch streams
        streams = await get_live_streams(
            query.query, CLIENT_ID, access_token, query.max_results
        )

        if not streams:
            raise HTTPException(
                status_code=404, detail="No streams found for the query"
            )

        # Process streams concurrently
        tasks = [process_stream(stream, query.keyword) for stream in streams]
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

        return response

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error processing request: {str(e)}"
        )


# Run the server with: uvicorn filename:app --host 0.0.0.0 --port 8000
