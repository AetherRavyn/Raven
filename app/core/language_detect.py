"""Multi-Language Auto-Detect — detect language from text for voice and translation.

FRIDAY-style: automatically detects the user's language and
adapts voice synthesis and response generation accordingly.

Uses character frequency analysis and common word patterns —
no external API needed, works offline.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(slots=True)
class LanguageDetection:
    """Result of language detection."""
    language: str  # ISO 639-1 code (en, es, fr, de, etc.)
    confidence: float  # 0.0 to 1.0
    script: str  # Latin, Cyrillic, CJK, Arabic, etc.


# Language signatures based on common words and character patterns
_LANGUAGE_SIGNATURES: dict[str, dict[str, Any]] = {
    "en": {
        "common_words": {"the", "is", "are", "was", "have", "has", "will", "would", "could", "should", "about", "with", "this", "that", "from"},
        "patterns": [r"\b(?:the|and|is|in|to|of|a|that|it|for)\b"],
    },
    "es": {
        "common_words": {"el", "la", "los", "las", "es", "son", "está", "tiene", "hay", "para", "por", "con", "una", "como", "pero"},
        "patterns": [r"(?:á|é|í|ó|ú|ñ|¿|¡)"],
    },
    "fr": {
        "common_words": {"le", "la", "les", "est", "sont", "avoir", "être", "pour", "avec", "dans", "une", "des", "que", "qui", "mais"},
        "patterns": [r"(?:è|ê|ë|à|â|ù|û|ü|ô|î|ï|ç|œ|æ)"],
    },
    "de": {
        "common_words": {"der", "die", "das", "ist", "sind", "hat", "haben", "für", "mit", "auf", "eine", "einem", "und", "nicht", "sich"},
        "patterns": [r"(?:ä|ö|ü|ß)"],
    },
    "pt": {
        "common_words": {"o", "a", "os", "as", "é", "são", "tem", "para", "com", "uma", "por", "como", "mas", "foi", "está"},
        "patterns": [r"(?:ã|õ|ç)"],
    },
    "it": {
        "common_words": {"il", "la", "le", "di", "che", "è", "sono", "per", "con", "una", "nel", "gli", "della", "questo", "come"},
        "patterns": [r"(?:à|è|é|ì|ò|ù)"],
    },
    "ru": {
        "common_words": {"и", "в", "не", "на", "я", "что", "это", "как", "но", "он", "она", "мы", "вы", "они", "быть"},
        "patterns": [r"[\u0400-\u04FF]"],
    },
    "ja": {
        "common_words": {"の", "に", "は", "を", "た", "が", "で", "て", "と", "し", "れ", "さ", "ある", "いる", "する"},
        "patterns": [r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]"],
    },
    "zh": {
        "common_words": {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也"},
        "patterns": [r"[\u4E00-\u9FFF]"],
    },
    "ko": {
        "common_words": {"이", "그", "것", "은", "는", "에", "를", "이다", "으로", "하고", "에서", "에게", "부터", "까지", "만"},
        "patterns": [r"[\uAC00-\uD7AF\u1100-\u11FF]"],
    },
    "ar": {
        "common_words": {"في", "من", "على", "إلى", "أن", "هذا", "هذه", "التي", "الذي", "كان", "ليس", "مع", "عن", "بعد", "قبل"},
        "patterns": [r"[\u0600-\u06FF]"],
    },
    "hi": {
        "common_words": {"है", "में", "के", "को", "से", "पर", "ने", "नहीं", "था", "यह", "वह", "और", "एक", "भी", "तो"},
        "patterns": [r"[\u0900-\u097F]"],
    },
    "tr": {
        "common_words": {"bir", "bu", "da", "de", "ve", "ile", "için", "var", "olan", "gibi", "daha", "kadar", "çok", "her", "bile"},
        "patterns": [r"(?:ç|ğ|ı|ö|ş|ü)"],
    },
    "nl": {
        "common_words": {"de", "het", "een", "van", "en", "in", "is", "dat", "op", "te", "met", "voor", "niet", "zijn", "maar"},
        "patterns": [r"(?:ij|é|è|ê|ë|ü|ï)"],
    },
    "pl": {
        "common_words": {"i", "w", "nie", "na", "to", "że", "się", "jest", "do", "co", "jak", "ale", "za", "od", "po"},
        "patterns": [r"(?:ą|ć|ę|ł|ń|ó|ś|ź|ż)"],
    },
}


def detect_language(text: str) -> LanguageDetection:
    """Detect the language of a text string.

    Uses character frequency analysis and common word matching.
    No external API needed — works offline.
    """
    if not text or len(text.strip()) < 3:
        return LanguageDetection(language="en", confidence=0.1, script="Latin")

    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))
    scores: dict[str, float] = {}

    for lang, sig in _LANGUAGE_SIGNATURES.items():
        score = 0.0

        # Common word matching
        common = sig["common_words"]
        matches = len(words & common)
        if matches >= 3:
            score += matches * 0.15

        # Pattern matching (character sets)
        for pattern in sig["patterns"]:
            if re.search(pattern, text):
                score += 0.3

        scores[lang] = score

    # Determine best match
    if not scores or max(scores.values()) == 0:
        return LanguageDetection(language="en", confidence=0.2, script="Latin")

    best_lang = max(scores, key=scores.get)
    best_score = scores[best_lang]

    # Normalize confidence
    confidence = min(best_score / 2.0, 1.0)

    # Detect script
    script = _detect_script(text)

    return LanguageDetection(
        language=best_lang,
        confidence=confidence,
        script=script,
    )


def _detect_script(text: str) -> str:
    """Detect the writing script of the text."""
    if re.search(r'[\u0400-\u04FF]', text):
        return "Cyrillic"
    if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', text):
        return "Japanese"
    if re.search(r'[\u4E00-\u9FFF]', text):
        return "Chinese"
    if re.search(r'[\uAC00-\uD7AF]', text):
        return "Korean"
    if re.search(r'[\u0600-\u06FF]', text):
        return "Arabic"
    if re.search(r'[\u0900-\u097F]', text):
        return "Devanagari"
    if re.search(r'[\u0E00-\u0E7F]', text):
        return "Thai"
    if re.search(r'[\u1000-\u109F]', text):
        return "Myanmar"
    return "Latin"


def get_language_name(code: str) -> str:
    """Get the full language name from ISO 639-1 code."""
    names = {
        "en": "English", "es": "Spanish", "fr": "French", "de": "German",
        "pt": "Portuguese", "it": "Italian", "ru": "Russian", "ja": "Japanese",
        "zh": "Chinese", "ko": "Korean", "ar": "Arabic", "hi": "Hindi",
        "tr": "Turkish", "nl": "Dutch", "pl": "Polish",
    }
    return names.get(code, code)
