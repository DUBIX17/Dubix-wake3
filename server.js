// server.js
import express from "express";
import http from "http";
import WebSocket from "ws";
import bodyParser from "body-parser";

const app = express();
const server = http.createServer(app);
const port = 3000;

// Middleware
app.use(bodyParser.json());
app.use(bodyParser.raw({ type: "audio/*", limit: "10mb" }));

// Connect to WebSocket server (can be WSS with self-signed cert)
const wsClient = new WebSocket("wss://dubix-wake.onrender.com/ws-audio", {
  rejectUnauthorized: false // allow self-signed certs
});

let wsReady = false;
let wsResponses = [];

// Handle incoming WS messages
wsClient.on("message", (message) => {
  console.log("Received from WSS:", message.toString());
  wsResponses.push(message.toString());
});

wsClient.on("open", () => {
  console.log("Connected to WSS server");
  wsReady = true;
});

// HTTP endpoint to receive audio chunks
app.post("/stream-audio", (req, res) => {
  if (!wsReady) return res.status(500).send("WSS not connected");

  // Forward audio chunk to WSS
  wsClient.send(req.body);

  // Return all WSS responses so far
  const responses = wsResponses.slice();
  wsResponses = [];
  res.json({ responses });
});

// Start HTTP server
server.listen(port, () => {
  console.log(`HTTP server running at http://localhost:${port}`);
});
