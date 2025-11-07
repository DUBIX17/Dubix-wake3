import express from "express";
import { WebSocket } from "ws";
import path from "path";

const app = express();
app.use(express.static("public"));

// === CONFIG ===
const WS_TARGET_URL = "wss://dubix-wake.onrender.com/ws-audio"; // <-- change this
let lastWsResponses = [];

// Connect to WebSocket target
let ws = new WebSocket(WS_TARGET_URL);
ws.binaryType = "arraybuffer";

function reconnectWS() {
  ws = new WebSocket(WS_TARGET_URL);
  ws.binaryType = "arraybuffer";

  ws.on("open", () => console.log("[WS] Connected to target"));
  ws.on("message", (data) => {
    try {
      const msg = JSON.parse(data.toString());
      lastWsResponses.push(msg);
    } catch {
      console.log("[WS] Ignored non-JSON");
    }
  });
  ws.on("close", () => {
    console.log("[WS] Closed — retrying in 5s");
    setTimeout(reconnectWS, 5000);
  });
  ws.on("error", (err) => console.error("[WS] Error:", err));
}

reconnectWS();

// === ROUTES ===

// Handle raw binary POST (16-bit PCM)
app.post("/stream", express.raw({ type: "*/*", limit: "50mb" }), (req, res) => {
  if (!req.body || !Buffer.isBuffer(req.body)) {
    console.log("[HTTP] Invalid or empty body");
    return res.status(400).send("Invalid body");
  }

  if (ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(req.body); // send as pure binary
      res.sendStatus(200);
    } catch (e) {
      console.error("[WS] Send failed:", e);
      res.status(500).send("WebSocket send error");
    }
  } else {
    console.log("[HTTP] WebSocket not open");
    res.status(503).send("WebSocket not connected");
  }
});

// Poll for responses
app.get("/poll", (req, res) => {
  res.json(lastWsResponses);
});

// Clear responses every 3 seconds
setInterval(() => {
  lastWsResponses = [];
}, 3000);

// Start
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`✅ Server running on port ${PORT}`));
