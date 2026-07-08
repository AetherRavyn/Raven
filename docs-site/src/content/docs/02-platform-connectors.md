---
title: "02 - Platform Connectors"
---

# 02 - Platform Connectors

## Overview

RAVEN is reachable from any platform you already use. Each connector is an async
Python class that translates platform-specific events into the unified message format,
and translates outgoing messages into platform-specific formatting.

```
┌───────────────────────────────────────────────────────────────────────┐
│  You can talk to RAVEN from:                                         │
│                                                                       │
│  📱 Telegram       - Text, voice notes, photos, files, commands      │
│  🎮 Discord        - Text, voice channels, slash commands, embeds    │
│  💬 WhatsApp       - Text, voice notes, images                       │
│  🎤 Microphone     - Live voice on any device with a mic/speaker     │
│  🌐 Web Dashboard  - Browser-based chat + admin panel                │
│  🔌 HTTP API       - For custom integrations, scripts, other bots    │
│                                                                       │
│  RAVEN responds on the SAME platform you talked from.                │
│  If you send a voice note on Telegram, RAVEN replies with a voice    │
│  note. If you type in Discord, RAVEN types back.                     │
└───────────────────────────────────────────────────────────────────────┘
```

---

## Connector 1: Telegram Bot

The primary connector. Telegram's Bot API is the most feature-rich, free, and
reliable platform for bot development.

### Capabilities

| Feature | Supported | How |
|---|---|---|
| Text messages | Yes | Direct message or group mention |
| Voice notes | Yes | Download OGG → STT → brain → TTS → upload OGG |
| Photos / images | Yes | Download → VLM description → brain |
| Files / documents | Yes | Download → extract text → brain |
| Inline buttons | Yes | For confirmations, choices |
| Commands | Yes | `/search`, `/remind`, `/devices`, `/status` |
| Group chats | Yes | Responds when mentioned or replied to |
| Markdown formatting | Yes | Bold, code blocks, links |

### Implementation

```python
from telegram import Update, Bot
from telegram.ext import Application, MessageHandler, CommandHandler, filters
import io, os

class TelegramConnector:
    def __init__(self, brain: RavenBrain, token: str):
        self.brain = brain
        self.app = Application.builder().token(token).build()
        self._register_handlers()

    def _register_handlers(self):
        # Text messages
        self.app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._handle_text
        ))
        # Voice notes
        self.app.add_handler(MessageHandler(
            filters.VOICE | filters.AUDIO, self._handle_voice
        ))
        # Photos
        self.app.add_handler(MessageHandler(
            filters.PHOTO, self._handle_photo
        ))
        # Commands
        self.app.add_handler(CommandHandler("search", self._cmd_search))
        self.app.add_handler(CommandHandler("remind", self._cmd_remind))
        self.app.add_handler(CommandHandler("devices", self._cmd_devices))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("help", self._cmd_help))

    async def _handle_text(self, update: Update, context):
        """Handle a plain text message."""
        message = IncomingMessage(
            id=str(update.message.message_id),
            source="telegram",
            user_id=await self._resolve_user(update.effective_user.id),
            platform_user_id=str(update.effective_user.id),
            input_type="text",
            text=update.message.text,
            reply_context=ReplyContext(
                platform="telegram",
                chat_id=str(update.effective_chat.id),
                reply_to_message_id=str(update.message.message_id),
                supports_markdown=True,
                supports_voice_reply=True,
                supports_images=True,
                supports_buttons=True,
            ),
            timestamp=update.message.date,
        )

        response = await self.brain.handle_message(message)
        await self._send_response(update, response)

    async def _handle_voice(self, update: Update, context):
        """Handle a voice note: download → STT → brain → TTS → send back."""
        voice = update.message.voice or update.message.audio
        file = await context.bot.get_file(voice.file_id)

        # Download voice note
        audio_path = f"/tmp/raven_voice_{update.message.message_id}.ogg"
        await file.download_to_drive(audio_path)

        # Transcribe (STT handles OGG natively)
        transcribed_text = await self.brain.voice_engine.transcribe(audio_path)

        message = IncomingMessage(
            id=str(update.message.message_id),
            source="telegram",
            user_id=await self._resolve_user(update.effective_user.id),
            platform_user_id=str(update.effective_user.id),
            input_type="voice",
            text=transcribed_text,
            audio_path=audio_path,
            is_voice=True,
            reply_context=ReplyContext(
                platform="telegram",
                chat_id=str(update.effective_chat.id),
                reply_to_message_id=str(update.message.message_id),
                supports_markdown=True,
                supports_voice_reply=True,
                supports_images=True,
                supports_buttons=True,
            ),
            timestamp=update.message.date,
        )

        response = await self.brain.handle_message(message)

        # If user sent voice, reply with voice
        if response.text:
            # Generate TTS
            tts_path = await self.brain.voice_engine.synthesize(
                response.text, output_format="ogg"
            )
            response.voice_audio_path = tts_path

        await self._send_response(update, response)

        # Cleanup temp files
        os.unlink(audio_path)
        if response.voice_audio_path:
            os.unlink(response.voice_audio_path)

    async def _handle_photo(self, update: Update, context):
        """Handle a photo: download → VLM description → brain."""
        photo = update.message.photo[-1]  # Largest resolution
        file = await context.bot.get_file(photo.file_id)

        image_path = f"/tmp/raven_photo_{update.message.message_id}.jpg"
        await file.download_to_drive(image_path)

        # Get VLM description of the image
        image_description = await self.brain.vision_engine.describe(image_path)

        # Combine with caption if any
        caption = update.message.caption or ""
        combined_text = f"[User sent a photo: {image_description}] {caption}".strip()

        message = IncomingMessage(
            id=str(update.message.message_id),
            source="telegram",
            user_id=await self._resolve_user(update.effective_user.id),
            platform_user_id=str(update.effective_user.id),
            input_type="image",
            text=combined_text,
            image_path=image_path,
            reply_context=ReplyContext(
                platform="telegram",
                chat_id=str(update.effective_chat.id),
                reply_to_message_id=str(update.message.message_id),
                supports_markdown=True,
                supports_voice_reply=True,
                supports_images=True,
                supports_buttons=True,
            ),
            timestamp=update.message.date,
        )

        response = await self.brain.handle_message(message)
        await self._send_response(update, response)
        os.unlink(image_path)

    async def _send_response(self, update: Update, response: OutgoingMessage):
        """Send a response back to Telegram."""
        chat_id = update.effective_chat.id

        # Send voice if available
        if response.voice_audio_path:
            with open(response.voice_audio_path, 'rb') as audio_file:
                await update.effective_chat.send_voice(
                    voice=audio_file,
                    caption=response.text[:1024] if len(response.text) > 200 else None,
                    reply_to_message_id=update.message.message_id,
                )
            # Also send text version for readability
            if len(response.text) > 200:
                await update.effective_chat.send_message(
                    text=response.text,
                    parse_mode="Markdown",
                    reply_to_message_id=update.message.message_id,
                )
        else:
            # Text-only response
            # Split long messages (Telegram limit: 4096 chars)
            for chunk in self._split_text(response.text, 4000):
                await update.effective_chat.send_message(
                    text=chunk,
                    parse_mode="Markdown",
                    reply_to_message_id=update.message.message_id,
                )

        # Send inline buttons if any
        if response.buttons:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            keyboard = [[InlineKeyboardButton(b["text"], callback_data=b["data"])]
                        for b in response.buttons]
            markup = InlineKeyboardMarkup(keyboard)
            await update.effective_chat.send_message(
                text="Choose an option:",
                reply_markup=markup,
            )

    async def start(self):
        """Start the Telegram bot (long-polling)."""
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        # Keep running
        await asyncio.Event().wait()
```

---

## Connector 2: Discord Bot

Discord adds **voice channel** support -- RAVEN can join a voice channel and talk
in real-time, like another person in the call.

### Capabilities

| Feature | Supported | How |
|---|---|---|
| Text messages | Yes | In any channel where bot is present |
| Voice channels | Yes | Joins VC, listens via Opus, speaks via Opus |
| Slash commands | Yes | `/ask`, `/search`, `/remind`, `/devices` |
| Embeds | Yes | Rich formatted responses |
| Reactions | Yes | For confirmations |
| File uploads | Yes | Images, documents |
| Multiple servers | Yes | Same bot instance, server-specific config |

### Voice Channel Integration

This is the most complex connector because it involves real-time bidirectional audio:

```python
import discord
from discord.ext import commands
import asyncio
import numpy as np

class DiscordConnector:
    def __init__(self, brain: RavenBrain, token: str):
        self.brain = brain
        self.token = token
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self._setup()

    def _setup(self):
        @self.bot.event
        async def on_message(message):
            if message.author.bot:
                return
            await self.bot.process_commands(message)

            if self.bot.user.mentioned_in(message) or isinstance(
                message.channel, discord.DMChannel
            ):
                await self._handle_text(message)

        @self.bot.slash_command(name="join", description="Join your voice channel")
        async def join_voice(ctx):
            if ctx.author.voice:
                channel = ctx.author.voice.channel
                vc = await channel.connect()
                await ctx.respond("I'm here! Talk to me.")
                # Start listening
                asyncio.create_task(self._voice_loop(vc, ctx))
            else:
                await ctx.respond("You need to be in a voice channel first.")

        @self.bot.slash_command(name="leave", description="Leave voice channel")
        async def leave_voice(ctx):
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                await ctx.respond("Bye!")

        @self.bot.slash_command(name="ask", description="Ask RAVEN anything")
        async def ask(ctx, question: str):
            await ctx.defer()  # Show "thinking..."
            message = self._make_message(ctx, question)
            response = await self.brain.handle_message(message)
            await ctx.respond(response.text)

    async def _voice_loop(self, vc: discord.VoiceClient, ctx):
        """Continuously listen and respond in a voice channel.

        This is the core real-time voice loop for Discord.
        """
        # Start receiving audio
        sink = DiscordAudioSink(self.brain)
        vc.start_recording(sink, self._on_recording_done, ctx)

    async def _on_recording_done(self, sink, ctx):
        """Called when a user stops speaking (VAD detected silence)."""
        for user_id, audio_data in sink.audio_data.items():
            # Convert to WAV
            audio_path = f"/tmp/discord_voice_{user_id}.wav"
            audio_data.export(audio_path, format="wav")

            # Transcribe
            text = await self.brain.voice_engine.transcribe(audio_path)
            if not text or len(text.strip()) < 2:
                continue

            # Process through brain
            message = IncomingMessage(
                id=f"discord-voice-{time.time()}",
                source="discord",
                user_id=await self._resolve_user(user_id),
                platform_user_id=str(user_id),
                input_type="voice",
                text=text,
                is_voice=True,
                reply_context=ReplyContext(
                    platform="discord",
                    chat_id=str(ctx.channel.id),
                    guild_id=str(ctx.guild.id) if ctx.guild else None,
                    voice_channel_id=str(ctx.author.voice.channel.id),
                    supports_markdown=True,
                    supports_voice_reply=True,
                    supports_images=True,
                    supports_buttons=False,
                ),
                timestamp=datetime.utcnow(),
            )

            response = await self.brain.handle_message(message)

            # Speak the response in voice channel
            if ctx.voice_client and ctx.voice_client.is_connected():
                tts_path = await self.brain.voice_engine.synthesize(
                    response.text, output_format="wav"
                )
                audio_source = discord.FFmpegPCMAudio(tts_path)
                ctx.voice_client.play(audio_source)

                # Also post text in the text channel for reference
                await ctx.channel.send(f"🗣️ **RAVEN:** {response.text}")

            os.unlink(audio_path)

    async def start(self):
        await self.bot.start(self.token)
```

---

## Connector 3: WhatsApp Bot

WhatsApp requires a JavaScript bridge because the best free library (Baileys)
is Node.js-only. We run a small Express server that bridges to Python.

```
┌──────────────────┐    HTTP     ┌──────────────────┐
│  RAVEN Python    │◄──────────▶│  Baileys Bridge   │
│  (main process)  │            │  (Node.js)        │
│                  │            │                    │
│  Posts incoming   │            │  - Connects to    │
│  messages to     │            │    WhatsApp Web   │
│  brain           │            │  - Receives msgs  │
│                  │            │  - Sends replies  │
│  Sends replies   │            │  - Voice notes    │
│  back via HTTP   │            │  - Images         │
└──────────────────┘            └──────────────────┘
```

### Baileys Bridge (Node.js)

```javascript
// whatsapp-bridge/index.js
const { makeWASocket, useMultiFileAuthState, downloadMediaMessage } = require('@whiskeysockets/baileys');
const express = require('express');
const fs = require('fs');

const app = express();
app.use(express.json());

let sock;
const RAVEN_URL = process.env.RAVEN_URL || 'http://localhost:8080';

async function startWhatsApp() {
    const { state, saveCreds } = await useMultiFileAuthState('auth_info');

    sock = makeWASocket({
        auth: state,
        printQRInTerminal: true,  // Scan QR code to link
    });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('messages.upsert', async ({ messages }) => {
        for (const msg of messages) {
            if (msg.key.fromMe) continue;

            const jid = msg.key.remoteJid;
            const sender = jid.split('@')[0];

            let type = 'text';
            let text = msg.message?.conversation ||
                       msg.message?.extendedTextMessage?.text || '';
            let audioPath = null;
            let imagePath = null;

            // Handle voice notes
            if (msg.message?.audioMessage) {
                type = 'voice';
                const buffer = await downloadMediaMessage(msg, 'buffer');
                audioPath = `/tmp/wa_voice_${Date.now()}.ogg`;
                fs.writeFileSync(audioPath, buffer);
            }

            // Handle images
            if (msg.message?.imageMessage) {
                type = 'image';
                const buffer = await downloadMediaMessage(msg, 'buffer');
                imagePath = `/tmp/wa_image_${Date.now()}.jpg`;
                fs.writeFileSync(imagePath, buffer);
                text = msg.message.imageMessage.caption || '';
            }

            // Forward to RAVEN Python server
            try {
                const response = await fetch(`${RAVEN_URL}/api/incoming`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        source: 'whatsapp',
                        sender: sender,
                        jid: jid,
                        type: type,
                        text: text,
                        audio_path: audioPath,
                        image_path: imagePath,
                    }),
                });

                const result = await response.json();

                // Send reply
                if (result.voice_audio_path) {
                    await sock.sendMessage(jid, {
                        audio: fs.readFileSync(result.voice_audio_path),
                        mimetype: 'audio/ogg; codecs=opus',
                        ptt: true,  // Play as voice note, not audio file
                    });
                }

                if (result.text) {
                    await sock.sendMessage(jid, { text: result.text });
                }

            } catch (err) {
                console.error('Error forwarding to RAVEN:', err);
                await sock.sendMessage(jid, {
                    text: "Sorry, I'm having trouble right now. Try again in a moment."
                });
            }
        }
    });
}

// API endpoint for RAVEN to send proactive messages (alerts, reminders)
app.post('/send', async (req, res) => {
    const { jid, text, audio_path } = req.body;
    try {
        if (audio_path) {
            await sock.sendMessage(jid, {
                audio: fs.readFileSync(audio_path),
                mimetype: 'audio/ogg; codecs=opus',
                ptt: true,
            });
        }
        if (text) {
            await sock.sendMessage(jid, { text });
        }
        res.json({ success: true });
    } catch (err) {
        res.json({ success: false, error: err.message });
    }
});

app.listen(3001, () => console.log('WhatsApp bridge on :3001'));
startWhatsApp();
```

---

## Connector 4: Voice I/O (Microphone / Speaker)

For devices directly connected to the RAVEN server -- a Raspberry Pi with a mic
and speaker, a desktop with a USB microphone, or any computer running the bot.

This connector provides **always-on voice** with wake-word detection.

```python
import pyaudio
import numpy as np
import asyncio
from collections import deque

class VoiceIOConnector:
    """Direct microphone/speaker connector for local voice interaction.

    Listens continuously. Detects wake word ("Hey RAVEN") or uses
    push-to-talk mode. Speaks responses through local speakers.
    """

    def __init__(self, brain: RavenBrain, mic_device: str = "default",
                 speaker_device: str = "default"):
        self.brain = brain
        self.mic_device = mic_device
        self.speaker_device = speaker_device

        # Audio config
        self.sample_rate = 16000
        self.chunk_size = 512  # 32ms chunks
        self.channels = 1

        # VAD
        self.vad = SileroVAD(threshold=0.5)

        # Wake word detector (uses a small keyword-spotting model)
        self.wake_word_detector = WakeWordDetector(wake_word="raven")

        # State
        self.is_listening = False       # Actively recording user speech
        self.is_speaking = False        # Playing TTS audio
        self.audio_buffer: deque = deque(maxlen=500)  # ~16s of audio

    async def start(self):
        """Start the voice I/O loop."""
        # Open mic stream
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=pyaudio.paInt16,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size,
            input_device_index=self._find_device(pa, self.mic_device),
        )

        logger.info(f"Voice I/O started. Say 'Hey RAVEN' to begin.")

        try:
            while True:
                # Read audio chunk
                raw = stream.read(self.chunk_size, exception_on_overflow=False)
                pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

                if self.is_speaking:
                    # Don't listen while speaking (simple echo prevention)
                    continue

                if not self.is_listening:
                    # Check for wake word
                    if self.wake_word_detector.detect(pcm):
                        logger.info("Wake word detected!")
                        self.is_listening = True
                        self.audio_buffer.clear()
                        # Play a short acknowledgment sound
                        await self._play_ack_sound()
                        continue

                else:
                    # We're actively listening -- accumulate audio
                    self.audio_buffer.append(raw)

                    # Check VAD for end of speech
                    vad_result = self.vad.process_chunk(pcm)

                    if vad_result and vad_result.type == "speech_end":
                        # User finished speaking
                        self.is_listening = False

                        # Combine audio buffer into a single WAV
                        audio_data = b''.join(self.audio_buffer)
                        audio_path = await self._save_temp_wav(audio_data)

                        # Transcribe
                        text = await self.brain.voice_engine.transcribe(audio_path)
                        logger.info(f"Heard: {text}")

                        if text and len(text.strip()) > 1:
                            # Send to brain
                            message = IncomingMessage(
                                id=f"voice-{time.time()}",
                                source="voice",
                                user_id="local-user",
                                platform_user_id="local",
                                input_type="voice",
                                text=text,
                                is_voice=True,
                                reply_context=ReplyContext(
                                    platform="voice",
                                    chat_id="local",
                                    supports_markdown=False,
                                    supports_voice_reply=True,
                                    supports_images=False,
                                    supports_buttons=False,
                                ),
                                timestamp=datetime.utcnow(),
                            )

                            response = await self.brain.handle_message(message)

                            # Speak the response
                            if response.text:
                                await self._speak(response.text)

                        self.audio_buffer.clear()
                        os.unlink(audio_path)

                await asyncio.sleep(0.001)  # Yield to event loop

        finally:
            stream.close()
            pa.terminate()

    async def _speak(self, text: str):
        """Synthesize and play speech through speakers."""
        self.is_speaking = True
        try:
            audio_path = await self.brain.voice_engine.synthesize(
                text, output_format="wav"
            )
            await self._play_audio(audio_path)
            os.unlink(audio_path)
        finally:
            self.is_speaking = False

    async def _play_audio(self, audio_path: str):
        """Play a WAV file through the speaker."""
        # Use sounddevice or PyAudio for playback
        import sounddevice as sd
        import soundfile as sf

        data, samplerate = sf.read(audio_path)
        sd.play(data, samplerate, device=self.speaker_device)
        sd.wait()
```

### Wake Word Detection

```python
import openwakeword
from openwakeword.model import Model as OWWModel

class WakeWordDetector:
    """Detect 'Hey RAVEN' using openWakeWord (open-source).

    openWakeWord uses small neural networks (~1MB) trained for
    specific wake words. We can train a custom "Hey RAVEN" model
    using their training pipeline with ~50 positive examples.
    """

    def __init__(self, wake_word: str = "raven"):
        # Use a pre-trained model or custom-trained
        self.model = OWWModel(
            wakeword_models=["hey_raven"],  # Custom trained
            inference_framework="onnx"
        )
        self.threshold = 0.7

    def detect(self, audio_chunk: np.ndarray) -> bool:
        """Process an audio chunk and return True if wake word detected."""
        prediction = self.model.predict(audio_chunk)
        scores = prediction.get("hey_raven", 0)
        if isinstance(scores, (list, np.ndarray)):
            return any(s > self.threshold for s in scores)
        return scores > self.threshold
```

---

## Connector 5: Web Dashboard + API

A simple FastAPI server that provides both a REST API (for custom integrations)
and a web-based chat interface.

```python
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="RAVEN API")

class WebAPIConnector:
    def __init__(self, brain: RavenBrain, port: int = 8080):
        self.brain = brain
        self.port = port

        # REST endpoint for incoming messages (used by WhatsApp bridge too)
        @app.post("/api/incoming")
        async def handle_incoming(payload: dict):
            message = self._parse_incoming(payload)
            response = await self.brain.handle_message(message)
            return {
                "text": response.text,
                "voice_audio_path": response.voice_audio_path,
            }

        # WebSocket for real-time chat (web dashboard)
        @app.websocket("/ws/chat")
        async def chat_ws(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    data = await websocket.receive_json()
                    message = IncomingMessage(
                        id=f"web-{time.time()}",
                        source="web",
                        user_id=data.get("user_id", "web-user"),
                        platform_user_id="web",
                        input_type="text",
                        text=data["text"],
                        reply_context=ReplyContext(
                            platform="web",
                            chat_id="web",
                            supports_markdown=True,
                            supports_voice_reply=False,
                            supports_images=True,
                            supports_buttons=True,
                        ),
                        timestamp=datetime.utcnow(),
                    )
                    response = await self.brain.handle_message(message)
                    await websocket.send_json({
                        "text": response.text,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
            except Exception:
                pass

        # Status endpoint
        @app.get("/api/status")
        async def status():
            return {
                "bot_name": "RAVEN",
                "uptime_seconds": self.brain.uptime_seconds,
                "active_connectors": self.brain.active_connectors,
                "total_messages_processed": self.brain.message_count,
                "llm_model": self.brain.llm_model_name,
                "sensors_online": self.brain.sensor_count,
            }

        # Device management
        @app.get("/api/devices")
        async def list_devices():
            return await self.brain.smart_home.list_devices()

        @app.post("/api/devices/{device_id}/action")
        async def device_action(device_id: str, action: dict):
            return await self.brain.smart_home.execute(
                device_id, action["action"], action.get("params", {})
            )

    async def start(self):
        import uvicorn
        config = uvicorn.Config(app, host="0.0.0.0", port=self.port)
        server = uvicorn.Server(config)
        await server.serve()
```

---

## Connector Summary

| Connector | Language | Library | Auth | Voice | Real-time |
|---|---|---|---|---|---|
| Telegram | Python | python-telegram-bot | Bot token | Voice notes (async) | Polling |
| Discord | Python | discord.py | Bot token | Voice channels (live) | Gateway WS |
| WhatsApp | Node.js bridge | Baileys | QR code scan | Voice notes (async) | WS to WA |
| Voice I/O | Python | PyAudio + sounddevice | Local only | Live mic/speaker | Continuous |
| Web / API | Python | FastAPI | JWT (optional) | No (text only) | WebSocket |

### Adding New Connectors

The architecture makes it easy to add new platforms. Any connector just needs to:
1. Receive messages from the platform
2. Convert to `IncomingMessage`
3. Call `brain.handle_message()`
4. Convert `OutgoingMessage` back to platform format
5. Send the response

Potential future connectors:
- **Slack** (slack-bolt for Python)
- **Matrix** (matrix-nio for Python)
- **Signal** (signal-cli bridge)
- **SMS** (Twilio API)
- **Alexa / Google Home** (skill/action SDK)
- **IRC** (irc3 for Python)
