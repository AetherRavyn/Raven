/**
 * RAVEN WhatsApp Bridge — Baileys <-> RAVEN HTTP REST
 *
 * Receives WhatsApp messages and forwards them to RAVEN via POST /whatsapp/incoming.
 * Listens on /send for outbound messages from RAVEN to WhatsApp.
 *
 * Env vars:
 *   RAVEN_URL          Base URL of RAVEN web server (default: http://localhost:8001)
 *   BRIDGE_PORT        Port to listen on (default: 3001)
 *   SESSION_DIR        Directory for Baileys auth state (default: ./wa_session)
 */

const {
  default: makeWASocket,
  DisconnectReason,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
} = require("@whiskeysockets/baileys");
const express = require("express");
const axios = require("axios");
const qrcode = require("qrcode-terminal");
const pino = require("pino");
const path = require("path");
const fs = require("fs");

const RAVEN_URL = process.env.RAVEN_URL || "http://localhost:8001";
const BRIDGE_PORT = parseInt(process.env.BRIDGE_PORT || "3001", 10);
const SESSION_DIR = process.env.SESSION_DIR || "./wa_session";

const logger = pino({ level: "info" });

let sock = null;

// ─── Express REST API ────────────────────────────────────────────────────────

const app = express();
app.use(express.json());

/**
 * POST /send
 * Body: { "jid": "1234567890@s.whatsapp.net", "text": "Hello" }
 * Sends a message from RAVEN → WhatsApp.
 */
app.post("/send", async (req, res) => {
  const { jid, text } = req.body;
  if (!jid || !text) {
    return res.status(400).json({ error: "jid and text are required" });
  }
  if (!sock) {
    return res.status(503).json({ error: "WhatsApp not connected" });
  }
  try {
    await sock.sendMessage(jid, { text });
    res.json({ success: true });
  } catch (err) {
    logger.error({ err }, "send error");
    res.status(500).json({ error: err.message });
  }
});

/**
 * GET /status
 * Returns bridge health.
 */
app.get("/status", (req, res) => {
  res.json({ connected: sock !== null, bridge: "whatsapp" });
});

// ─── Baileys WhatsApp Connection ─────────────────────────────────────────────

async function connectToWhatsApp() {
  if (!fs.existsSync(SESSION_DIR)) {
    fs.mkdirSync(SESSION_DIR, { recursive: true });
  }

  const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    logger: pino({ level: "silent" }),
    auth: state,
    printQRInTerminal: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      logger.info("Scan this QR code to connect WhatsApp:");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "close") {
      const shouldReconnect =
        lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
      logger.warn(
        { statusCode: lastDisconnect?.error?.output?.statusCode },
        "Connection closed"
      );
      if (shouldReconnect) {
        logger.info("Reconnecting in 5s...");
        sock = null;
        setTimeout(connectToWhatsApp, 5000);
      } else {
        logger.error("Logged out — delete session and restart to re-pair");
        sock = null;
      }
    } else if (connection === "open") {
      logger.info("WhatsApp connected!");
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const msg of messages) {
      if (msg.key.fromMe) continue; // skip own messages
      if (!msg.message) continue;

      const jid = msg.key.remoteJid;
      const text =
        msg.message.conversation ||
        msg.message.extendedTextMessage?.text ||
        "";

      if (!text) continue;

      const userId = jid.replace("@s.whatsapp.net", "").replace("@g.us", "");

      const payload = {
        user_id: userId,
        chat_id: jid,
        text,
        platform: "whatsapp",
      };

      try {
        await axios.post(`${RAVEN_URL}/whatsapp/incoming`, payload, {
          timeout: 10000,
        });
      } catch (err) {
        logger.error({ err }, "Failed to forward message to RAVEN");
      }
    }
  });
}

// ─── Start ───────────────────────────────────────────────────────────────────

app.listen(BRIDGE_PORT, () => {
  logger.info(`WhatsApp bridge listening on port ${BRIDGE_PORT}`);
});

connectToWhatsApp().catch((err) => {
  logger.error({ err }, "Fatal error starting WhatsApp bridge");
  process.exit(1);
});
