import express from 'express';
import { WebSocketServer } from 'ws';
import ort from 'onnxruntime-node';
import path from 'path';
import { fileURLToPath } from 'url';
import fs from 'fs';
import os from 'os';
import { randomUUID } from 'crypto';
import http from 'http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const MODEL_PATH = path.join(__dirname, 'ALEKS!!.onnx');
let session;

async function loadModel() {
  session = await ort.InferenceSession.create(MODEL_PATH);
  console.log('ONNX model loaded!');
}
loadModel();

const app = express();
app.use(express.static(path.join(__dirname, 'public')));

// Render sets the port in process.env.PORT
const PORT = process.env.PORT || 3000;

// Create HTTP server to attach WebSocket
const server = http.createServer(app);
server.listen(PORT, () => console.log(`Server running on port ${PORT}`));

// Attach WebSocket server to the same HTTP server
const wss = new WebSocketServer({ server });

console.log(`WebSocket server attached to HTTP server on port ${PORT}`);

const THRESHOLD = 0.7;
const DG_MODEL = 'nova-3';
const DG_LANG = 'en';
const SAMPLE_RATE = 16000;
const SILENCE_MAX_MS = 1000;

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

    const floatBuffer = Float32Array.from(audioBuffer.flat());
    const tmpFile = path.join(os.tmpdir(), `${randomUUID()}.raw`);
    fs.writeFileSync(tmpFile, Buffer.from(floatBuffer.buffer));

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
        if (data.trim().toLowerCase() === 'alex') {
          ws.send('Alex detected');
          recording = true;
          audioBuffer = [];
        }
      } else if (data instanceof Buffer) {
        const floatArray = new Float32Array(data.buffer);

        if (!recording) {
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
          audioBuffer.push(Array.from(floatArray));
          lastAudioTime = Date.now();

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
