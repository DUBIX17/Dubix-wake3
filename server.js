import express from 'express';
import { WebSocketServer } from 'ws';
import ort from 'onnxruntime-node';
import path from 'path';
import { fileURLToPath } from 'url';
import axios from 'axios';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const MODEL_PATH = path.join(__dirname, 'ALEKS!!.onnx');
let session;

async function loadModel() {
  session = await ort.InferenceSession.create(MODEL_PATH);
  console.log('ONNX model loaded!');
}
loadModel();

// Express to serve HTML
const app = express();
app.use(express.static(path.join(__dirname, 'public')));
const HTTP_PORT = process.env.HTTP_PORT || 3000;
app.listen(HTTP_PORT, () => console.log(`HTTP server on http://0.0.0.0:${HTTP_PORT}`));

// WebSocket server
const PORT = process.env.PORT || 8765;
const wss = new WebSocketServer({ port: PORT });
console.log(`WebSocket server running on ws://0.0.0.0:${PORT}`);

const THRESHOLD = 0.7;

// Deepgram API config
const DEEPGRAM_API_KEY = process.env.DEEPGRAM_API_KEY;
const DEEPGRAM_URL = 'https://api.deepgram.com/v1/listen?model=general&language=en-US';

// Silence detection: stop after ~2 sec of low amplitude
const SILENCE_THRESHOLD = 0.01;
const SILENCE_MAX_MS = 2000;

wss.on('connection', (ws) => {
  console.log('Client connected');

  let recording = false;
  let audioBuffer = [];
  let lastAudioTime = 0;
  let silenceTimer;

  function processAudioStop() {
    if (!recording || audioBuffer.length === 0) return;

    // Concatenate collected audio into one Float32Array
    const floatBuffer = Float32Array.from(audioBuffer.flat());

    // Send Float32 audio to Deepgram (no conversion to PCM16)
    axios.post(DEEPGRAM_URL, floatBuffer.buffer, {
      headers: {
        'Authorization': `Token ${DEEPGRAM_API_KEY}`,
        'Content-Type': 'audio/l32; rate=16000'  // Float32 PCM
      },
      responseType: 'json'
    }).then(res => {
      ws.send(JSON.stringify({ transcript: res.data?.channel?.alternatives?.[0]?.transcript || '' }));
    }).catch(err => {
      console.error('Deepgram error:', err.message);
    });

    // Reset recording state
    recording = false;
    audioBuffer = [];
    clearTimeout(silenceTimer);
  }

  ws.on('message', async (data) => {
    try {
      if (typeof data === 'string') {
        // Text wake word
        if (data.trim().toLowerCase() === 'alex') {
          ws.send('Alex detected');
          recording = true;
          audioBuffer = [];
        }
      } else if (data instanceof Buffer) {
        const floatArray = new Float32Array(data.buffer);

        if (!recording) {
          // Run wake word detection
          const inputTensor = new ort.Tensor('float32', floatArray, [1, floatArray.length, 1]);
          const results = await session.run({ input: inputTensor });
          const outputName = Object.keys(results)[0];
          const prob = results[outputName].data[0];

          if (prob >= THRESHOLD) {
            ws.send('Alex detected');
            recording = true;
            audioBuffer = [];
          }
        } else {
          // Collect audio while recording
          audioBuffer.push(Array.from(floatArray));
          lastAudioTime = Date.now();

          // Silence timer
          clearTimeout(silenceTimer);
          silenceTimer = setTimeout(() => {
            const now = Date.now();
            if (now - lastAudioTime >= SILENCE_MAX_MS) processAudioStop();
          }, SILENCE_MAX_MS);
        }
      }
    } catch (err) {
      console.error('Error processing message:', err);
    }
  });

  ws.on('close', () => console.log('Client disconnected'));
});
