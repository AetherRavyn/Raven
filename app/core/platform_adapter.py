"""Platform Personality Adapter — adapts Raven's tone to each platform.

FRIDAY-style: same personality, different expression. Casual on
Telegram, professional on Slack, conversational in voice.

Reads platform-specific settings from SOUL.md and applies them
to the response before sending.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class PlatformProfile:
    """Platform-specific personality settings."""
    style: str = "casual"  # casual, professional, conversational
    max_length: int = 4096
    use_markdown: bool = True
    emoji_level: str = "moderate"  # none, minimal, moderate, high
    personality: str = "warm-and-precise"


# Default profiles for known platforms
_PROFILES: dict[str, PlatformProfile] = {
    "telegram": PlatformProfile(
        style="casual",
        max_length=4096,
        use_markdown=True,
        emoji_level="moderate",
    ),
    "discord": PlatformProfile(
        style="casual",
        max_length=2000,
        use_markdown=True,
        emoji_level="moderate",
    ),
    "slack": PlatformProfile(
        style="professional",
        max_length=4000,
        use_markdown=True,
        emoji_level="minimal",
    ),
    "voice": PlatformProfile(
        style="conversational",
        max_length=200,  # words, not chars
        use_markdown=False,
        emoji_level="none",
        personality="warm-and-precise",
    ),
    "web": PlatformProfile(
        style="casual",
        max_length=8000,
        use_markdown=True,
        emoji_level="moderate",
    ),
}


def get_platform_profile(platform: str) -> PlatformProfile:
    """Get the personality profile for a platform."""
    return _PROFILES.get(platform, PlatformProfile())


def adapt_response(response: str, platform: str) -> str:
    """Adapt a response for a specific platform.

    Applies:
    - Length truncation
    - Emoji adjustment
    - Style conversion
    """
    profile = get_platform_profile(platform)

    # Truncate to platform limit
    if len(response) > profile.max_length:
        response = response[: profile.max_length - 3] + "..."

    # Emoji adjustment
    if profile.emoji_level == "none":
        # Remove all emojis
        response = _remove_emojis(response)
    elif profile.emoji_level == "minimal":
        # Keep only essential emojis (🚨, ⚠️, ✅, ❌)
        response = _filter_essential_emojis(response)

    # Style conversion for voice
    if platform == "voice":
        response = _adapt_for_voice(response)

    # Style conversion for professional
    if profile.style == "professional":
        response = _adapt_for_professional(response)

    return response


def _remove_emojis(text: str) -> str:
    """Remove emoji characters from text."""
    # Unicode emoji ranges
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f926-\U0001f937"
        "\U00010000-\U0010ffff"
        "\u2640-\u2642"
        "\u2600-\u2B55"
        "\u200d"
        "\u23cf"
        "\u23e9"
        "\u231a"
        "\ufe0f"
        "\u3030"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _filter_essential_emojis(text: str) -> str:
    """Keep only essential emojis (alerts, status indicators)."""
    essential = {"🚨", "⚠️", "✅", "❌", "📊", "📈", "📉"}
    result = []
    for char in text:
        if char in essential or not ('\U0001F600' <= char <= '\U0010FFFF'):
            result.append(char)
    return "".join(result)


def _adapt_for_voice(text: str) -> str:
    """Adapt text for spoken delivery."""
    # Remove markdown formatting
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)  # italic
    text = re.sub(r"`(.+?)`", r"\1", text)  # code
    text = re.sub(r"```[\s\S]*?```", "(code block omitted)", text)  # code blocks
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)  # links → text only

    # Convert bullet points to spoken format
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)

    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    return text.strip()


def _adapt_for_professional(text: str) -> str:
    """Adapt text for professional context (Slack, email)."""
    # Reduce excessive exclamation marks
    text = re.sub(r"!{2,}", "!", text)

    # Keep markdown but ensure proper formatting
    return text
