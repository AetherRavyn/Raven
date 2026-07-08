# Core Cognitive & ML Depth

RAVEN is model-agnostic, capable of routing tasks to 13+ LLM providers, Vision-Language Models (VLMs), and Audio models. Its core intelligence is governed by specialized cognitive engines in `app/core/`. The system implements a three-tier cognitive architecture (System 0/1/2), reinforcement learning from human feedback (RLHF), multi-modal vision pipelines, fact checking, self-correction, and metacognitive monitoring.

## 1. Multi-Provider LLM Architecture

RAVEN abstracts model inference through a pluggable provider interface with automatic fallback routing. All providers are created through `app/provider/factory.py` and managed by `app/provider/manager.py`.

### Complete Provider Table

| Provider ID | Class Location | Auth Method | Base URL Pattern | Supported Models | Tier | Notes |
|---|---|---|---|---|---|---|
| `xai` | `app/providers/xai/client.py` | API Key (`XAI_API_KEY`) | `https://api.x.ai/v1` | grok-beta, grok-vision-beta | Cloud (Deep) | gRPC-based, supports vision |
| `openai` | via openai SDK | API Key (`OPENAI_API_KEY`) | `https://api.openai.com/v1` | gpt-4o, gpt-4o-mini, gpt-4-turbo | Cloud (Deep) | Full tool-calling + streaming |
| `anthropic` | via anthropic SDK | API Key (`ANTHROPIC_API_KEY`) | `https://api.anthropic.com/v1` | claude-3-5-sonnet-20241022, claude-3-opus | Cloud (Deep) | Long context (200K tokens) |
| `google` | via google-generativeai | API Key (`GOOGLE_API_KEY` or `GEMINI_API_KEY`) | `https://generativelanguage.googleapis.com/v1` | gemini-1.5-pro, gemini-1.5-flash | Cloud (Cheap/Deep) | Very large context window (1M tokens) |
| `ollama` | `app/providers/ollama/client.py` | None (local) | `http://localhost:11434` | Any Ollama-hosted model (llama3.2, mistral, etc.) | Local (Free) | No auth; configurable via `OLLAMA_MODEL` |
| `vllm` | factory-based | None (local) | `http://localhost:8000` | Any vLLM-hosted model | Local (Free) | OpenAI-compatible API |
| `openrouter` | factory-based | API Key (`OPENROUTER_API_KEY`) | `https://openrouter.ai/api/v1` | 200+ models (aggregator) | Aggregator (Cheap) | Access to multiple models through one API |
| `groq` | factory-based | API Key (`GROQ_API_KEY`) | `https://api.groq.com/openai/v1` | llama3-70b, mixtral, gemma | Cloud (Cheap) | Very fast inference |
| `deepseek` | factory-based | API Key (`DEEPSEEK_API_KEY`) | `https://api.deepseek.com/v1` | deepseek-chat, deepseek-coder | Cloud (Cheap) | Strong coding performance |
| `nvidia` | factory-based | API Key (`NVIDIA_NIM_API_KEY`) | `https://integrate.api.nvidia.com/v1` | meta/llama3-70b-instruct | Cloud (Cheap) | NVIDIA NIM inference |
| `huggingface` | factory-based | API Key (`HUGGINGFACE_API_KEY`) | `https://api-inference.huggingface.co/models` | meta-llama/Meta-Llama-3-70B-Instruct | Cloud (Cheap) | HuggingFace Inference API |
| `opencode_zen` | factory-based | Free (no key) | `https://api.opencode.ai/v1` | big-pickle, small-pickle (5 free models) | Cloud (Free) | Always-available fallback; no key needed |
| `localai` / `lm_studio` | factory-based | None (local) | `http://localhost:8080` | Any LocalAI/LM Studio model | Local (Free) | OpenAI-compatible API |

### Routing Strategy

The `ModelRouter` class in `app/core/model_router.py` classifies requests into three tiers using keyword heuristics:

```python
# From app/core/model_router.py:30
def classify(self, text: str) -> str:
    lowered = text.lower().strip()
    if any(word in lowered for word in ("hello", "hi", "time", "status", "os")):
        return "local"
    if any(phrase in lowered for phrase in ("search", "summary", "summarize",
        "explain", "what is", "how do", "compare", "why")):
        return "cheap"
    return "deep"
```

**Tier behavior:**
- **Local** (Ollama, vLLM): Simple queries, greetings, time/status checks, routing decisions. Response < 1s. Uses the local provider shortcut when the default provider is free/local.
- **Cheap** (OpenCode Zen, Groq, DeepSeek): Standard responses, web search summaries, explanations. Balanced cost/quality.
- **Deep** (xAI/Grok, OpenAI, Anthropic, Gemini): Complex reasoning, code generation, multi-step task planning, financial analysis. Highest quality, higher latency.

### AutoModelRouter Fallback Chain

The `AutoModelRouter` in `app/core/model_router.py:154` provides the `get_best_model()` method that resolves the best available provider through a cascading priority chain:

1. **ProviderManager combo** — If the user configured a dashboard combo/ranking, trust it first.
2. **Explicit env override** — `LLM_PROVIDER` and `LLM_MODEL` env vars.
3. **High-tier API keys** — Checks for valid Anthropic key first, then OpenAI, then Google/Gemini. Skip test/placeholder keys (`sk-dashboard-paste-test`, etc.).
4. **OpenCode Zen** — Free cloud gateway. Always available, no key needed. Comes before local because local is unreliable (Ollama crashes, model not loaded).
5. **Local endpoints** — Last resort. Checks vLLM, LM Studio, LocalAI, and Ollama health endpoints.

The `get_available_models()` method returns all configured providers as a prioritized list used for resilient fallback during actual LLM calls:

```python
fallbacks = AutoModelRouter.get_available_models("agent")
for f_prov_name, f_model_name in fallbacks:
    f_prov = create_provider(f_prov_name)
    f_res = await f_prov.chat_completion(model=f_model_name, messages=messages)
    if f_res.get("success"):
        result = f_res
        break
```

The fallback loop in `AgentRuntime.execute_turn()` (`app/core/runtime.py:2273`) tracks failed providers to avoid retrying them, caps at 3 fallback attempts, and updates the active provider on success so subsequent turns use the working fallback.

### RL Feedback on Routing

The `ModelRouter.record_feedback()` method integrates feedback into routing decisions:

```python
def record_feedback(self, route_kind: str, reward: float, reason: str = "") -> None:
    self.feedback.add_feedback(user_id="system", item_type="route",
        item_id=route_kind, reward=reward, reason=reason)
```

During `resolve()`, the router consults `self.feedback.score("route", route_kind)` and if the bias exceeds 0.25, it downgrades non-deep routes to local, preferring the free tier for unreliable deep providers.

## 2. RLHF Pipeline

RAVEN features a localized, continuous RLHF loop that aligns with user preferences without full finetuning. The pipeline involves three stages:

### Stage 1: Feedback Collection

Feedback is collected from multiple sources:
- **Explicit**: Thumbs up/down, satisfaction scores (1-5), natural language corrections
- **Implicit**: Tool execution success/failure, user rephrasing (suggests misunderstanding), user abandonment
- **Systemic**: Task completion rate, response latency, token efficiency

The `FeedbackStore` (`app/core/feedback.py`) persists feedback as structured records to `workspace/memory/feedback.db`:

```python
event = self.feedback_store.add_feedback(
    user_id=request.user_id,
    item_type=item_type,     # "route", "tool", "response"
    item_id=item_id,         # e.g. "openai/gpt-4o"
    reward=reward,           # -1.0 to 1.0
    reason=reason,
    metadata=metadata or {},
)
```

### Stage 2: PreferenceStore → RlhfRouter

The `ReinforcementLearner` (`app/core/reinforcement_learning.py:110`) uses tabular Q-learning with UCB exploration. State dimensions:
- `task_category` (str): "coding", "research", "finance", etc.
- `hour_bucket` (int 0-4): morning, late_morning, afternoon, evening, night
- `user_tier` (str): "new" (<10 interactions), "regular" (10-100), "power" (>100)

Reward values:
- +1.0 explicit positive feedback
- -1.0 explicit negative feedback
- +0.5 successful tool call
- -0.3 tool call failure
- +0.2 task completed successfully

The Q-table persists to `workspace/reinforcement_learning/q_table.json`. The `RlhfRouter` alters agent routing based on past success/failure per provider per style. For example, if `gpt-4o` consistently fails on coding tasks but `claude-3.5-sonnet` succeeds, the router learns to route coding tasks to Anthropic.

### Stage 3: RlhfCrystallizer

The `SkillCrystallizer` (`app/core/skill_crystallizer.py`) synthesizes broad preference trends into permanent behavioral rules. It runs on a schedule (every 200 turns via the TaskScheduler) and:
1. Reviews successful execution traces
2. Extracts parameter patterns (e.g., always use `--no-cache` for Docker builds)
3. Generalizes hardcoded values into parameters
4. Writes structured skill definitions to the skill store

## 3. Dual Cognition Architecture

RAVEN implements a three-tier cognitive ladder for efficient resource allocation:

### System 0 — Ambient Loop (Reflex)

**File**: `app/core/proactive_core/engine.py`, `app/core/proactive_bootstrap.py`

Always-on background monitoring with a 60-second tick interval. No LLM invocation. Trigger conditions:
- Timer-based: 30s heartbeat, 60s sensor poll, 5min memory sync
- Event-based: MQTT messages, webhook POSTs, Home Assistant state changes
- Sensor-based: Temperature threshold exceeded, motion detected, door opened

### System 1 — MiniEngine (Fast)

**File**: `app/minichat/minichat.py`

Lightweight heuristics and pattern matching for tasks requiring <2 second response:
- Simple Q&A (time, weather, status)
- Intent classification
- Direct command routing (git, file ops, web search)
- No tool calls — pure pattern matching

The `System1Router` evaluates each inbound signal and either handles it directly or escalates to System 2.

### System 2 — AgentRuntime (Deep)

**File**: `app/core/runtime.py`

Full ReAct loop with tool execution and multi-step reasoning:
- Response time: 5-30 seconds
- Max turns: 15 (configurable via `max_turns = 15` in `app/core/runtime.py:2174`)
- Max same-tool streak: 3 (forces synthesis after N consecutive identical tool calls)
- Input size limit: 30,000 chars (~7,500 tokens)
- Token compression trigger: 80,000 tokens (auto-compresses session history)
- Full planning, verification, and learning pipeline

The `MessageOrchestrator` (`app/core/orchestrator.py:143`) routes each inbound signal to the appropriate tier based on complexity, urgency, and user preferences.

## 4. Cognitive Modules Reference

| Module | File Path | Description | Key Methods | Configuration Options |
|---|---|---|---|---|
| `SoulEngine` | `app/core/soul_engine.py` | Loads SOUL.md identity; defines agent's immutable core purpose | `get_persona()`, `get_rules()` | `SOUL.md` file path |
| `Attention` / WorkingMemory | `app/core/attention.py` | 7±2 item working memory buffer with relevance decay | `focus(item)`, `decay()`, `summarize()` | Buffer size, decay rate |
| `Perception` | `app/core/perception.py` | Environmental context gathering | `gather_context()`, `get_ambient_data()` | Sensor endpoints |
| `Metacognition` | `app/core/metacognition.py` | Self-monitoring; selects reasoning strategy; detects uncertainty | `select_strategy(text, category)`, `reflect()`, `get_confidence()` | `RAVEN_METACOGNITION_ENABLED` env var |
| `Learner` | `app/core/learner.py` | Continuous learning from interaction patterns | `learn(turn)`, `get_agent_ranking()`, `get_best_agent()` | Learning rate, memory size |
| `PatternLearner` | `app/core/pattern_learner.py` | Identifies recurring behavior patterns | `learn_from_interaction()`, `get_patterns()` | Pattern window size |
| `AnalogyEngine` | `app/core/analogy.py` | Maps novel problems to known solution patterns | `suggest_approach(problem, category)`, `record_case()` | Case store path |
| `Counterfactual` | `app/core/counterfactual.py` | Explores alternative reasoning paths | `explore_alternative()`, `compare_paths()` | Max alternatives |
| `FactCheckEngine` | `app/core/trust/fact_check.py` | Validates claims against knowledge graphs and search | `verify(claim)`, `get_evidence()` | Search provider, trust threshold |
| `SelfCorrectionEngine` | `app/core/self_improvement.py` | Analyzes failures and iterates solutions | `correct(trace)`, `verify_correction()` | Max correction attempts |
| `CuriosityModule` | `app/core/proactive_intelligence.py` | Identifies knowledge gaps; triggers ambient research | `scan_knowledge_gaps()`, `explore(topic)` | Scan interval, exploration budget |
| `TrajectoryCompressor` | `app/core/trajectory_compressor.py` | Compresses multi-step execution traces | `compress(messages, force)` | Compression threshold (80K tokens) |
| `LanguageDetect` | `app/core/language_detect.py` | Automatic language detection for multilingual responses | `get_language_name(text)` | Supported languages list |
| `Persona` | `app/core/persona.py` | Adaptive personality based on user history | `generate_system_prompt(base, user_id)` | Personality traits |
| `ForecastEngine` | `app/core/forecast.py` | Predictive analytics for scheduling | `predict()`, `get_forecast()` | Forecast horizon |
| `OpportunityDetector` | `app/core/opportunity.py` | Identifies proactive action opportunities | `scan()`, `evaluate(opportunity)` | Threshold score |

## 5. Vision & Multimodal Pipeline

Leveraging the `MultiModalProcessor` (`app/core/multimodal.py`) and `MultimodalContextBuilder` (`app/core/multimodal.py`), images are analyzed through a multi-stage pipeline:

1. **YOLO Detection** (external monitoring process): Rapid object detection and bounding box identification on camera streams. Results posted to the webhook server at `POST /internal/camera-alert`.

2. **Semantic Embedding** (`app/core/multimodal_retrieval.py`): Images are embedded into ChromaDB using MobileNet or ONNX-based local models for semantic recall (e.g., "show me the picture of the red car from yesterday").

3. **Vision LLM Analysis**: The `MultimodalContextBuilder.from_request()` method constructs image context from `request.image_urls`. These are passed to the provider's chat completion as multimodal content arrays (text + image_url). Supported VLMs: xAI Grok Vision, GPT-4o, Gemini 1.5 Pro Vision.

4. **Video Fusion** (`app/core/video_fusion.py`): Temporal analysis of video streams. The `VideoEventFusion` module correlates events across frames and tracks objects over time.

```python
# From runtime.py execute_turn
if request.image_urls:
    content_array = [{"type": "text", "text": input_text}]
    for url in request.image_urls:
        content_array.append({"type": "image_url", "image_url": {"url": url}})
    user_msg = {"role": "user", "content": content_array}
```

## 6. Fact Checking Workflow

The fact-checking pipeline (`app/core/trust/fact_check.py`, `app/core/trust/citations.py`, `app/core/trust/source_trust.py`):

1. **Claim Extraction**: After the LLM generates a response, extract factual claims
2. **Source Retrieval**: Search knowledge graph, web search, and learning store for supporting evidence
3. **Verification**: Cross-reference claims against sources; assign confidence scores
4. **Citation Injection**: Attach citations and evidence footnotes to the response
5. **User-Facing Evidence**: The `_attach_evidence_footer()` method appends evidence lines to responses:

```python
evidence = self._build_evidence_lines(request, plan, traces, content)
content = self._attach_evidence_footer(content, evidence)
```

## 7. Self-Correction Loop

The self-correction system (`app/core/self_improvement.py`, `app/core/verifier/`):

1. **Failure Detection**: Tool execution failures, provider errors, verification failures
2. **Analysis**: The `Verifier` checks plan step completion against success criteria
3. **Correction**: The `SelfCorrectionEngine` generates alternative approaches
4. **Verification**: Corrections are verified; probes track pass/fail rates
5. **Learning**: Successful corrections are stored in the learning store for future use
6. **Escalation**: If verification fails, the system appends a verification message and retries:

```python
verification = self.verifier.verify(plan, content)
if not verification.get("success"):
    msg = {"role": "system", "content": f"[SYSTEM VERIFICATION FAILED] {verification.get('findings')}"}
    messages.append(msg)
```

## 8. Performance Characteristics Per Tier

| Metric | Local (Ollama) | Cheap (Groq/Zen) | Deep (OpenAI/Anthropic) |
|---|---|---|---|
| Avg Latency | 500-2000ms | 200-800ms | 1000-5000ms |
| Token Cost | Free | ~$0.15/M tokens | ~$10-30/M tokens |
| Context Window | 8K-128K | 8K-32K | 128K-200K |
| Reliability | 70-90% | 95-99% | 99.5-99.9% |
| Availability | Local-only | Cloud 99.9% | Cloud 99.95% |
| Best For | Simple Q&A, routing | Summaries, search | Code, reasoning, planning |

## 9. Configuration Examples

```ini
# Primary (deep) provider
LLM_PROVIDER=xai
XAI_API_KEY=your-xai-key-here
LLM_MODEL=grok-beta

# Fallback chain — AutoModelRouter checks keys in priority order
ANTHROPIC_API_KEY=sk-ant-your-key
OPENAI_API_KEY=sk-your-key
GOOGLE_API_KEY=your-google-key

# Lightweight (local) provider
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
LOCAL_LIGHT_MODEL=ollama/llama3.2:3b

# Aggregator
OPENROUTER_API_KEY=sk-or-your-key

# Free fallback (always available)
OPENCODE_ZEN_MODEL=big-pickle

# Local endpoints
VLLM_BASE_URL=http://localhost:8000
LM_STUDIO_BASE_URL=http://localhost:1234
LOCALAI_BASE_URL=http://localhost:8080

# Budget control
RAVEN_DAILY_BUDGET_USD=0.50
RAVEN_COGNITION_LADDER=true
RAVEN_COST_ROUTER_V2=true
```

## 10. Edge Cases and Failure Modes

- **Provider rate limiting**: The `chat_completion_resilient()` wrapper handles 429/503 errors with exponential backoff. If all providers fail, the system returns a cached response or the `REBOOT_BANNER`.
- **Empty API keys**: Skipped via `_skip_keys` set including `""`, `"sk-dashboard-paste-test"`, `"no-key-needed"`, `"none"`, `"undefined"`.
- **Ollama crash**: The `_local_available()` health check caches failure for the session. If local goes down, degrades to cloud-only mode.
- **Token overflow**: Automatic compression triggers at 80K tokens. Input truncation at 30K chars. Session pruning removes oldest messages.
- **Tool call loops**: The same-tool streak breaker forces LLM to synthesize after 3 consecutive identical tool calls.
- **RTF (Runtime Failure)**: The fallback loop tries up to 3 different providers, skipping failed ones, before giving up.
