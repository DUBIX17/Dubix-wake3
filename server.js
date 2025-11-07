import express from "express";
import { WebSocket } from "ws";

const app = express();
app.use(express.static("public"));

// === CONFIG ===
const WS_TARGET_URL = "wss://dubix-wake.onrender.com/ws-audio"; // <-- put your WS target here
let lastWsResponses = [];

// === WebSocket setup ===
let ws;
function connectWS() {
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
    setTimeout(connectWS, 5000);
  });
  ws.on("error", (err) => console.error("[WS] Error:", err.message));
}
connectWS();

// === Handle raw binary uploads manually ===
app.post("/stream", (req, res) => {
  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    const body = Buffer.concat(chunks);
    if (!body.length) {
      console.log("[HTTP] Invalid or empty body");
      return res.status(400).send("Empty body");
    }

    if (ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(body);
        res.sendStatus(200);
      } catch (err) {
        console.error("[WS] Send failed:", err.message);
        res.status(500).send("WebSocket send error");
      }
    } else {
      console.log("[HTTP] WebSocket not connected");
      res.status(503).send("WebSocket not connected");
    }
  });
});

// === Poll for WS JSON responses ===
app.get("/poll", (req, res) => {
  res.json(lastWsResponses);
});

// === Clear WS responses every 3s ===
setInterval(() => {
  lastWsResponses = [];
}, 3000);

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`✅ HTTPS proxy running on port ${PORT}`));
