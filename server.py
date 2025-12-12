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
SILENCE_MAX = 1.0          # seconds of silence before stopping recording
SILENCE_THRESHOLD = 300    # amplitude threshold for silence detection
WAKEWORD_THRESHOLD = 0.5

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DG_MODEL = "nova-3"
DG_LANG = "en"

# ---------------- STATE ----------------
recording = False
audio_buffer = []
last_non_silent_time = 0

WAKEWORD_MAP = {
    "Alex": "Alex",
    "Aleks!!": "Alex",
}

# ---------------- HELPERS ----------------
def is_silence(int16_array):
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

    # Tell client which wakewords are loaded
    await ws.send_str(json.dumps({"loaded_models": owwModel.wakeword_names}))

    sample_rate = SAMPLE_RATE

    async for msg in ws:

        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                sample_rate = int(msg.data)
            except:
                pass

        elif msg.type == aiohttp.WSMsgType.ERROR:
            print(f"[WS ERROR] {ws.exception()}")

        elif msg.type == aiohttp.WSMsgType.BINARY:

            audio_bytes = msg.data

            if len(audio_bytes) % 2 == 1:
                audio_bytes += b"\x00"

            data = np.frombuffer(audio_bytes, dtype=np.int16)

            if sample_rate != SAMPLE_RATE:
                data = resampy.resample(data, sample_rate, SAMPLE_RATE).astype(np.int16)

            # ---------------- WAKEWORD DETECTION ----------------
            if not recording:

                # OWW expects float32 normalized [-1,1]
                predictions = owwModel.predict(data.astype(np.float32) / 32768.0)
                print("[Wakeword Predictions]", predictions)

                activated = []
                for kw, score in predictions.items():
                    if score >= WAKEWORD_THRESHOLD:
                        activated.append(WAKEWORD_MAP.get(kw, kw))

                if "Alex" in activated:
                    print("[Wakeword] Alex detected → start recording")

                    recording = True
                    audio_buffer = []
                    last_non_silent_time = time.time()

                    await ws.send_str(json.dumps({"activations": ["Alex"]}))

            # ---------------- RECORDING MODE ----------------
            if recording:

                audio_buffer.extend(data.tolist())

                if not is_silence(data):
                    last_non_silent_time = time.time()

                if time.time() - last_non_silent_time >= SILENCE_MAX:
                    print("[Silence] Recording ended")

                    wav_bytes = np.array(audio_buffer, dtype=np.int16).tobytes()
                    transcript = send_to_deepgram(wav_bytes)
                    await ws.send_str(json.dumps({"transcript": transcript}))

                    recording = False
                    audio_buffer = []

    return ws


# ---------------- STATIC FILE ----------------
async def static_file_handler(request):
    return web.FileResponse("./streaming_client.html")


# ---------------- MAIN ----------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    args = parser.parse_args()

    base_path = os.path.dirname(os.path.abspath(__file__))

    # ---------------- LOAD CUSTOM MODEL ----------------
    model_path = os.path.join(base_path, "Aleks!!.onnx")

    # Force CPU provider to avoid GPU errors
    os.environ["CUDA_VISIBLE_DEVICES"] = ""  # disables CUDA
    owwModel = Model(wakeword_models=[model_path], inference_framework="onnx")
    print(f"[Model] Loaded custom wakeword: {model_path}")

    # ---------------- RUN SERVER ----------------
    app = web.Application()
    app.add_routes([
        web.get("/ws", websocket_handler),
        web.get("/", static_file_handler)
    ])

    # Use PORT env variable or default to 10000
    port = int(os.getenv("PORT", 10000))
    print(f"[Server] Starting on port {port}")
    web.run_app(app, host="0.0.0.0", port=port)
        
