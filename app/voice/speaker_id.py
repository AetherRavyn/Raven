# app/voice/speaker_id.py
"""Speaker Identification — voice biometrics for multi-user recognition.

Uses speech embeddings to identify who is speaking. Supports:
  - Enrollment: "Hey Jarvis, register my voice as <name>"
  - Runtime identification: compare voice embedding against enrolled users
  - Falls back to "local" user if no match or no enrollments

Backends (prioritized):
  1. resemblyzer — pretrained SpeakerEncoder (lightweight, easy)
  2. speechbrain — larger models, higher accuracy
  3. Fallback — always returns "local"

Storage: workspace/voice/speaker_profiles/
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import wave
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_PROFILES_DIR = Path("workspace/voice/speaker_profiles")
_SIMILARITY_THRESHOLD = 0.75  # cosine similarity threshold for positive match


class SpeakerProfile:
    """A single enrolled speaker with their voice embedding."""

    __slots__ = ("name", "user_id", "embedding", "enrollment_count")

    def __init__(
        self,
        name: str,
        user_id: str,
        embedding: np.ndarray,
        enrollment_count: int = 1,
    ) -> None:
        self.name = name
        self.user_id = user_id
        self.embedding = embedding
        self.enrollment_count = enrollment_count


class SpeakerIdentifier:
    """Identifies speakers by voice embedding comparison."""

    def __init__(self) -> None:
        self._profiles: Dict[str, SpeakerProfile] = {}
        self._encoder = None
        self._backend = "none"
        self._load_profiles()

    # ── Encoder Initialization ─────────────────────────────────────────

    def _ensure_encoder(self) -> bool:
        """Lazy-load the best available speaker embedding backend."""
        if self._encoder is not None:
            return True

        # Try resemblyzer first (lightweight)
        try:
            from resemblyzer import VoiceEncoder  # type: ignore

            self._encoder = VoiceEncoder("cpu")
            self._backend = "resemblyzer"
            logger.info("SpeakerID: using resemblyzer backend")
            return True
        except ImportError:
            pass

        # Try speechbrain
        try:
            from speechbrain.inference import EncoderClassifier  # type: ignore

            self._encoder = EncoderClassifier.from_hparams(
                source="speechbrain/spkrec-ecapa-voxceleb",
                run_opts={"device": "cpu"},
            )
            self._backend = "speechbrain"
            logger.info("SpeakerID: using speechbrain backend")
            return True
        except (ImportError, Exception) as exc:
            logger.debug("SpeakerID: speechbrain unavailable — %s", exc)

        logger.warning(
            "SpeakerID: no speaker encoder available. "
            "Install `resemblyzer` or `speechbrain` for speaker identification."
        )
        return False

    # ── Embedding Extraction ───────────────────────────────────────────

    def _extract_embedding(self, audio_path: str) -> Optional[np.ndarray]:
        """Extract a speaker embedding from an audio file."""
        if not self._ensure_encoder():
            return None

        try:
            if self._backend == "resemblyzer":
                from resemblyzer import preprocess_wav  # type: ignore

                wav = preprocess_wav(audio_path)
                embedding = self._encoder.embed_utterance(wav)
                return embedding

            elif self._backend == "speechbrain":
                import torchaudio  # type: ignore

                signal, fs = torchaudio.load(audio_path)
                embedding = self._encoder.encode_batch(signal)
                return embedding.squeeze().cpu().numpy()

        except Exception as exc:
            logger.error("SpeakerID: embedding extraction failed — %s", exc)
            return None

    def _extract_embedding_from_bytes(self, audio_bytes: bytes) -> Optional[np.ndarray]:
        """Extract embedding from raw PCM bytes (16-bit, 16kHz, mono)."""
        # Write to temp WAV
        try:
            fd, wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_bytes)

            embedding = self._extract_embedding(wav_path)
            return embedding
        except Exception as exc:
            logger.error("SpeakerID: failed to process audio bytes — %s", exc)
            return None
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    # ── Cosine Similarity ──────────────────────────────────────────────

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two embeddings."""
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))

    # ── Identification ─────────────────────────────────────────────────

    def identify(self, audio_path: str) -> Tuple[str, float]:
        """
        Identify the speaker from an audio file.

        Returns:
            (user_id, confidence) — "local" with 0.0 if no match found.
        """
        if not self._profiles:
            return "local", 0.0

        embedding = self._extract_embedding(audio_path)
        if embedding is None:
            return "local", 0.0

        best_match = "local"
        best_score = 0.0

        for profile in self._profiles.values():
            score = self._cosine_similarity(embedding, profile.embedding)
            if score > best_score:
                best_score = score
                best_match = profile.user_id

        if best_score >= _SIMILARITY_THRESHOLD:
            profile = self._profiles.get(best_match)
            name = profile.name if profile else best_match
            logger.info(
                "SpeakerID: identified %s (confidence=%.3f)",
                name,
                best_score,
            )
            return best_match, best_score
        else:
            logger.debug(
                "SpeakerID: no match above threshold (best=%.3f)", best_score
            )
            return "local", best_score

    def identify_from_bytes(self, audio_bytes: bytes) -> Tuple[str, float]:
        """Identify speaker from raw PCM bytes."""
        if not self._profiles:
            return "local", 0.0

        embedding = self._extract_embedding_from_bytes(audio_bytes)
        if embedding is None:
            return "local", 0.0

        best_match = "local"
        best_score = 0.0

        for profile in self._profiles.values():
            score = self._cosine_similarity(embedding, profile.embedding)
            if score > best_score:
                best_score = score
                best_match = profile.user_id

        if best_score >= _SIMILARITY_THRESHOLD:
            return best_match, best_score
        return "local", best_score

    # ── Enrollment ─────────────────────────────────────────────────────

    def enroll(self, name: str, user_id: str, audio_path: str) -> bool:
        """Enroll a new speaker or update an existing profile."""
        embedding = self._extract_embedding(audio_path)
        if embedding is None:
            logger.error("SpeakerID: enrollment failed — could not extract embedding")
            return False

        if user_id in self._profiles:
            # Averaging with existing embedding for better accuracy
            existing = self._profiles[user_id]
            count = existing.enrollment_count
            existing.embedding = (existing.embedding * count + embedding) / (count + 1)
            existing.enrollment_count = count + 1
            logger.info(
                "SpeakerID: updated enrollment for %s (samples: %d)",
                name,
                existing.enrollment_count,
            )
        else:
            self._profiles[user_id] = SpeakerProfile(
                name=name,
                user_id=user_id,
                embedding=embedding,
                enrollment_count=1,
            )
            logger.info("SpeakerID: enrolled new speaker %s as %s", name, user_id)

        self._save_profiles()
        return True

    # ── Persistence ────────────────────────────────────────────────────

    def _load_profiles(self) -> None:
        """Load speaker profiles from disk."""
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

        for profile_path in _PROFILES_DIR.glob("*.json"):
            try:
                with open(profile_path, "r") as f:
                    data = json.load(f)
                embedding_path = profile_path.with_suffix(".npy")
                if embedding_path.exists():
                    embedding = np.load(str(embedding_path))
                    self._profiles[data["user_id"]] = SpeakerProfile(
                        name=data["name"],
                        user_id=data["user_id"],
                        embedding=embedding,
                        enrollment_count=data.get("enrollment_count", 1),
                    )
                    logger.debug("SpeakerID: loaded profile for %s", data["name"])
            except Exception as exc:
                logger.warning("SpeakerID: failed to load profile %s — %s", profile_path, exc)

    def _save_profiles(self) -> None:
        """Save all speaker profiles to disk."""
        _PROFILES_DIR.mkdir(parents=True, exist_ok=True)

        for user_id, profile in self._profiles.items():
            try:
                meta_path = _PROFILES_DIR / f"{user_id}.json"
                embed_path = _PROFILES_DIR / f"{user_id}.npy"

                with open(meta_path, "w") as f:
                    json.dump(
                        {
                            "name": profile.name,
                            "user_id": profile.user_id,
                            "enrollment_count": profile.enrollment_count,
                        },
                        f,
                        indent=2,
                    )
                np.save(str(embed_path), profile.embedding)
            except Exception as exc:
                logger.error("SpeakerID: failed to save profile %s — %s", user_id, exc)

    def list_enrolled(self) -> List[Dict[str, str]]:
        """List all enrolled speakers."""
        return [
            {"name": p.name, "user_id": p.user_id, "samples": str(p.enrollment_count)}
            for p in self._profiles.values()
        ]


# ── Module singleton ───────────────────────────────────────────────────

_IDENTIFIER: SpeakerIdentifier | None = None


def get_speaker_identifier() -> SpeakerIdentifier:
    global _IDENTIFIER
    if _IDENTIFIER is None:
        _IDENTIFIER = SpeakerIdentifier()
    return _IDENTIFIER
