---
name: Local ML Models
module_id: skill.bundled.local_ml
version: 1.0.0
category: skill
origin: bundled
triggers:
  - pattern: "run.*local.*model|llama|llama.cpp"
    confidence: 0.90
  - pattern: "download.*model.*huggingface|hf.*model"
    confidence: 0.85
  - pattern: "search.*huggingface|find.*model"
    confidence: 0.80
  - pattern: "vllm.*status|local.*inference"
    confidence: 0.75
capabilities: [local-ml, llama-cpp, huggingface, vllm]
trust_level: workspace
enabled_by_default: true
stability: stable
---

# Local ML Models

Run local machine learning models via llama.cpp, search and download from HuggingFace Hub, and manage vLLM servers.

## When to Use
Use when the user wants to run LLM inference locally, download models from HuggingFace, check local model availability, or manage a vLLM server.

## Procedure

### Chat with Local Model (llama.cpp)
1. Call `local_ml` with `action=chat`, `prompt=<text>`, `model=<path>`
2. Optionally set `max_tokens`, `temperature`, `top_k`
3. Requires a GGUF model file and llama.cpp CLI installed
4. Return the generated text

### Download from HuggingFace
1. Call `local_ml` with `action=hf_download`, `model=<repo_id>`
2. Automatically detects GGUF files and downloads only those
3. For non-GGUF repos, downloads config files (skips large weights)
4. Requires `huggingface_hub` Python package

### Search HuggingFace Models
1. Call `local_ml` with `action=hf_search`, `query=<search text>`
2. Returns top 20 models sorted by downloads
3. Each result includes model_id, pipeline_tag, downloads, likes

### Check vLLM Status
- Call `local_ml` with `action=vllm_status`

### List Local Models
- Call `local_ml` with `action=list_models`
- Searches common model directories for GGUF files

## Example
```
User: Can you run Llama 3.2 locally?
Agent: Let me check what models we have.
       [local_ml: action=list_models]
       We have these GGUF models available:
       - models/llama-3.2-3b-instruct.Q4_K_M.gguf (2.1 GB)
       
       What would you like to ask the model?
```

## Dependencies
- llama.cpp CLI (llama-cli or main binary)
- huggingface_hub Python package
