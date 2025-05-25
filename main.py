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

# Configure logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Twitch API credentials
CLIENT_ID = 'ycjfxdt8nuc7kcevjzinfa8l4xaxz4'
CLIENT_SECRET = 'o99f3qzqhvl58z473ki89jtzfsrgz9'

app = FastAPI()

# Pydantic model for request body
class SearchQuery(BaseModel):
    query: str
    keyword: str = 'hello'
    max_results: int = 5

# Load YamNet model
yamnet_model = hub.load('https://tfhub.dev/google/yamnet/1')

async def get_access_token(client_id, client_secret):
    """Get an OAuth app access token from Twitch."""
    url = 'https://id.twitch.tv/oauth2/token'
    params = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials'
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            return data['access_token']

async def get_live_streams(search_query, client_id, access_token, max_results):
    """Fetch live streams based on a search query."""
    url = 'https://api.twitch.tv/helix/streams'
    headers = {
        'Client-ID': client_id,
        'Authorization': f'Bearer {access_token}'
    }
    params = {'first': max_results, 'game_name': search_query}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data = await response.json()
            streams_data = data.get('data', [])
            if streams_data:
                logger.info(f"Found stream: {streams_data[0]}")
            else:
                logger.info("No streams found for the query")
            streams = [
                {
                    'user_name': stream['user_name'],
                    'stream_url': f'https://www.twitch.tv/{stream["user_login"]}'
                }
                for stream in streams_data
            ]
            return streams

def capture_audio_segment(stream_url, duration=60):
    """Capture a 10-second audio segment from a Twitch stream to feed into Tensorflow yamnet."""
            # Initialize streamlink with options to handle HLS streams
    for attempt in range(max_attempts):
        try:
            session = streamlink.Streamlink()
            session.set_option("hls-duration", duration)  # Specify duration
            session.set_option("hls-live-edge", 3)
            streams = session.streams(stream_url)
            stream_key = 'audio_only' if 'audio_only' in streams else 'worst'
            stream = streams.get(stream_key)
            stream_fd = stream.open()
            if not streams:
                logger.error(f"No streams available for URL: {stream_url}")
                return None

            ffmpeg_cmd = [
                'ffmpeg',
                '-i', 'pipe:0',  # input from stdin
                '-f', 's16le',  # raw 16-bit PCM audio
                '-t', str(duration),  # capture duration
                '-acodec', 'pcm_s16le',
                '-ac', '1',  # mono
                '-ar', '16000',  # 16 kHz
                'pipe:1'  # output to stdout
            ]
                # Run ffmpeg and capture output
            process = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)


            audio_buffer = io.BytesIO()
            chunk_size = 8192  # Read in 8KB chunks
            start_time = time.time()
            while time.time() - start_time < duration + 5:  # Add buffer time
                chunk = stream_fd.read(chunk_size)
                if not chunk:
                    break  # End of stream
                process.stdin.write(chunk)  # Write chunk to FFmpeg
                process.stdin.flush()
                rlist, _, _ = select.select([process.stdout], [], [], 0.1)
                if process.stdout in rlist:
                    output_chunk = process.stdout.read(chunk_size)
                    if output_chunk:
                        audio_buffer.write(output_chunk)
                # if process.poll() is not None:
                #         logger.warning(f"FFmpeg exited early with code {process.returncode}")
                #         break
            
            stream_fd.close()
            process.stdin.close()

            _, stderr = process.communicate(timeout=5)
            if process.returncode != 0:
                logger.error(f"FFmpeg error: {stderr.decode()}")
                return None

            # Convert byte buffer to numpy array
            audio_buffer.seek(0)
            audio_bytes = audio_buffer.read()
            audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0  # Normalize to [-1, 1]        
            return audio_np
        except:
            logger.error(f"Error capturing audio:")
            continue
        finally:
            # Ensure resources are cleaned up
            if 'stream_fd' in locals():
                stream_fd.close()
            if 'process' in locals() and process.poll() is None:
                process.terminate()    

            

def detect_keyword(audio_samples, keyword):
    """Detect if the keyword is spoken in the audio using YamNet (synchronous)."""
    try:
        if audio_samples is None:
            return False
        # Ensure audio_samples is a numpy array
        audio_samples = np.array(audio_samples, dtype=np.float32)
        # YAMNet expects mono audio at 16kHz, already handled in capture_audio_segment
        scores, _, _ = yamnet_model(audio_samples)

        class_map_path = hub.resolve('https://tfhub.dev/google/yamnet/1') + '/yamnet_class_map.csv'
        class_names = tf.io.read_file(class_map_path).numpy().decode('utf-8').splitlines()[1:]
        class_names = [line.split(',')[1] for line in class_names]

        speech_idx = class_names.index('Speech') if 'Speech' in class_names else -1
        if speech_idx == -1:
            return False

        mean_scores = np.mean(scores, axis=0)
        speech_score = mean_scores[speech_idx]
        return speech_score > 0.5  # Placeholder threshold
    except Exception as e:
        logger.error(f"Error processing audio for keyword detection: {e}")
        return False

async def process_stream(stream, keyword):
    """Process a single stream: capture audio and detect keyword."""
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        audio_samples = await loop.run_in_executor(pool, capture_audio_segment, stream['stream_url'])
        print("Did we get here?")
        print(audio_samples)
        if audio_samples is not None:
            result = await loop.run_in_executor(pool, detect_keyword, audio_samples, keyword)
            return {'user_name': stream['user_name'], 'keyword_detected': result}
        return {'user_name': stream['user_name'], 'keyword_detected': False}

@app.post("/search_streams")
async def search_streams(query: SearchQuery):
    """API endpoint to search Twitch streams and detect keyword."""
    try:
        # Get access token
        access_token = await get_access_token(CLIENT_ID, CLIENT_SECRET)

        # Fetch streams
        streams = await get_live_streams(query.query, CLIENT_ID, access_token, query.max_results)

        if not streams:
            raise HTTPException(status_code=404, detail="No streams found for the query")

        # Process streams concurrently
        tasks = [process_stream(stream, query.keyword) for stream in streams]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Format response
        response = []
        for result in results:
            if isinstance(result, Exception):
                response.append({'error': str(result)})
            else:
                if result['keyword_detected']:
                    logger.info(f"True: Keyword '{query.keyword}' detected in stream {result['user_name']}")
                response.append(result)

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

# Run the server with: uvicorn filename:app --host 0.0.0.0 --port 8000