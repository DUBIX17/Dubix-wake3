import express from "express";
import https from "https";
import fs from "fs";
import { WebSocket } from "ws";
import path from "path";

const app = express();
app.use(express.raw({ type: "*/*", limit: "10mb" })); // for binary audio data
app.use(express.static("public"));

// === CONFIG ===
const WS_TARGET_URL = "wss://dubix-wake.onrender.com/ws-audio"; // <-- change this
let lastWsResponses = [];

// Connect to target WebSocket
const ws = new WebSocket(WS_TARGET_URL);
ws.binaryType = "arraybuffer";

ws.on("open", () => console.log("[WS] Connected to target"));
ws.on("message", (data) => {
  try {
    const msg = JSON.parse(data.toString());
    lastWsResponses.push(msg);
  } catch (e) {
    console.error("[WS] Non-JSON message ignored");
  }
});
ws.on("close", () => console.log("[WS] Closed, retrying soon..."));
ws.on("error", (err) => console.error("[WS] Error:", err));

// Clear responses every 3 seconds
setInterval(() => {
  lastWsResponses = [];
}, 3000);

// === ROUTES ===

// ESP32 / browser posts binary PCM chunks here
app.post("/stream", (req, res) => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(req.body); // forward raw binary
    res.sendStatus(200);
  } else {
    res.status(503).send("WebSocket not connected");
  }
});

// Clients poll here to get last responses
app.get("/poll", (req, res) => {
  res.json(lastWsResponses);
});

// === HTTPS SERVER ===
// In Render you don’t need to self-manage SSL, just use HTTP
// but we keep this for local testing:
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
