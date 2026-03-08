# HomeSentinel AI v4 - Implementation Plan & Gap Analysis

_Autonomous Distributed Intelligent Surveillance Platform_

## Executive Summary of Gap Analysis

The current codebase is a monolithic, pseudo-distributed system (`homesentinel.py`) relying on Python's `multiprocessing`/`threading` and a **Redis Pub/Sub** message bus. While it implements several advanced concepts (YOLO, ReID, basic behavior histograms, basic graph structures), it falls significantly short of the requested **containerized microservices architecture**, **Kafka-backed event streaming**, and **spatial/behavioral intelligence** requirements.

The goal of this plan is to outline the exact gaps and dictate the implementation roadmap to convert the existing codebase into a true, edge-optimized, modular, fault-tolerant distributed system.

---

## Phase 1: Infrastructure & Message Bus Migration (GAP)

**Goal:** Migrate from monolithic processes to isolated Docker containers communicating primarily via Redis Pub/Sub and secondarily via MQTT.

### Current State
- `monitoring/src/message_bus.py` uses Redis Pub/Sub.
- Services are bundled into `homesentinel.py` as threads/multiprocessing processes.
- No containerization strategy for individual microservices.

### Required Implementation
- [ ] **Dockerization**: Create separate `Dockerfiles` for each of the 10 core microservices (Camera, Edge Video, YOLO26, Tracking, Face, Identity, Event, Risk Analysis, Alert, Evidence).
- [ ] **Redis Integration (Keep & Enhance)**: Maintain Redis Pub/Sub as the primary high-throughput message broker for the edge nodes. Implement the following mandatory channels:
  - `camera.frames`, `frames.optimized`, `detections.yolo26`, `tracking.objects`, `faces.detected`, `identity.results`, `events.detected`, `alerts.generated`, `graph.updates`, `behavior.updates`
- [ ] **MQTT Integration**: Add an MQTT bridge for secondary edge communications (`home/frames`, `home/detections`, `home/events`, `home/alerts`).
- [ ] **Database Standardization**: Enforce strictly **SQLite** for relational storage (events, evidence paths) and **Neo4j** specifically for graph intelligence. Remove Postgres dependencies in the edge components.

## Phase 2: Core Microservices Decoupling (GAP)

**Goal:** Isolate and refine the core computer vision and camera services into independent, horizontally scalable containers.

### Current State
- `YOLODetector`, `ByteTrackTracker`, `ReID`, and `CameraStream` run in shared memory/processes.
- Face service uses `w600k_r50.onnx` ArcFace model.
- Model loading is hardcoded on initialization.

### Required Implementation
- [ ] **Camera Service**: Extract to independent service publishing raw frames to Kafka.
- [ ] **Edge Video Service**: Implement a dedicated service to consume `camera.frames`, decode, resize, perform motion detection, and publish to `frames.optimized`.
- [ ] **YOLO26 Detection Service**: Isolate object detection. Ensure strict usage of `YOLO26` (nano/small) to detect Person, Object, Pet. Publish to `detections.yolo26`.
- [ ] **Tracking Service**: Isolate ByteTrack logic to maintain persistent IDs across occlusions. Consume `detections.yolo26`, publish to `tracking.objects`.
- [ ] **Face & Identity Services**: 
  - **CRITICAL FIX**: Replace ArcFace with **MobileFaceNet** as strictly required. 
  - Split into Face Service (detection, cropping, embedding extraction) and Identity Service (matching embeddings to Family, Child, Guest, Unknown).
- [ ] **AI Model Manager**: Build a new service responsible for dynamically loading, updating, and switching models (YOLO26, Face embeddings, Behavior models) without service downtime.

## Phase 3: Advanced AI & Spatial Reasoning (GAP)

**Goal:** Implement true 3D spatial mapping, behavior learning, and multi-object reasoning which are currently only mocked or implemented fundamentally in code.

### Current State
- `HouseMappingEngine` is a hardcoded Python adjacency dictionary.
- `PathPredictionAI` uses simple uniform probability across adjacent rooms.
- `SelfLearningBehaviorModel` is basic (time histograms).
- Suspicion scoring lacks rigorous mapping.

### Required Implementation
- [ ] **3D House Mapping Engine**: Move from hardcoded dictionaries to a robust spatial model storing Rooms, Doors, Entrances, and Restricted Areas. Incorporate Camera Spatial Data (`position_x/y/z`, `view_direction`, `field_of_view`).
- [ ] **Real-Time Graph Intelligence (Neo4j)**: Ensure real-time consumption of `graph.updates` Kafka topic to build nodes (Person, Object, Camera, Location, Event) and relationships (`SEEN_AT`, `MOVED_TO`, `HOLDING`, `INTERACTED_WITH`).
- [ ] **Path Prediction AI**: Enhance prediction to utilize Neo4j graph history, predicting target locations with associated probabilities (e.g., `Door 0.7`, `Garage 0.2`).
- [ ] **Multi-Object Reasoning Engine**: Implement complex rule logic over graph data:
  - Child near knife -> CRITICAL
  - Person carrying box + Box missing -> Object removal
  - Pet near open door -> Escape attempt
- [ ] **Self-Learning Behavior Model**: Enhance lightweight learning to maintain normal hours, specific normal paths, normal rooms, normal object locations, and normal pet patterns via frequency maps and transition matrices.
- [ ] **Suspicion Scoring AI**: Implement the strict 0.0 -> 1.0 scoring formula mapping to LOW (0.0-0.2), MEDIUM (0.2-0.5), HIGH (0.5-0.8), CRITICAL (0.8-1.0) based on identity, time, weapon presence, and graph context.

## Phase 4: Event, Alert, and Evidence Management (GAP)

**Goal:** Complete the event correlation and alerting pipeline.

### Current State
- `AlertManager` exists but needs to listen to a standardized Kafka bus.
- Telegram webhook alerts exist but lack standardized formatting.

### Required Implementation
- [ ] **Event Detection Service**: Isolate logic to detect Unknown Person, Weapon, Restricted Entry, Object movement, Pet escape, and Loitering. Publish to `events.detected`.
- [ ] **Risk Analysis Service**: Consume events, query Suspicion Scoring AI, and output HIGH/CRITICAL severities to `alerts.generated`.
- [ ] **Evidence Service**: Manage SQLite database inserts (`event_id`, `timestamp`, `camera_id`, `location`, `track_id`, `identity`, `confidence`, `anomaly_type`, `severity`, `image_path`, `video_path`) and filesystem storage for crops/clips.
- [ ] **Alert Service**: Format Telegram alerts exactly as required (Event, Camera, Identity, Severity, Time, Image included). Ensure webhook integration.
- [ ] **Live API (FastAPI)**: Standardize endpoints (`/video/{camera_id}`, `/events/live`, `/events/history`, `/cameras`).

## Phase 5: Edge Optimization & P2P Network (GAP)

**Goal:** Ensure the system runs smoothly on ARM/Snapdragon CPUs with 8GB RAM without centralized reliance.

### Current State
- `EdgeAIScheduler` is basic.
- `EdgeToEdgeNetwork` simulates P2P by passing messages in memory/Redis locally.

### Required Implementation
- [ ] **Edge AI Scheduler**: Enforce strict limits (CPU < 70%, RAM < 6GB) per edge node. Dynamically adjust inference frequency/FPS based on activity thresholds. Target: 640x480 @ 5-10 FPS per camera.
- [ ] **Smart Caching System**: Finalize caching for detection results, embeddings, and motion states with adaptive expiration to save CPU cycles.
- [ ] **Edge-to-Edge Intelligence Network**: Implement true P2P communication (e.g., direct MQTT or UDP broadcasts between network nodes without a central broker) to share Identity embeddings, Tracking IDs, and graph updates instantly across the mesh.

---
**Status**: Architecture redesign pending execution. Monolith to Microservices transition is required for full v4 compliance.
