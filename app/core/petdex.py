from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PetSpecies(str, Enum):
    RAVEN = "raven"
    CROW = "crow"
    PARROT = "parrot"
    OWL = "owl"
    PHOENIX = "phoenix"

    def __str__(self) -> str:
        return self.value


class PetState(str, Enum):
    IDLE = "idle"
    SLEEPING = "sleeping"
    HAPPY = "happy"
    SAD = "sad"
    SICK = "sick"
    EVOLVING = "evolving"

    def __str__(self) -> str:
        return self.value


class PetAction(str, Enum):
    FEED = "feed"
    PLAY = "play"
    HEAL = "heal"
    RENAME = "rename"
    EVOLVE = "evolve"

    def __str__(self) -> str:
        return self.value


class PetModel:
    __slots__ = (
        "id", "name", "species", "level", "xp", "health",
        "happiness", "hunger", "energy", "state",
        "last_fed", "last_played", "created_at", "evolved_at",
    )

    def __init__(
        self,
        id: str,
        name: str,
        species: str = "raven",
        level: int = 1,
        xp: int = 0,
        health: float = 1.0,
        happiness: float = 1.0,
        hunger: float = 1.0,
        energy: float = 1.0,
        state: str = "idle",
        last_fed: str | None = None,
        last_played: str | None = None,
        created_at: str | None = None,
        evolved_at: str | None = None,
    ) -> None:
        self.id = id
        self.name = name
        self.species = species
        self.level = level
        self.xp = xp
        self.health = health
        self.happiness = happiness
        self.hunger = hunger
        self.energy = energy
        self.state = state
        self.last_fed = last_fed
        self.last_played = last_played
        now = datetime.now(timezone.utc).isoformat()
        self.created_at = created_at or now
        self.evolved_at = evolved_at

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PetModel:
        return cls(
            id=row["id"],
            name=row["name"],
            species=row["species"],
            level=row["level"],
            xp=row["xp"],
            health=row["health"],
            happiness=row["happiness"],
            hunger=row["hunger"],
            energy=row["energy"],
            state=row["state"],
            last_fed=row["last_fed"],
            last_played=row["last_played"],
            created_at=row["created_at"],
            evolved_at=row["evolved_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "species": self.species,
            "level": self.level,
            "xp": self.xp,
            "health": self.health,
            "happiness": self.happiness,
            "hunger": self.hunger,
            "energy": self.energy,
            "state": self.state,
            "last_fed": self.last_fed,
            "last_played": self.last_played,
            "created_at": self.created_at,
            "evolved_at": self.evolved_at,
        }

    def __repr__(self) -> str:
        return (
            f"PetModel(id={self.id!r}, name={self.name!r}, "
            f"species={self.species!r}, level={self.level})"
        )


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pets (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    species TEXT NOT NULL DEFAULT 'raven',
    level INTEGER NOT NULL DEFAULT 1,
    xp INTEGER NOT NULL DEFAULT 0,
    health REAL NOT NULL DEFAULT 1.0,
    happiness REAL NOT NULL DEFAULT 1.0,
    hunger REAL NOT NULL DEFAULT 1.0,
    energy REAL NOT NULL DEFAULT 1.0,
    state TEXT NOT NULL DEFAULT 'idle',
    last_fed TEXT,
    last_played TEXT,
    created_at TEXT NOT NULL,
    evolved_at TEXT
);

CREATE TABLE IF NOT EXISTS pet_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pet_id TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (pet_id) REFERENCES pets(id)
);
"""


class PetdexManager:
    def __init__(self, db_path: str | Path = "workspace/memory/petdex.db") -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA busy_timeout=5000")
        return self._local.conn

    def _init_db(self) -> None:
        self._conn.executescript(_SCHEMA_SQL)
        self._conn.commit()

    def _log_interaction(self, pet_id: str, action: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO pet_interactions (pet_id, action, timestamp) VALUES (?, ?, ?)",
            (pet_id, action, now),
        )
        self._conn.commit()

    def adopt(self, name: str, species: str = "raven") -> PetModel:
        if species not in {s.value for s in PetSpecies}:
            raise ValueError(f"Unknown species: {species!r}. Choose from {[s.value for s in PetSpecies]}")
        pet = PetModel(
            id=str(uuid.uuid4()),
            name=name,
            species=species,
        )
        self._conn.execute(
            """INSERT INTO pets (id, name, species, level, xp, health, happiness, hunger, energy, state, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                pet.id, pet.name, pet.species, pet.level, pet.xp,
                pet.health, pet.happiness, pet.hunger, pet.energy,
                pet.state, pet.created_at,
            ),
        )
        self._conn.commit()
        self._log_interaction(pet.id, PetAction.HEAL.value)
        logger.info("Pet adopted: %s (%s, %s)", pet.name, pet.species, pet.id)
        return pet

    def get_pet(self, pet_id: str) -> PetModel | None:
        row = self._conn.execute("SELECT * FROM pets WHERE id = ?", (pet_id,)).fetchone()
        return PetModel.from_row(row) if row else None

    def list_pets(self) -> list[PetModel]:
        rows = self._conn.execute("SELECT * FROM pets ORDER BY created_at DESC").fetchall()
        return [PetModel.from_row(r) for r in rows]

    def feed(self, pet_id: str) -> PetModel:
        pet = self._get_pet_or_raise(pet_id)
        pet.hunger = min(1.0, pet.hunger + 0.3)
        pet.happiness = min(1.0, pet.happiness + 0.1)
        pet.last_fed = datetime.now(timezone.utc).isoformat()
        self._update_pet(pet)
        self._log_interaction(pet_id, PetAction.FEED.value)
        logger.info("Pet fed: %s", pet_id)
        return pet

    def play(self, pet_id: str) -> PetModel:
        pet = self._get_pet_or_raise(pet_id)
        pet.happiness = min(1.0, pet.happiness + 0.3)
        pet.energy = max(0.0, pet.energy - 0.2)
        pet.last_played = datetime.now(timezone.utc).isoformat()
        self._update_pet(pet)
        pet = self.add_xp(pet_id, 10)
        self._log_interaction(pet_id, PetAction.PLAY.value)
        logger.info("Pet played: %s", pet_id)
        return pet

    def heal(self, pet_id: str) -> PetModel:
        pet = self._get_pet_or_raise(pet_id)
        pet.health = 1.0
        self._update_pet(pet)
        self._log_interaction(pet_id, PetAction.HEAL.value)
        logger.info("Pet healed: %s", pet_id)
        return pet

    def rename(self, pet_id: str, new_name: str) -> PetModel:
        pet = self._get_pet_or_raise(pet_id)
        pet.name = new_name
        self._update_pet(pet)
        self._log_interaction(pet_id, PetAction.RENAME.value)
        logger.info("Pet renamed: %s -> %s", pet_id, new_name)
        return pet

    def add_xp(self, pet_id: str, amount: int) -> PetModel:
        pet = self._get_pet_or_raise(pet_id)
        pet.xp += amount
        threshold = pet.level * 100
        while pet.xp >= threshold:
            pet.xp -= threshold
            pet.level += 1
            pet.state = PetState.EVOLVING.value
            pet.evolved_at = datetime.now(timezone.utc).isoformat()
            threshold = pet.level * 100
            logger.info("Pet leveled up: %s -> level %d", pet_id, pet.level)
        self._update_pet(pet)
        return pet

    def tick(self) -> None:
        rows = self._conn.execute("SELECT * FROM pets").fetchall()
        for row in rows:
            pet = PetModel.from_row(row)
            pet.hunger = max(0.0, pet.hunger - 0.02)
            pet.happiness = max(0.0, pet.happiness - 0.01)
            pet.energy = max(0.0, pet.energy - 0.01)
            pet.state = self.compute_state(pet).value
            self._update_pet(pet)
        self._conn.commit()
        logger.debug("Pet tick completed for %d pets", len(rows))

    def compute_state(self, pet: PetModel) -> PetState:
        if pet.health < 0.3:
            return PetState.SICK
        if pet.hunger < 0.2:
            return PetState.SAD
        if pet.happiness > 0.8 and pet.energy > 0.6:
            return PetState.HAPPY
        if pet.energy < 0.2:
            return PetState.SLEEPING
        return PetState.IDLE

    def get_stats(self) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) as total, AVG(level) as avg_level FROM pets"
        ).fetchone()
        total = row["total"] or 0
        avg_level = round(row["avg_level"] or 0.0, 2)
        int_row = self._conn.execute(
            "SELECT COUNT(*) as cnt FROM pet_interactions"
        ).fetchone()
        total_interactions = int_row["cnt"] or 0
        return {
            "total_pets": total,
            "avg_level": avg_level,
            "total_interactions": total_interactions,
        }

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def clear(self) -> None:
        self._conn.executescript("DELETE FROM pets; DELETE FROM pet_interactions;")
        self._conn.commit()

    def _get_pet_or_raise(self, pet_id: str) -> PetModel:
        pet = self.get_pet(pet_id)
        if pet is None:
            raise ValueError(f"Pet not found: {pet_id!r}")
        return pet

    def _update_pet(self, pet: PetModel) -> None:
        self._conn.execute(
            """UPDATE pets SET
                name=?, species=?, level=?, xp=?, health=?, happiness=?,
                hunger=?, energy=?, state=?, last_fed=?, last_played=?,
                evolved_at=?
               WHERE id=?""",
            (
                pet.name, pet.species, pet.level, pet.xp,
                pet.health, pet.happiness, pet.hunger, pet.energy,
                pet.state, pet.last_fed, pet.last_played,
                pet.evolved_at, pet.id,
            ),
        )
        self._conn.commit()
