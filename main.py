import aiohttp
from aiohttp import web
import numpy as np
import resampy
import argparse
import json
import os
import time
import uuid
import requests
from openwakeword import Model

# ---------------- CONFIG ----------------
CHUNK_SIZE = 1280        # samples per chunk
SAMPLE_RATE = 16000      # server expects 16kHz
SILENCE_MAX_MS = 1000    # stop recording after 1 second of silence
WAKEWORD_THRESHOLD = 0.5 # threshold for OpenWakeWord activation

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DG_MODEL = "nova-3"
DG_LANG = "en"

# ---------------- STATE ----------------
recording = False
audio_buffer = []
last_audio_time = 0

# ---------------- HELPERS ----------------
def int16_to_float32(data: bytes):
    int16_array = np.frombuffer(data, dtype=np.int16)
    return int16_array.astype(np.float32) / 32768.0

def send_to_deepgram(audio_data: bytes):
    try:
        resp = requests.post(
            f"https://api.deepgram.com/v1/listen?model={DG_MODEL}&language={DG_LANG}&encoding=linear16&sample_rate={SAMPLE_RATE}&punctuate=true",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "application/octet-stream"
            },
            data=audio_data
        )
        result = resp.json()
        transcript = result.get("results", {}).get("channels", [{}])[0].get("alternatives", [{}])[0].get("transcript", "")
        print(f"Transcript: {transcript}")
        return transcript
    except Exception as e:
        print(f"Deepgram error: {e}")
        return ""

# ---------------- WEBSOCKET HANDLER ----------------
async def websocket_handler(request):
    global recording, audio_buffer, last_audio_time

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Send loaded models info
    await ws.send_str(json.dumps({"loaded_models": list(owwModel.models.keys())}))

    sample_rate = SAMPLE_RATE  # default
    async for msg in ws:
        if msg.type == aiohttp.WSMsgType.TEXT:
            # client may send sample rate as first message
            try:
                sample_rate = int(msg.data)
            except:
                pass
        elif msg.type == aiohttp.WSMsgType.ERROR:
            print(f"WebSocket error: {ws.exception()}")
        elif msg.type == aiohttp.WSMsgType.BINARY:
            audio_bytes = msg.data
            if len(audio_bytes) % 2 == 1:
                audio_bytes += b'\x00'

            data = np.frombuffer(audio_bytes, dtype=np.int16)
            if sample_rate != SAMPLE_RATE:
                data = resampy.resample(data, sample_rate, SAMPLE_RATE)

            # --- WAKE WORD DETECTION ---
            if not recording:
                predictions = owwModel.predict(data)
                activated = [k for k, v in predictions.items() if v >= WAKEWORD_THRESHOLD]
                if "Alex" in activated:
                    print("Alex detected! Start recording...")
                    recording = True
                    audio_buffer = []
                    last_audio_time = time.time()
                    await ws.send_str(json.dumps({"activations": ["Alex"]}))

            # --- RECORDING PHASE ---
            if recording:
                audio_buffer.extend(data)
                last_audio_time = time.time()

                # Check for silence
                await asyncio.sleep(SILENCE_MAX_MS / 1000)
                if time.time() - last_audio_time >= SILENCE_MAX_MS / 1000:
                    print("Silence detected. Stopping recording...")
                    # Convert int16 buffer to bytes
                    audio_bytes_to_send = np.array(audio_buffer, dtype=np.int16).tobytes()
                    transcript = send_to_deepgram(audio_bytes_to_send)
                    await ws.send_str(json.dumps({"transcript": transcript}))
                    recording = False
                    audio_buffer = []

    return ws

# ---------------- STATIC FILE HANDLER ----------------
async def static_file_handler(request):
    return web.FileResponse('./streaming_client.html')

# ---------------- MAIN ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model_path", type=str, default="", help="Path to wake word model")
    parser.add_argument("--inference_framework", type=str, default="tflite", help="onnx or tflite")
    args = parser.parse_args()

    # Load OpenWakeWord model
    if args.model_path:
        owwModel = Model(wakeword_models=[args.model_path], inference_framework=args.inference_framework)
    else:
        owwModel = Model(inference_framework=args.inference_framework)

    app = web.Application()
    app.add_routes([web.get('/ws', websocket_handler), web.get('/', static_file_handler)])
    web.run_app(app, host="0.0.0.0", port=9000)
