import logging
import pprint
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    desc,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

Base = declarative_base()

# --- SQLAlchemy Models ---


class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(255), unique=True, nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    track_id = Column(Integer)
    camera_id = Column(String(100), nullable=False, index=True)
    location = Column(String(255))
    timestamp = Column(DateTime, nullable=False, index=True)
    identity = Column(String(255))
    confidence = Column(Float)
    anomaly_type = Column(String(100))
    severity = Column(String(20), nullable=False, index=True)
    risk_level = Column(String(20)) # Legacy
    description = Column(String)
    image_path = Column(String(500))
    video_path = Column(String(500))
    metadata_ = Column("metadata", JSON)  # 'metadata' is reserved in SQLAlchemy Base
    processed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class Clip(Base):
    __tablename__ = "clips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    clip_id = Column(String(255), unique=True, nullable=False)
    camera_id = Column(String(100), nullable=False, index=True)
    file_path = Column(String(500), nullable=False)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False)
    duration_seconds = Column(Float)
    event_id = Column(String(255))
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime, server_default=func.now())


class Track(Base):
    __tablename__ = "tracks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    track_id = Column(Integer, nullable=False)
    camera_id = Column(String(100), nullable=False, index=True)
    class_name = Column(String(50), nullable=False)
    first_seen = Column(DateTime, nullable=False)
    last_seen = Column(DateTime, nullable=False)
    total_distance = Column(Float, default=0.0)
    trajectory = Column(JSON)
    metadata_ = Column("metadata", JSON)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("track_id", "camera_id", name="uix_track_camera"),
    )


# --- Database Manager ---


class SQLiteDB:
    def __init__(self, config: Dict):
        # Look for sqlite config, default to a local file named saras.db
        self.config = config.get("database", {}).get("sqlite", {})
        db_path = self.config.get("db_path", "sqlite:///saras.db")

        self.engine = None
        self.SessionLocal = None
        self._init_db(db_path)

    def _init_db(self, db_path: str):
        try:
            # SQLite specific engine configurations
            self.engine = create_engine(
                db_path,
                connect_args={
                    "check_same_thread": False
                },  # Needed for multithreading in SQLite
                echo=False,  # Set to True for SQL query logging
            )

            # Create all tables
            Base.metadata.create_all(bind=self.engine)

            # Initialize session factory
            self.SessionLocal = sessionmaker(
                autocommit=False, autoflush=False, bind=self.engine
            )

            logger.info(f"SQLite database initialized at {db_path}")
        except Exception as e:
            logger.error(f"Failed to initialize SQLite database: {e}")
            self.engine = None

    def _row_to_dict(self, row) -> Dict:
        """Helper to convert SQLAlchemy model instances back to raw dicts."""
        if not row:
            return {}
        # Returns column names and their values, renaming 'metadata_' back to 'metadata'
        result = {c.name: getattr(row, c.name) for c in row.__table__.columns}
        if "metadata_" in result:
            result["metadata"] = result.pop("metadata_")
        return result

    def insert_event(self, event: Dict) -> bool:
        if not self.SessionLocal:
            return False

        with self.SessionLocal() as session:
            try:
                stmt = sqlite_insert(Event).values(
                    event_id=event.get("event_id"),
                    event_type=event.get("event_type"),
                    track_id=event.get("track_id"),
                    camera_id=event.get("camera_id"),
                    location=event.get("location") or event.get("zone_id"),
                    timestamp=event.get("timestamp"),
                    identity=event.get("identity"),
                    confidence=event.get("confidence"),
                    anomaly_type=event.get("anomaly_type"),
                    severity=event.get("severity") or event.get("risk_level", "LOW"),
                    risk_level=event.get("risk_level", "LOW"),
                    description=event.get("description"),
                    image_path=event.get("image_path"),
                    video_path=event.get("video_path"),
                    metadata_=event.get("metadata", {}),
                )

                # ON CONFLICT DO NOTHING
                stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])

                session.execute(stmt)
                session.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to insert event: {e}")
                session.rollback()
                return False

    def insert_clip(self, clip_data: Dict) -> bool:
        if not self.SessionLocal:
            return False

        with self.SessionLocal() as session:
            try:
                stmt = sqlite_insert(Clip).values(
                    clip_id=clip_data.get("clip_id"),
                    camera_id=clip_data.get("camera_id"),
                    file_path=clip_data.get("file_path"),
                    start_time=clip_data.get("start_time"),
                    end_time=clip_data.get("end_time"),
                    duration_seconds=clip_data.get("duration_seconds"),
                    event_id=clip_data.get("event_id"),
                    metadata_=clip_data.get("metadata", {}),
                )

                # ON CONFLICT DO NOTHING
                stmt = stmt.on_conflict_do_nothing(index_elements=["clip_id"])

                session.execute(stmt)
                session.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to insert clip: {e}")
                session.rollback()
                return False

    def insert_track(self, track_data: Dict) -> bool:
        if not self.SessionLocal:
            return False

        with self.SessionLocal() as session:
            try:
                stmt = sqlite_insert(Track).values(
                    track_id=track_data.get("track_id"),
                    camera_id=track_data.get("camera_id"),
                    class_name=track_data.get("class_name"),
                    first_seen=track_data.get("first_seen"),
                    last_seen=track_data.get("last_seen"),
                    total_distance=track_data.get("total_distance", 0),
                    trajectory=track_data.get("trajectory", []),
                    metadata_=track_data.get("metadata", {}),
                )

                # ON CONFLICT (track_id, camera_id) DO UPDATE
                stmt = stmt.on_conflict_do_update(
                    index_elements=["track_id", "camera_id"],
                    set_={
                        "last_seen": stmt.excluded.last_seen,
                        "total_distance": stmt.excluded.total_distance,
                        "trajectory": stmt.excluded.trajectory,
                        "metadata_": stmt.excluded.metadata_,
                    },
                )

                session.execute(stmt)
                session.commit()
                return True
            except Exception as e:
                logger.error(f"Failed to insert track: {e}")
                session.rollback()
                return False

    def get_events(
        self,
        camera_id: Optional[str] = None,
        risk_level: Optional[str] = None,
        event_type: Optional[str] = None,
        from_time: Optional[datetime] = None,
        to_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Dict]:
        if not self.SessionLocal:
            return []

        with self.SessionLocal() as session:
            try:
                query = session.query(Event)

                if camera_id:
                    query = query.filter(Event.camera_id == camera_id)
                if risk_level:
                    query = query.filter(Event.risk_level == risk_level)
                if event_type:
                    query = query.filter(Event.event_type == event_type)
                if from_time:
                    query = query.filter(Event.timestamp >= from_time)
                if to_time:
                    query = query.filter(Event.timestamp <= to_time)

                query = query.order_by(desc(Event.timestamp)).limit(limit)

                return [self._row_to_dict(row) for row in query.all()]
            except Exception as e:
                logger.error(f"Failed to get events: {e}")
                return []

    def get_clips(
        self, camera_id: Optional[str] = None, limit: int = 100
    ) -> List[Dict]:
        if not self.SessionLocal:
            return []

        with self.SessionLocal() as session:
            try:
                query = session.query(Clip)
                if camera_id:
                    query = query.filter(Clip.camera_id == camera_id)

                query = query.order_by(desc(Clip.start_time)).limit(limit)

                return [self._row_to_dict(row) for row in query.all()]
            except Exception as e:
                logger.error(f"Failed to get clips: {e}")
                return []

    def close(self):
        if self.engine:
            self.engine.dispose()
            logger.info("SQLite connection closed")
