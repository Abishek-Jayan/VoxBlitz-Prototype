import asyncio
import tensorflow as tf
import tensorflow_hub as hub
import numpy as np
import ffmpeg
import streamlink  # Correct import
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import io
import concurrent.futures
import time
import aiohttp
import logging
import select
import subprocess
from ffmpeg import FFmpeg, Progress

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Twitch API credentials
CLIENT_ID = "ycjfxdt8nuc7kcevjzinfa8l4xaxz4"
CLIENT_SECRET = "o99f3qzqhvl58z473ki89jtzfsrgz9"

app = FastAPI()


# Pydantic model for request body
class SearchQuery(BaseModel):
    query: str
    keyword: str = "hello"
    max_results: int = 1


# Load YamNet model
yamnet_model = hub.load("https://tfhub.dev/google/yamnet/1")


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


def capture_audio_segment(stream_url, duration=10):
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

    # ffmpeg_cmd = [
    #     "ffmpeg",
    #     "-i",
    #     "pipe:0",
    #     "-f",
    #     "s16le",
    #     "-t",
    #     str(duration),
    #     "-acodec",
    #     "pcm_s16le",
    #     "-ac",
    #     "1",
    #     "-ar",
    #     "16000",
    #     "-loglevel",
    #     "warning",
    #     "pipe:1",
    # ]

    f_fmpeg = (
        FFmpeg().input(stream_new_url).output("pipe:1", {"f":"s16le", "acodec":"pcm_s16le", "ac":"1", "ar":"16000"})
    )
    @f_fmpeg.on("progress")
    def on_progress(progress: Progress):
        print(progress)
        if progress.time.seconds > duration + 5:
            f_fmpeg.terminate()
    audio_bytes = f_fmpeg.execute()
    audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    logger.info(f"Captured {len(audio_np)} samples from {stream_url}")
    return audio_np


def detect_keyword(audio_samples, keyword):
    """Detect if the keyword is spoken in the audio using YamNet (synchronous)."""
    try:
        if audio_samples is None:
            return False
        # Ensure audio_samples is a numpy array
        audio_samples = np.array(audio_samples, dtype=np.float32)
        # YAMNet expects mono audio at 16kHz, already handled in capture_audio_segment
        scores, embeddings, waveform = yamnet_model(audio_samples)
        print("We got here")
        class_map_path = (
            hub.resolve("https://tfhub.dev/google/yamnet/1") + "/assets/yamnet_class_map.csv"
        )
        my_classes = [keyword]
        model = tf.keras.Sequential([
        tf.keras.layers.Input(shape=(1024), dtype=tf.float32),
        tf.keras.layers.Dense(128, activation='relu'),
        tf.keras.layers.Dense(len(my_classes), activation='softmax')
        ])
        model.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=0.0003),
              loss='sparse_categorical_crossentropy',
              metrics=['accuracy'])
        model.fit(embeddings, labels, epochs=15, validation_split=0.2)
        mean_scores = np.mean(scores, axis=0)
        speech_score = mean_scores[]
        print("Did this work?")
        return speech_score > 0.5  # Placeholder threshold
    except Exception as e:
        logger.error(f"Error processing audio for keyword detection: {e}")
        return False


async def process_stream(stream, keyword):
    """Process a single stream: capture audio and detect keyword."""
    try:
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            audio_samples = await asyncio.wait_for(
                loop.run_in_executor(pool, capture_audio_segment, stream["stream_url"]),
                timeout=30.0
            )
            logger.info(f"Audio samples for {stream['user_name']}: {'None' if audio_samples is None else len(audio_samples)}")
            if audio_samples is not None:
                result = await loop.run_in_executor(pool, detect_keyword, audio_samples, keyword)
                return {"user_name": stream["user_name"], "keyword_detected": result}
            return {"user_name": stream["user_name"], "keyword_detected": False}
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
