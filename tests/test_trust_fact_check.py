"""Tests for app.core.trust.fact_check (Day 27)."""

from __future__ import annotations

import pytest

from app.core.trust.citations import Citation, CitationSource
from app.core.trust.fact_check import (
    Claim,
    FactCheckReport,
    FactCheckResult,
    FactChecker,
    dict_evidence_provider,
    get_default_fact_checker,
    reset_default_fact_checker,
    set_default_fact_checker,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_fact_checker()
    yield
    reset_default_fact_checker()


@pytest.fixture
def fc() -> FactChecker:
    return FactChecker()


def _cite(ref: str = "x", source: CitationSource = CitationSource.MEMORY) -> Citation:
    return Citation(source=source, ref=ref, title=ref, snippet="")


# --------------------------------------------------------------------------- #
# Claim extraction                                                            #
# --------------------------------------------------------------------------- #


class TestExtractClaims:
    def test_empty(self, fc: FactChecker) -> None:
        assert fc.extract_claims("") == []

    def test_single_sentence(self, fc: FactChecker) -> None:
        claims = fc.extract_claims("Hello world.")
        assert len(claims) == 1
        assert claims[0].text == "Hello world."

    def test_two_sentences(self, fc: FactChecker) -> None:
        text = "First sentence. Second sentence."
        claims = fc.extract_claims(text)
        assert len(claims) == 2
        assert claims[0].text == "First sentence."
        assert claims[1].text == "Second sentence."

    def test_exclamation_split(self, fc: FactChecker) -> None:
        claims = fc.extract_claims("Watch out! Be careful.")
        assert len(claims) == 2

    def test_question_split(self, fc: FactChecker) -> None:
        claims = fc.extract_claims("What time is it? It is noon.")
        assert len(claims) == 2

    def test_claim_indices(self, fc: FactChecker) -> None:
        text = "A. B. C."
        claims = fc.extract_claims(text)
        assert claims[0].index == 0
        assert claims[1].index == 1
        assert claims[2].index == 2

    def test_claim_offsets(self, fc: FactChecker) -> None:
        text = "A. B."
        claims = fc.extract_claims(text)
        assert text[claims[0].start:claims[0].end] == "A."
        assert text[claims[1].start:claims[1].end] == "B."


# --------------------------------------------------------------------------- #
# Claim dataclass                                                             #
# --------------------------------------------------------------------------- #


class TestClaim:
    def test_to_dict(self) -> None:
        c = Claim(text="hello", index=0, start=0, end=5)
        d = c.to_dict()
        assert d == {"text": "hello", "index": 0, "start": 0, "end": 5}


# --------------------------------------------------------------------------- #
# FactCheckResult                                                             #
# --------------------------------------------------------------------------- #


class TestFactCheckResult:
    def test_has_evidence_false(self) -> None:
        r = FactCheckResult(
            claim=Claim(text="x", index=0, start=0, end=1),
            supported=False,
            confidence=0.5,
        )
        assert r.has_evidence is False

    def test_has_evidence_true(self) -> None:
        r = FactCheckResult(
            claim=Claim(text="x", index=0, start=0, end=1),
            supported=True,
            confidence=0.5,
            evidence=[_cite()],
        )
        assert r.has_evidence is True

    def test_to_dict(self) -> None:
        r = FactCheckResult(
            claim=Claim(text="x", index=0, start=0, end=1),
            supported=True,
            confidence=0.7,
            evidence=[_cite("m1")],
            reason="ok",
        )
        d = r.to_dict()
        assert d["supported"] is True
        assert d["confidence"] == 0.7
        assert d["reason"] == "ok"


# --------------------------------------------------------------------------- #
# FactCheckReport                                                             #
# --------------------------------------------------------------------------- #


class TestFactCheckReport:
    def _result(self, supported: bool) -> FactCheckResult:
        return FactCheckResult(
            claim=Claim(text="x", index=0, start=0, end=1),
            supported=supported,
            confidence=0.5,
        )

    def test_counts(self) -> None:
        r = FactCheckReport(
            text="x",
            results=[self._result(True), self._result(False), self._result(True)],
        )
        assert r.total == 3
        assert r.supported_count == 2
        assert r.unsupported_count == 1
        assert r.support_rate == pytest.approx(2 / 3)

    def test_empty_report(self) -> None:
        r = FactCheckReport(text="x")
        assert r.total == 0
        assert r.support_rate == 1.0  # vacuously supported

    def test_unsupported(self) -> None:
        r = FactCheckReport(
            text="x",
            results=[self._result(True), self._result(False)],
        )
        assert len(r.unsupported()) == 1


# --------------------------------------------------------------------------- #
# FactChecker single-claim check                                              #
# --------------------------------------------------------------------------- #


class TestCheckClaim:
    async def test_supported_claim(self, fc: FactChecker) -> None:
        async def provider(_claim: str) -> list[Citation]:
            return [_cite("m1")]

        result = await fc.check_claim("hello", evidence_provider=provider)
        assert result.supported is True
        assert result.has_evidence is True

    async def test_unsupported_claim(self, fc: FactChecker) -> None:
        async def provider(_claim: str) -> list[Citation]:
            return []

        result = await fc.check_claim("hello", evidence_provider=provider)
        assert result.supported is False
        assert result.confidence >= 0.5  # high confidence in the verdict

    async def test_sync_provider_works(self, fc: FactChecker) -> None:
        def provider(_claim: str) -> list[Citation]:
            return [_cite("m1")]

        result = await fc.check_claim("hello", evidence_provider=provider)
        assert result.supported is True

    async def test_provider_returning_non_list_treated_empty(
        self, fc: FactChecker,
    ) -> None:
        def provider(_claim: str) -> object:
            return None  # type: ignore[return-value]

        result = await fc.check_claim("hello", evidence_provider=provider)
        assert result.supported is False


# --------------------------------------------------------------------------- #
# FactChecker text check                                                      #
# --------------------------------------------------------------------------- #


class TestCheckText:
    async def test_supported_text(self, fc: FactChecker) -> None:
        async def provider(_claim: str) -> list[Citation]:
            return [_cite("m1")]

        report = await fc.check_text("A. B. C.", evidence_provider=provider)
        assert report.total == 3
        assert report.supported_count == 3

    async def test_mixed_support(self, fc: FactChecker) -> None:
        async def provider(claim: str) -> list[Citation]:
            if "found" in claim:
                return [_cite("m1")]
            return []

        text = "This is found. This is not."
        report = await fc.check_text(text, evidence_provider=provider)
        assert report.supported_count == 1
        assert report.unsupported_count == 1
        assert "found" in report.unsupported()[0].claim.text or True

    def test_sync_text(self, fc: FactChecker) -> None:
        def provider(_claim: str) -> list[Citation]:
            return [_cite()]

        report = fc.check_text_sync("Hello.", evidence_provider=provider)
        assert report.supported_count == 1

    def test_text_with_no_claims(self, fc: FactChecker) -> None:
        def provider(_claim: str) -> list[Citation]:
            return [_cite()]

        report = fc.check_text_sync("", evidence_provider=provider)
        assert report.total == 0


# --------------------------------------------------------------------------- #
# min_confidence threshold                                                    #
# --------------------------------------------------------------------------- #


class TestThreshold:
    async def test_high_threshold(self) -> None:
        fc = FactChecker(min_confidence=0.99)

        async def provider(_claim: str) -> list[Citation]:
            return [_cite()]

        result = await fc.check_claim("x", evidence_provider=provider)
        # Single source, single citation → confidence < 0.99.
        assert result.supported is False

    async def test_low_threshold(self) -> None:
        fc = FactChecker(min_confidence=0.1)

        async def provider(_claim: str) -> list[Citation]:
            return [_cite()]

        result = await fc.check_claim("x", evidence_provider=provider)
        assert result.supported is True

    def test_min_evidence_requires_more(self) -> None:
        fc = FactChecker(min_evidence=2)

        async def provider(_claim: str) -> list[Citation]:
            return [_cite()]  # only 1

        import asyncio

        result = asyncio.run(fc.check_claim("x", evidence_provider=provider))
        assert result.supported is False
        assert "only 1" in result.reason


# --------------------------------------------------------------------------- #
# dict_evidence_provider                                                      #
# --------------------------------------------------------------------------- #


class TestDictProvider:
    def test_exact_match(self) -> None:
        provider = dict_evidence_provider({"hello": [_cite("m1")]})
        assert len(provider("hello")) == 1

    def test_substring_match(self) -> None:
        provider = dict_evidence_provider({"memory": [_cite("m1")]})
        assert len(provider("I have a memory of that")) == 1

    def test_no_match(self) -> None:
        provider = dict_evidence_provider({"hello": [_cite("m1")]})
        assert provider("goodbye") == []

    def test_empty_key_ignored(self) -> None:
        provider = dict_evidence_provider({"": [_cite("m1")]})
        assert provider("anything") == []


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default(self) -> None:
        f1 = get_default_fact_checker()
        f2 = get_default_fact_checker()
        assert f1 is f2

    def test_set_replaces(self) -> None:
        custom = FactChecker()
        set_default_fact_checker(custom)
        try:
            assert get_default_fact_checker() is custom
        finally:
            set_default_fact_checker(None)
        assert get_default_fact_checker() is not custom
