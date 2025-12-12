import aiohttp
from aiohttp import web
import numpy as np
import resampy
import argparse
import json
import os
import time
import asyncio
import requests
from openwakeword import Model

# ---------------- CONFIG ----------------
CHUNK_SIZE = 1280
SAMPLE_RATE = 16000
SILENCE_MAX = 1.0              # seconds of real silence before stopping
SILENCE_THRESHOLD = 300        # amplitude threshold for silence detection
WAKEWORD_THRESHOLD = 0.5

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DG_MODEL = "nova-3"
DG_LANG = "en"

# ---------------- STATE ----------------
recording = False
audio_buffer = []
last_non_silent_time = 0

# Map trained keyword → expected keyword
WAKEWORD_MAP = {
    "Aleks!!": "Alex"
}

# ---------------- HELPERS ----------------
def is_silence(int16_array):
    """Return True if audio chunk amplitude is very low."""
    return np.max(np.abs(int16_array)) < SILENCE_THRESHOLD


def send_to_deepgram(audio_bytes: bytes):
    try:
        resp = requests.post(
            f"https://api.deepgram.com/v1/listen"
            f"?model={DG_MODEL}&language={DG_LANG}"
            f"&encoding=linear16&sample_rate={SAMPLE_RATE}&punctuate=true",
            headers={
                "Authorization": f"Token {DEEPGRAM_API_KEY}",
                "Content-Type": "application/octet-stream"
            },
            data=audio_bytes
        )
        result = resp.json()
        transcript = (
            result.get("results", {})
                  .get("channels", [{}])[0]
                  .get("alternatives", [{}])[0]
                  .get("transcript", "")
        )
        print(f"[Deepgram Transcript] {transcript}")
        return transcript

    except Exception as e:
        print(f"[Deepgram Error] {e}")
        return ""


# ---------------- WEBSOCKET HANDLER ----------------
async def websocket_handler(request):
    global recording, audio_buffer, last_non_silent_time

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Inform client which models loaded
    await ws.send_str(json.dumps({"loaded_models": list(owwModel.models.keys())}))

    sample_rate = SAMPLE_RATE

    async for msg in ws:

        # -------- SAMPLE RATE TEXT --------
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                sample_rate = int(msg.data)
            except:
                pass

        # -------- ERROR --------
        elif msg.type == aiohttp.WSMsgType.ERROR:
            print(f"[WS ERROR] {ws.exception()}")

        # -------- AUDIO (BINARY PCM) --------
        elif msg.type == aiohttp.WSMsgType.BINARY:

            audio_bytes = msg.data

            # Fix odd length
            if len(audio_bytes) % 2 == 1:
                audio_bytes += b"\x00"

            # Convert to numpy int16
            data = np.frombuffer(audio_bytes, dtype=np.int16)

            # Resample (if client sample rate differs)
            if sample_rate != SAMPLE_RATE:
                data = resampy.resample(data, sample_rate, SAMPLE_RATE).astype(np.int16)

            # -------------------- WAKEWORD DETECTION --------------------
            if not recording:

                predictions = owwModel.predict(data)

                # Log raw predictions
                print(f"[Wakeword Predictions] {predictions}")

                activated = []
                for kw, score in predictions.items():
                    if score >= WAKEWORD_THRESHOLD:
                        activated.append(WAKEWORD_MAP.get(kw, kw))

                if "Alex" in activated:
                    print("[Wakeword] Alex detected → recording started")

                    recording = True
                    audio_buffer = []
                    last_non_silent_time = time.time()

                    await ws.send_str(json.dumps({"activations": ["Alex"]}))

            # -------------------- RECORDING PHASE --------------------
            if recording:

                # Append audio
                audio_buffer.extend(data.tolist())

                # Silence check
                if not is_silence(data):
                    last_non_silent_time = time.time()

                # If silence > 1 second → stop recording
                if time.time() - last_non_silent_time >= SILENCE_MAX:
                    print("[Silence] Recording ended")

                    # Convert buffer → bytes
                    wav_bytes = np.array(audio_buffer, dtype=np.int16).tobytes()

                    transcript = send_to_deepgram(wav_bytes)

                    await ws.send_str(json.dumps({"transcript": transcript}))

                    # Reset
                    recording = False
                    audio_buffer = []

    return ws


# ---------------- STATIC FILE ----------------
async def static_file_handler(request):
    return web.FileResponse("./streaming_client.html")


# ---------------- MAIN ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--inference_framework", type=str, default=None)
    args = parser.parse_args()

    base_path = os.path.dirname(os.path.abspath(__file__))

    # Try auto-detecting a local model
    model_path = None
    model_type = None

    for file in os.listdir(base_path):
        if file.lower().endswith(".onnx"):
            model_path = os.path.join(base_path, file)
            model_type = "onnx"
            break
        if file.lower().endswith(".tflite"):
            model_path = os.path.join(base_path, file)
            model_type = "tflite"
            break

    # Override framework if user forced it
    if args.inference_framework:
        model_type = args.inference_framework

    # Load model
    if model_path:
        owwModel = Model(
            wakeword_models=[model_path],
            inference_framework=model_type
        )
        print(f"[Model] Loaded custom: {model_path} ({model_type})")

    else:
        owwModel = Model()
        print("[Model] Loaded built-in OWW models")

    # Start server
    app = web.Application()
    app.add_routes([
        web.get("/ws", websocket_handler),
        web.get("/", static_file_handler)
    ])

    web.run_app(app, host="0.0.0.0", port=9000)
        
