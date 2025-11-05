import express from "express";
import http from "http";
import WebSocket from "ws";
import bodyParser from "body-parser";

const app = express();
const server = http.createServer(app);
const port = process.env.PORT || 10000; // Render provides PORT in env

// Middleware
app.use(bodyParser.json());
app.use(bodyParser.raw({ type: "audio/*", limit: "20mb" }));

// Connect to WSS server
const wsServerUrl = process.env.WSS_URL || "wss://dubix-wake.onrender.com/ws-audio";
const wsClient = new WebSocket(wsServerUrl, {
  rejectUnauthorized: false // allow self-signed cert for testing
});

let wsReady = false;
let wsResponses = [];

wsClient.on("open", () => {
  console.log("Connected to WSS server");
  wsReady = true;
});

wsClient.on("message", (message) => {
  console.log("Received from WSS:", message.toString());
  wsResponses.push(message.toString());
});

// HTTP endpoint to receive audio chunks
app.post("/stream-audio", (req, res) => {
  if (!wsReady) return res.status(500).send("WSS not connected");

  wsClient.send(req.body);

  const responses = wsResponses.slice();
  wsResponses = [];
  res.json({ responses });
});

server.listen(port, () => {
  console.log(`Server running on port ${port}`);
});
