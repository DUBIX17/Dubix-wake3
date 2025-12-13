import aiohttp
from aiohttp import web
import numpy as np
import resampy
import json
import os
import time
from openwakeword import Model

# ==========================================================
# CONFIG
# ==========================================================
SAMPLE_RATE = 16000
CHUNK_SIZE = 1280

SILENCE_MAX = 1.0          # seconds of silence before stopping
SILENCE_THRESHOLD = 300    # amplitude threshold
WAKEWORD_THRESHOLD = 0.5
MAX_RECORD_SECONDS = 20

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
DG_MODEL = "nova-3"
DG_LANG = "en"

# ==========================================================
# STATE
# ==========================================================
recording = False
audio_buffer = []
last_non_silent_time = 0
recording_start_time = 0

WAKEWORD_MAP = {
    "Alex": "Alex",
    "Aleks!!": "Alex",
}

# ==========================================================
# HELPERS
# ==========================================================
def is_silence(int16_array: np.ndarray) -> bool:
    return np.max(np.abs(int16_array)) < SILENCE_THRESHOLD


async def send_to_deepgram(audio_bytes: bytes) -> str:
    url = (
        "https://api.deepgram.com/v1/listen"
        f"?model={DG_MODEL}"
        f"&language={DG_LANG}"
        "&encoding=linear16"
        f"&sample_rate={SAMPLE_RATE}"
        "&punctuate=true"
    )

    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}",
        "Content-Type": "application/octet-stream",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, data=audio_bytes) as resp:
            if resp.status != 200:
                print("[Deepgram Error]", resp.status)
                return ""

            result = await resp.json()
            transcript = (
                result.get("results", {})
                .get("channels", [{}])[0]
                .get("alternatives", [{}])[0]
                .get("transcript", "")
            )

            print("[Deepgram Transcript]", transcript)
            return transcript

# ==========================================================
# WEBSOCKET HANDLER
# ==========================================================
async def websocket_handler(request):
    global recording, audio_buffer
    global last_non_silent_time, recording_start_time

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    # Send loaded wakewords to client
    await ws.send_str(json.dumps({
        "loaded_models": owwModel.wakeword_names
    }))

    client_sample_rate = SAMPLE_RATE

    async for msg in ws:

        # Client sends sample rate
        if msg.type == aiohttp.WSMsgType.TEXT:
            try:
                client_sample_rate = int(msg.data)
            except ValueError:
                pass

        # Audio chunk
        elif msg.type == aiohttp.WSMsgType.BINARY:

            audio_bytes = msg.data

            # Ensure int16 alignment
            if len(audio_bytes) % 2:
                audio_bytes += b"\x00"

            data = np.frombuffer(audio_bytes, dtype=np.int16)

            # Resample if needed
            if client_sample_rate != SAMPLE_RATE:
                data = resampy.resample(
                    data,
                    client_sample_rate,
                    SAMPLE_RATE
                ).astype(np.int16)

            # ==================================================
            # WAKEWORD DETECTION
            # ==================================================
            if not recording:
                predictions = owwModel.predict(
                    data.astype(np.float32) / 32768.0
                )

                activated = [
                    WAKEWORD_MAP.get(k, k)
                    for k, v in predictions.items()
                    if v >= WAKEWORD_THRESHOLD
                ]

                if "Alex" in activated:
                    print("[Wakeword] Alex detected")

                    recording = True
                    audio_buffer = []
                    recording_start_time = time.time()
                    last_non_silent_time = time.time()

                    await ws.send_str(json.dumps({
                        "activations": ["Alex"]
                    }))

            # ==================================================
            # RECORDING MODE
            # ==================================================
            if recording:
                audio_buffer.extend(data.tolist())

                if not is_silence(data):
                    last_non_silent_time = time.time()

                now = time.time()
                if (
                    now - last_non_silent_time >= SILENCE_MAX
                    or now - recording_start_time >= MAX_RECORD_SECONDS
                ):
                    print("[Recording stopped]")

                    wav_bytes = np.array(
                        audio_buffer,
                        dtype=np.int16
                    ).tobytes()

                    transcript = await send_to_deepgram(wav_bytes)

                    await ws.send_str(json.dumps({
                        "transcript": transcript
                    }))

                    recording = False
                    audio_buffer = []

    return ws

# ==========================================================
# STATIC FILE
# ==========================================================
async def static_file_handler(request):
    return web.FileResponse("./streaming_client.html")

# ==========================================================
# MAIN
# ==========================================================
if __name__ == "__main__":

    # -------- FORCE CPU (Render has no GPU) --------
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["ORT_DISABLE_CUDA"] = "1"

    base_path = os.path.dirname(os.path.abspath(__file__))
    custom_model_path = os.path.join(base_path, "Aleks!!.onnx")

    # -------- LOAD CUSTOM WAKEWORD ONLY --------
    owwModel = Model(
        custom_wakeword_models=[custom_model_path],
        use_builtin_models=False,      # <-- critical: disable default models
        inference_framework="onnx"
    )

    print("[Loaded wakewords]", owwModel.wakeword_names)

    app = web.Application()
    app.add_routes([
        web.get("/ws", websocket_handler),
        web.get("/", static_file_handler),
    ])

    port = int(os.getenv("PORT", 10000))
    print(f"[Server] Listening on port {port}")

    web.run_app(app, host="0.0.0.0", port=port)
    
