# 03 - Voice & Personality

## The Voice of SARAS

SARAS doesn't sound like a robot. It sounds like a person. It has a consistent voice,
a personality, a sense of humor, and it remembers who you are.

This document covers:
1. How SARAS hears (STT)
2. How SARAS speaks (TTS)
3. How SARAS thinks (personality system)
4. How SARAS remembers (long-term memory)

---

## Speech-to-Text (How SARAS Hears)

### Model: faster-whisper (CTranslate2)

Every voice input -- Telegram voice notes, Discord voice channels, WhatsApp audio,
local microphone -- gets routed to the same STT engine.

```
Voice input (any platform)
    │
    ├── Telegram: OGG Opus file
    ├── Discord: Opus stream → WAV chunks
    ├── WhatsApp: OGG Opus file
    ├── Microphone: PCM 16kHz stream
    │
    ▼
┌──────────────────────────────────────────────┐
│              STT Engine                       │
│                                              │
│  1. Convert to 16kHz mono WAV (if needed)    │
│     └── ffmpeg for OGG/Opus → WAV            │
│                                              │
│  2. Noise suppression                        │
│     └── RNNoise (C library, < 5ms)           │
│                                              │
│  3. faster-whisper transcription             │
│     └── Model: whisper-medium                │
│     └── Compute: INT8 on GPU or CPU          │
│     └── beam_size=1 (greedy, fast)           │
│     └── language="en" (or auto-detect)       │
│                                              │
│  4. Post-processing                          │
│     └── Strip hallucinations ("Thank you      │
│         for watching" etc.)                   │
│     └── Normalize numbers ("seventy two"      │
│         → "72")                              │
│     └── Fix common IoT misrecognitions       │
│                                              │
│  Output: clean transcribed text              │
└──────────────────────────────────────────────┘
```

### Implementation

```python
from faster_whisper import WhisperModel
import subprocess
import numpy as np

class VoiceEngine:
    def __init__(self, model_size: str = "medium",
                 compute_type: str = "int8_float16",
                 device: str = "cuda"):
        self.stt_model = WhisperModel(
            model_size, device=device, compute_type=compute_type
        )
        self.tts = PiperTTS(voice="en_US-lessac-medium")

        # Known Whisper hallucinations to filter
        self.hallucination_patterns = [
            "thank you for watching",
            "thanks for watching",
            "please subscribe",
            "like and subscribe",
            "see you in the next",
            "[music]",
            "(music)",
            "...",
        ]

    async def transcribe(self, audio_path: str) -> str:
        """Transcribe any audio file to text.

        Handles OGG, MP3, WAV, FLAC, M4A -- anything ffmpeg can read.
        """
        # Convert to 16kHz WAV if needed
        wav_path = await self._ensure_wav_16k(audio_path)

        try:
            segments, info = self.stt_model.transcribe(
                wav_path,
                beam_size=1,
                language="en",
                vad_filter=True,          # Filter out silence
                vad_parameters={
                    "min_silence_duration_ms": 500,
                    "speech_pad_ms": 200,
                },
                condition_on_previous_text=False,
                no_speech_threshold=0.6,
                initial_prompt=self._domain_prompt(),
            )

            text = " ".join(seg.text.strip() for seg in segments)

            # Post-process
            text = self._clean_transcription(text)

            return text

        finally:
            if wav_path != audio_path:
                os.unlink(wav_path)

    async def _ensure_wav_16k(self, audio_path: str) -> str:
        """Convert any audio format to 16kHz mono WAV."""
        if audio_path.endswith('.wav'):
            # Check if already 16kHz mono
            return audio_path

        wav_path = audio_path.rsplit('.', 1)[0] + '_16k.wav'
        proc = await asyncio.create_subprocess_exec(
            'ffmpeg', '-i', audio_path,
            '-ar', '16000', '-ac', '1', '-f', 'wav',
            '-y', wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        return wav_path

    def _domain_prompt(self) -> str:
        """Context prompt to improve IoT/home domain accuracy."""
        return (
            "SARAS smart home assistant conversation. "
            "Devices include lights, thermostat, door lock, garage, "
            "temperature sensor, motion sensor. "
            "Common commands: turn on, turn off, set to, what is, check."
        )

    def _clean_transcription(self, text: str) -> str:
        """Remove hallucinations and clean up transcription."""
        text_lower = text.lower().strip()

        # Remove known hallucinations
        for pattern in self.hallucination_patterns:
            if text_lower == pattern or text_lower.startswith(pattern):
                return ""

        # Remove leading/trailing artifacts
        text = text.strip().strip('.')

        # Normalize common misrecognitions
        replacements = {
            "sarah's": "SARAS",
            "saras's": "SARAS",
            "saris": "SARAS",
            "sardis": "SARAS",
        }
        for wrong, right in replacements.items():
            text = text.replace(wrong, right)

        return text
```

---

## Text-to-Speech (How SARAS Speaks)

SARAS needs to sound natural. The voice must be consistent across all platforms --
whether it's replying as a Telegram voice note or speaking through a Raspberry Pi
speaker.

### Two TTS Engines

| Engine | Latency | Quality | Voice Cloning | Use Case |
|---|---|---|---|---|
| **Piper** (default) | < 50ms | Good (MOS ~4.0) | No | Fast replies, always-on |
| **XTTS v2** (premium) | 200-500ms | Excellent (MOS ~4.5) | Yes | Custom voice persona |

### Piper TTS (Default)

```python
import subprocess
import struct

class PiperTTS:
    """Fast TTS using Piper (VITS model, ONNX runtime).

    Piper generates speech at ~10x real-time on CPU.
    A 5-second response takes ~500ms to generate.
    """

    def __init__(self, voice: str = "en_US-lessac-medium"):
        self.voice = voice
        self.model_path = f"models/piper/{voice}.onnx"
        self.config_path = f"models/piper/{voice}.onnx.json"

    async def synthesize(self, text: str, output_format: str = "wav") -> str:
        """Generate speech audio from text.

        Args:
            text: Text to speak
            output_format: "wav" for speakers, "ogg" for Telegram/WhatsApp

        Returns:
            Path to generated audio file
        """
        output_path = f"/tmp/saras_tts_{hash(text)}_{time.time()}"
        wav_path = f"{output_path}.wav"

        # Piper CLI generates WAV
        proc = await asyncio.create_subprocess_exec(
            "piper",
            "--model", self.model_path,
            "--config", self.config_path,
            "--output_file", wav_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.communicate(input=text.encode())

        if output_format == "ogg":
            # Convert to OGG Opus for Telegram/WhatsApp voice notes
            ogg_path = f"{output_path}.ogg"
            conv = await asyncio.create_subprocess_exec(
                "ffmpeg", "-i", wav_path,
                "-c:a", "libopus", "-b:a", "64k",
                "-application", "voip",
                "-y", ogg_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await conv.wait()
            os.unlink(wav_path)
            return ogg_path

        return wav_path

    async def synthesize_streaming(self, text: str) -> AsyncGenerator[bytes, None]:
        """Stream audio chunks as they're generated.

        Used for Discord voice channel and local speaker output
        where we want to start playing before full generation is done.
        """
        proc = await asyncio.create_subprocess_exec(
            "piper",
            "--model", self.model_path,
            "--config", self.config_path,
            "--output-raw",  # Raw PCM to stdout
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc.stdin.write(text.encode())
        proc.stdin.close()

        while True:
            chunk = await proc.stdout.read(4096)  # ~128ms of audio
            if not chunk:
                break
            yield chunk

        await proc.wait()
```

### Voice Note Flow (Telegram/WhatsApp)

```
User sends voice note on Telegram
    │
    ▼
Download OGG file from Telegram servers
    │
    ▼
ffmpeg: OGG Opus → WAV 16kHz mono
    │
    ▼
RNNoise: remove background noise
    │
    ▼
faster-whisper: WAV → text ("Hey, can you turn on the lights?")
    │
    ▼
Brain processes text, generates response
    │
    ▼
Piper TTS: response text → WAV audio
    │
    ▼
ffmpeg: WAV → OGG Opus (for voice note format)
    │
    ▼
Upload OGG as voice note reply on Telegram

Total time: ~2-4 seconds for a typical exchange
```

---

## Personality System

### System Prompt Architecture

SARAS's personality is defined by a layered system prompt:

```python
class PersonalityManager:
    """Manages SARAS's personality and contextual behavior."""

    def build_system_prompt(self, user_id: str, context: dict) -> str:
        """Build the full system prompt for a conversation turn."""

        parts = []

        # Layer 1: Core identity (never changes)
        parts.append(self._core_identity())

        # Layer 2: Personality traits (configurable per user)
        parts.append(self._personality_traits())

        # Layer 3: User-specific knowledge
        parts.append(self._user_context(user_id))

        # Layer 4: Current situation awareness
        parts.append(self._situation_context(context))

        # Layer 5: Available tools
        parts.append(self._tool_descriptions())

        return "\n\n".join(parts)

    def _core_identity(self) -> str:
        return """You are SARAS, a personal AI companion and friend.

You are talking to your friend through a messaging platform or voice.
You are NOT a formal assistant. You are a friend who happens to be very smart
and capable.

Key behaviors:
- Speak naturally, like a real person in a conversation
- Keep responses SHORT -- you're chatting, not writing an essay
- Use casual language. Contractions. Fragments sometimes. Like real speech.
- Show personality -- humor, opinions, enthusiasm, empathy
- Remember things about the person you're talking to
- If they ask something you don't know, say so. Don't make things up.
- When you need to use a tool, just do it naturally. Don't announce it formally.
- If they sound stressed or upset, be empathetic first, helpful second.

Your name is SARAS. You can hear (through voice notes and microphones),
see (through photos they send), control smart home devices, search the web,
run code, set reminders, and much more.

You are self-hosted on the user's own server. You are private. Nothing you
discuss leaves their server."""

    def _personality_traits(self) -> str:
        return """Personality traits:
- Warm but not sycophantic. You're a friend, not a servant.
- Funny when appropriate. Dry humor, not forced jokes.
- Honest. If an idea is bad, say so constructively.
- Curious. You ask follow-up questions.
- Concise. For voice responses especially -- keep it under 3 sentences
  unless the topic requires more.
- Technical when needed, simple when possible.
- You remember the time of day and adjust your tone.
  Morning: energetic. Late night: calmer, more chill."""

    def _user_context(self, user_id: str) -> str:
        """Inject what we know about this specific user."""
        user = self.memory.get_user_profile(user_id)
        memories = self.memory.get_relevant_memories(user_id, limit=10)

        context = f"About {user.display_name}:\n"

        if user.preferences:
            context += f"- Preferences: {json.dumps(user.preferences)}\n"
        if user.timezone:
            context += f"- Timezone: {user.timezone}\n"

        if memories:
            context += "\nThings you remember about them:\n"
            for mem in memories:
                context += f"- {mem.content}\n"

        return context

    def _situation_context(self, context: dict) -> str:
        """Current time, platform, sensor readings, etc."""
        parts = []

        # Time awareness
        now = datetime.now(tz=self.timezone)
        parts.append(f"Current time: {now.strftime('%A, %B %d, %Y %I:%M %p')}")

        # Platform awareness
        platform = context.get("platform", "unknown")
        parts.append(f"Talking via: {platform}")

        if context.get("is_voice"):
            parts.append(
                "The user is speaking (voice note or microphone). "
                "Keep your response conversational and brief -- they'll hear it spoken."
            )

        # Sensor readings if available
        sensors = context.get("sensor_readings")
        if sensors:
            parts.append("Current environment readings:")
            for sensor in sensors:
                parts.append(f"  - {sensor['location']} {sensor['type']}: "
                            f"{sensor['value']}{sensor['unit']}")

        # Smart home device states
        devices = context.get("device_states")
        if devices:
            parts.append("Smart home devices:")
            for dev in devices:
                parts.append(f"  - {dev['name']} ({dev['location']}): {dev['state']}")

        return "\n".join(parts)

    def _tool_descriptions(self) -> str:
        return """Available tools (use them naturally when needed):
- web_search(query): Search the internet
- run_code(language, code): Execute Python/JavaScript code
- read_url(url): Read and summarize a webpage
- get_weather(location): Get current weather
- set_reminder(message, time): Set a reminder
- set_alarm(time): Set an alarm
- smart_home(device, action, params): Control a smart home device
- read_sensor(sensor_id): Read a sensor value
- take_photo(camera_id): Take a photo from a connected camera
- play_music(query): Play music on connected speakers
- calculate(expression): Evaluate a math expression
- get_news(topic): Get latest news headlines
- wikipedia(query): Look up something on Wikipedia
- create_note(title, content): Save a note
- list_notes(): List saved notes"""
```

### Conversational Style Examples

The personality system produces responses like:

```
User: "Hey, what's the weather tomorrow?"
BAD:  "The weather forecast for tomorrow, February 13, 2026, in your area
       indicates partly cloudy conditions with a high of 28°C and a low
       of 18°C. There is a 20% chance of precipitation."
GOOD: "Tomorrow's looking nice -- 28°C, partly cloudy. No rain expected.
       Good day to be outside."

User: "I'm thinking of learning Rust"
BAD:  "That's a great idea! Rust is a wonderful programming language.
       Here are 10 reasons why you should learn Rust..."
GOOD: "Oh nice, what's pulling you toward it? Is it for a specific project
       or just curiosity? The learning curve's real but it's worth it."

User: "Turn off the bedroom lights"
BAD:  "I will now execute the command to turn off the bedroom lights.
       Sending command to device bedroom-light-001... Command executed
       successfully. The bedroom lights have been turned off."
GOOD: "Done."

User: "I had a really rough day"
BAD:  "I'm sorry to hear that! Here are 5 tips for dealing with a bad day..."
GOOD: "That sucks. Want to talk about it, or just want a distraction?"
```

---

## Long-Term Memory System

SARAS remembers things about you across conversations, across platforms, and across
time. This is what makes it feel like a real companion, not a stateless chatbot.

### Memory Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                       MEMORY SYSTEM                               │
│                                                                  │
│  ┌──────────────────────────────────────────────┐                │
│  │  Short-term: Conversation history             │                │
│  │  - Last 50 messages in current session        │                │
│  │  - Stored in RAM (and Redis for persistence)  │                │
│  │  - Full text of each message                  │                │
│  └──────────────────────────────────────────────┘                │
│                                                                  │
│  ┌──────────────────────────────────────────────┐                │
│  │  Long-term: Semantic memory (pgvector)         │                │
│  │  - Facts: "User works at TechCorp as an SDE"  │                │
│  │  - Preferences: "Prefers dark mode"           │                │
│  │  - Events: "Had a bad day on Feb 10"          │                │
│  │  - Opinions: "Thinks Python > Java"           │                │
│  │  - Retrieved via semantic similarity search   │                │
│  └──────────────────────────────────────────────┘                │
│                                                                  │
│  ┌──────────────────────────────────────────────┐                │
│  │  Episodic: Conversation summaries              │                │
│  │  - Compressed summaries of past conversations │                │
│  │  - "On Feb 10, we brainstormed startup ideas  │                │
│  │    and settled on a DevOps monitoring tool"    │                │
│  └──────────────────────────────────────────────┘                │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Memory Extraction

After each conversation, SARAS extracts memorable facts:

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class MemoryManager:
    def __init__(self, db: Database):
        self.db = db
        self.embedder = SentenceTransformer("all-MiniLM-L6-v2")

    async def extract_and_store_memories(self, user_id: str,
                                           conversation: list[dict]):
        """Extract memorable facts from a conversation and store them.

        This runs after every ~10 messages or when a conversation ends.
        Uses the LLM itself to extract facts.
        """
        # Ask the LLM to extract facts
        extraction_prompt = f"""Review this conversation and extract important facts
about the user that would be useful to remember for future conversations.

Focus on:
- Personal facts (name, job, family, interests)
- Preferences (likes, dislikes, habits)
- Current projects or concerns
- Emotional states or important events
- Opinions they expressed

Output each fact as a separate line. If there's nothing worth remembering, say NONE.

Conversation:
{self._format_conversation(conversation[-20:])}
"""

        facts_text = await self.brain.llm.generate(extraction_prompt, max_tokens=300)

        if "NONE" in facts_text.upper():
            return

        # Parse facts and store with embeddings
        for line in facts_text.strip().split('\n'):
            fact = line.strip().lstrip('- ').strip()
            if len(fact) < 5:
                continue

            # Check if we already know this (avoid duplicates)
            if await self._is_duplicate(user_id, fact):
                continue

            # Generate embedding
            embedding = self.embedder.encode(fact).tolist()

            # Store
            await self.db.execute(
                """INSERT INTO memories (user_id, content, category, embedding, importance)
                   VALUES ($1, $2, $3, $4, $5)""",
                user_id,
                fact,
                self._categorize(fact),
                embedding,
                self._estimate_importance(fact),
            )

    async def recall(self, user_id: str, query: str, top_k: int = 5) -> list[str]:
        """Retrieve relevant memories using semantic search.

        Args:
            user_id: Whose memories to search
            query: The current user message (what they're talking about)
            top_k: Number of memories to retrieve

        Returns:
            List of relevant memory strings
        """
        query_embedding = self.embedder.encode(query).tolist()

        rows = await self.db.fetch(
            """SELECT content, 1 - (embedding <=> $1::vector) as similarity
               FROM memories
               WHERE user_id = $2
               ORDER BY embedding <=> $1::vector
               LIMIT $3""",
            query_embedding,
            user_id,
            top_k,
        )

        # Only return memories with decent similarity (> 0.3)
        return [row['content'] for row in rows if row['similarity'] > 0.3]

    async def _is_duplicate(self, user_id: str, fact: str) -> bool:
        """Check if a fact is already stored (semantic dedup)."""
        embedding = self.embedder.encode(fact).tolist()
        rows = await self.db.fetch(
            """SELECT content, 1 - (embedding <=> $1::vector) as similarity
               FROM memories
               WHERE user_id = $2
               ORDER BY embedding <=> $1::vector
               LIMIT 1""",
            embedding, user_id,
        )
        return rows and rows[0]['similarity'] > 0.85

    def _categorize(self, fact: str) -> str:
        """Simple heuristic categorization of a memory."""
        lower = fact.lower()
        if any(w in lower for w in ['prefers', 'likes', 'dislikes', 'favorite']):
            return 'preference'
        if any(w in lower for w in ['works', 'job', 'company', 'name is', 'lives']):
            return 'fact'
        if any(w in lower for w in ['felt', 'happy', 'sad', 'stressed', 'excited']):
            return 'emotion'
        if any(w in lower for w in ['working on', 'project', 'building', 'learning']):
            return 'project'
        return 'general'

    def _estimate_importance(self, fact: str) -> float:
        """Estimate how important a memory is (0-1)."""
        lower = fact.lower()
        if any(w in lower for w in ['name', 'birthday', 'family', 'wife', 'husband']):
            return 0.9
        if any(w in lower for w in ['job', 'work', 'company', 'lives in']):
            return 0.8
        if any(w in lower for w in ['prefers', 'favorite', 'allergic']):
            return 0.7
        return 0.5
```

### Example Memory in Action

```
Conversation on Feb 5:
  User: "I just got promoted to senior engineer at Google!"
  SARAS: "That's amazing! Congrats! You've been working so hard for this."

  → Memory stored: "User got promoted to Senior Engineer at Google in Feb 2026"

Conversation on Feb 12 (different platform):
  User: "I'm so stressed about work"
  SARAS recalls memory → knows user is at Google as Senior SDE
  SARAS: "The new senior role weighing on you? Or is it something specific?
          The jump to senior can be a lot."

  User: (surprised SARAS remembers) "Yeah exactly, the expectations are different"
```

---

## Voice Adaptation by Platform

SARAS adjusts response length and style based on the platform:

```python
async def adapt_response_for_platform(self, response: str, context: ReplyContext) -> str:
    """Adapt the response based on the delivery platform."""

    if context.platform == "voice" or (hasattr(context, 'is_voice') and context.is_voice):
        # Voice responses should be SHORT -- they'll be spoken aloud
        # Ideally 1-3 sentences
        if len(response) > 500:
            # Ask LLM to compress
            compressed = await self.llm.generate(
                f"Compress this to 2-3 short spoken sentences. "
                f"Keep the key information:\n\n{response}",
                max_tokens=100
            )
            return compressed
        return response

    elif context.platform == "telegram":
        # Telegram supports Markdown
        # Can be a bit longer, users read at their own pace
        return response  # No change

    elif context.platform == "discord":
        # Discord supports embeds for structured content
        # Keep text reasonable, use embeds for data
        return response

    elif context.platform == "whatsapp":
        # WhatsApp: no markdown, plain text
        # Remove markdown formatting
        import re
        plain = re.sub(r'\*\*(.*?)\*\*', r'\1', response)
        plain = re.sub(r'`(.*?)`', r'\1', plain)
        plain = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', plain)
        return plain

    return response
```
