import express from 'express';
import { WebSocketServer } from 'ws';
import ort from 'onnxruntime-node';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import os from 'os';
import { randomUUID } from 'crypto';
import fetch from 'node-fetch';

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
const DG_MODEL = 'general';
const DG_LANG = 'en-US';
const SAMPLE_RATE = 16000;
const SILENCE_MAX_MS = 2000;

wss.on('connection', (ws) => {
  console.log('Client connected');

  let recording = false;
  let audioBuffer = [];
  let lastAudioTime = 0;
  let silenceTimer;
  let isTranscribing = false;

  async function processAudioStop() {
    if (!recording || audioBuffer.length === 0 || isTranscribing) return;
    isTranscribing = true;

    // Concatenate collected audio into one Float32Array
    const floatBuffer = Float32Array.from(audioBuffer.flat());

    // Write Float32 buffer to temp file
    const tmpFile = path.join(os.tmpdir(), `${randomUUID()}.raw`);
    fs.writeFileSync(tmpFile, Buffer.from(floatBuffer.buffer));

    // POST to Deepgram as linear32
    let transcript = '';
    try {
      const fileData = fs.readFileSync(tmpFile);
      const resp = await fetch(
        `https://api.deepgram.com/v1/listen?model=${DG_MODEL}&language=${DG_LANG}&encoding=linear32&sample_rate=${SAMPLE_RATE}&punctuate=true`,
        {
          method: 'POST',
          headers: {
            Authorization: `Token ${process.env.DEEPGRAM_API_KEY}`,
            'Content-Type': 'application/octet-stream',
          },
          body: fileData,
        }
      );
      const json = await resp.json();
      transcript = json?.results?.channels?.[0]?.alternatives?.[0]?.transcript?.trim() ?? '';
      ws.send(JSON.stringify({ transcript }));
    } catch (err) {
      console.error('Deepgram error:', err.message);
    } finally {
      try { fs.unlinkSync(tmpFile); } catch {}
      recording = false;
      audioBuffer = [];
      isTranscribing = false;
      clearTimeout(silenceTimer);
    }
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
          // Collect audio
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
