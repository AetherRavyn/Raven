"""Tests for app.core.privacy.inspector (Day 28)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.privacy.consent import DataClass
from app.core.privacy.inspector import (
    DataItem,
    Inspector,
    InspectorQuery,
    get_default_inspector,
    reset_default_inspector,
    set_default_inspector,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    reset_default_inspector()
    yield
    reset_default_inspector()


@pytest.fixture
def insp() -> Inspector:
    return Inspector()


def _item(
    user_id: str = "u1",
    data_class: DataClass = DataClass.LOCATION,
    content: str = "hello",
    source: str = "memory",
    when: datetime | None = None,
    pinned: bool = False,
    item_id: str | None = None,
) -> DataItem:
    return DataItem(
        id=item_id or "id-" + content,
        user_id=user_id,
        data_class=data_class,
        content=content,
        source=source,
        timestamp=when or datetime.now(timezone.utc),
        pinned=pinned,
    )


# --------------------------------------------------------------------------- #
# DataItem                                                                    #
# --------------------------------------------------------------------------- #


class TestDataItem:
    def test_creation(self) -> None:
        i = DataItem(
            id="x",
            user_id="u1",
            data_class=DataClass.LOCATION,
            content="hi",
        )
        assert i.pinned is False
        assert i.metadata == {}

    def test_string_data_class_normalised(self) -> None:
        i = DataItem(
            id="x",
            user_id="u1",
            data_class="location",
            content="hi",
        )
        assert i.data_class is DataClass.LOCATION

    def test_to_dict(self) -> None:
        i = DataItem(
            id="x",
            user_id="u1",
            data_class=DataClass.LOCATION,
            content="hi",
        )
        d = i.to_dict()
        assert d["id"] == "x"
        assert d["data_class"] == "location"


# --------------------------------------------------------------------------- #
# InspectorQuery                                                              #
# --------------------------------------------------------------------------- #


class TestInspectorQuery:
    def test_user_filter(self) -> None:
        q = InspectorQuery(user_id="u1")
        assert q.matches(_item(user_id="u1")) is True
        assert q.matches(_item(user_id="u2")) is False

    def test_data_class_filter(self) -> None:
        q = InspectorQuery(user_id="u1", data_class=DataClass.LOCATION)
        assert q.matches(_item(data_class=DataClass.LOCATION)) is True
        assert q.matches(_item(data_class=DataClass.EMAIL)) is False

    def test_source_filter(self) -> None:
        q = InspectorQuery(user_id="u1", source="memory")
        assert q.matches(_item(source="memory")) is True
        assert q.matches(_item(source="web")) is False

    def test_contains_filter(self) -> None:
        q = InspectorQuery(user_id="u1", contains="secret")
        assert q.matches(_item(content="my secret note")) is True
        assert q.matches(_item(content="public note")) is False

    def test_pinned_only(self) -> None:
        q = InspectorQuery(user_id="u1", pinned_only=True)
        assert q.matches(_item(pinned=True)) is True
        assert q.matches(_item(pinned=False)) is False

    def test_time_window(self) -> None:
        now = datetime.now(timezone.utc)
        q = InspectorQuery(user_id="u1", since=now - timedelta(hours=1))
        assert q.matches(_item(when=now)) is True
        assert q.matches(_item(when=now - timedelta(hours=2))) is False


# --------------------------------------------------------------------------- #
# Inspector add / get / edit / delete                                        #
# --------------------------------------------------------------------------- #


class TestInspectorAdd:
    def test_add_returns_item(self, insp: Inspector) -> None:
        item = insp.add(
            user_id="u1",
            data_class=DataClass.LOCATION,
            content="hi",
        )
        assert item.id != ""
        assert item.user_id == "u1"

    def test_add_with_custom_id(self, insp: Inspector) -> None:
        item = insp.add(
            user_id="u1",
            data_class=DataClass.LOCATION,
            content="hi",
            item_id="custom_1",
        )
        assert item.id == "custom_1"

    def test_get(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="x")
        assert insp.get(item.id) is item

    def test_get_missing(self, insp: Inspector) -> None:
        assert insp.get("nope") is None

    def test_edit_content(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        insp.edit(item.id, content="b")
        assert insp.get(item.id).content == "b"

    def test_edit_metadata(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        insp.edit(item.id, metadata={"k": "v"})
        assert insp.get(item.id).metadata == {"k": "v"}

    def test_edit_missing(self, insp: Inspector) -> None:
        assert insp.edit("nope", content="x") is None

    def test_delete(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="x")
        assert insp.delete(item.id) is True
        assert insp.get(item.id) is None

    def test_delete_missing(self, insp: Inspector) -> None:
        assert insp.delete("nope") is False


# --------------------------------------------------------------------------- #
# Pin / unpin                                                                 #
# --------------------------------------------------------------------------- #


class TestPin:
    def test_pin(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="x")
        assert insp.pin(item.id) is True
        assert insp.get(item.id).pinned is True

    def test_pin_missing(self, insp: Inspector) -> None:
        assert insp.pin("nope") is False

    def test_unpin(self, insp: Inspector) -> None:
        item = insp.add(user_id="u1", data_class=DataClass.LOCATION, content="x", pinned=True)
        assert insp.unpin(item.id) is True
        assert insp.get(item.id).pinned is False

    def test_unpin_missing(self, insp: Inspector) -> None:
        assert insp.unpin("nope") is False


# --------------------------------------------------------------------------- #
# Query / all_for_user / by_category / count                                 #
# --------------------------------------------------------------------------- #


class TestQueries:
    def test_query(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        insp.add(user_id="u1", data_class=DataClass.EMAIL, content="b")
        result = insp.query(InspectorQuery(user_id="u1"))
        assert len(result) == 2

    def test_query_with_data_class(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        insp.add(user_id="u1", data_class=DataClass.EMAIL, content="b")
        result = insp.query(InspectorQuery(user_id="u1", data_class=DataClass.LOCATION))
        assert len(result) == 1

    def test_query_with_limit(self, insp: Inspector) -> None:
        for i in range(5):
            insp.add(
                user_id="u1",
                data_class=DataClass.LOCATION,
                content=f"item-{i}",
                item_id=f"id-{i}",
            )
        result = insp.query(InspectorQuery(user_id="u1", limit=3))
        assert len(result) == 3

    def test_query_newest_first(self, insp: Inspector) -> None:
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        new = datetime(2030, 1, 1, tzinfo=timezone.utc)
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="old", when=old, item_id="o")
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="new", when=new, item_id="n")
        result = insp.query(InspectorQuery(user_id="u1"))
        assert result[0].id == "n"

    def test_all_for_user(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a", item_id="1")
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="b", item_id="2")
        insp.add(user_id="u2", data_class=DataClass.LOCATION, content="c", item_id="3")
        assert len(insp.all_for_user("u1")) == 2

    def test_by_category(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a", item_id="1")
        insp.add(user_id="u1", data_class=DataClass.EMAIL, content="b", item_id="2")
        groups = insp.by_category("u1")
        assert "location" in groups
        assert "email" in groups

    def test_count(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a", item_id="1")
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="b", item_id="2")
        insp.add(user_id="u1", data_class=DataClass.EMAIL, content="c", item_id="3")
        counts = insp.count("u1")
        assert counts["location"] == 2
        assert counts["email"] == 1


# --------------------------------------------------------------------------- #
# Sources / refresh / prune                                                  #
# --------------------------------------------------------------------------- #


class TestSources:
    def test_add_source(self, insp: Inspector) -> None:
        insp.add_source("memory", lambda uid: [])
        assert "memory" in insp.sources()

    def test_remove_source(self, insp: Inspector) -> None:
        insp.add_source("memory", lambda uid: [])
        insp.remove_source("memory")
        assert "memory" not in insp.sources()

    def test_refresh_pulls_items(self, insp: Inspector) -> None:
        def source(uid: str) -> list[DataItem]:
            return [_item(item_id="from-source")]

        insp.add_source("memory", source)
        added = insp.refresh("u1")
        assert added == 1
        assert insp.get("from-source") is not None

    def test_refresh_skips_existing(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a", item_id="x")
        insp.add_source("memory", lambda uid: [_item(item_id="x")])
        added = insp.refresh("u1")
        assert added == 0

    def test_refresh_swallows_source_errors(self, insp: Inspector) -> None:
        def bad(uid: str) -> list[DataItem]:
            raise RuntimeError("nope")

        insp.add_source("bad", bad)
        assert insp.refresh("u1") == 0

    def test_prune_removes_stale(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a", item_id="1")
        insp.add_source("memory", lambda uid: [_item(item_id="2")])
        removed = insp.prune("u1")
        assert removed == 1
        assert insp.get("1") is None
        assert insp.get("2") is None  # not added by prune


# --------------------------------------------------------------------------- #
# Reset / len                                                                 #
# --------------------------------------------------------------------------- #


class TestReset:
    def test_reset_clears_items_and_sources(self, insp: Inspector) -> None:
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        insp.add_source("memory", lambda uid: [])
        insp.reset()
        assert len(insp) == 0
        assert insp.sources() == []

    def test_len(self, insp: Inspector) -> None:
        assert len(insp) == 0
        insp.add(user_id="u1", data_class=DataClass.LOCATION, content="a")
        assert len(insp) == 1


# --------------------------------------------------------------------------- #
# Singleton                                                                   #
# --------------------------------------------------------------------------- #


class TestSingleton:
    def test_get_default(self) -> None:
        i1 = get_default_inspector()
        i2 = get_default_inspector()
        assert i1 is i2

    def test_set_replaces(self) -> None:
        custom = Inspector()
        set_default_inspector(custom)
        try:
            assert get_default_inspector() is custom
        finally:
            set_default_inspector(None)
        assert get_default_inspector() is not custom
