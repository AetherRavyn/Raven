"""One-shot MobileNetV2 → ONNX export with the classifier head sliced off.

Closes Gap D in
``docs/13-jarvis-friday-gap-analysis-2026-06.md``: the
shipped ``monitoring/models/MobileNet-v2.onnx`` only
exposes the 1000-dim ``class_logits`` output, which
forces ``SemanticSearchEngine`` to fall back to coarse
ImageNet-class nearest-neighbour search.  The new export
emits **two** outputs — the 1280-dim ``features`` (the
penultimate global-avgpool layer) **and** the 1000-dim
``class_logits`` — so the engine can pick the real
semantic embedding whenever the model exposes it.

Output file
-----------

``monitoring/models/MobileNet-v2-features.onnx`` (sibling
of the existing ``MobileNet-v2.onnx``).  We do **not**
overwrite the original because:

  1. Existing on-disk indexes use the 1000-dim vector
     shape; dropping the file would orphan those indexes.
  2. The ``SemanticSearchEngine`` negotiates the active
     output at load time, so a fresh build can switch by
     setting ``RAVEN_SEMANTIC_EMBEDDING_MODE=features``
     once the new file is in place.

Why a wrapper model
-------------------

``torchvision.models.mobilenet_v2`` returns only the
logits.  To emit the 1280-dim feature vector we wrap
the backbone in a tiny ``nn.Module`` that runs
``model.features`` + global average pool + flatten, and
saves the original ``classifier`` for the second output.

Usage
-----

::

    .venv/bin/python scripts/export_mobilenet_v2_features.py

No CLI flags; the output path is hard-wired to
``monitoring/models/MobileNet-v2-features.onnx`` so the
on-disk shape matches what
``monitoring/src/semantic_search.py`` already looks for.
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
import torch.nn as nn
import torchvision.models as M


# ── Wrapper model ─────────────────────────────────────────────────────


class MobileNetV2Features(nn.Module):
    """MobileNetV2 that emits the 1280-dim penultimate features.

    The first output (``features``) is the global-average-pool
    flatten of the backbone's last conv stage — this is the
    1280-dim vector the semantic-search engine prefers.
    The second output (``class_logits``) is the original
    ImageNet 1000-dim classifier head, kept for backward
    compatibility with any caller that still wants the
    coarse class signal.
    """

    def __init__(self, base: M.MobileNetV2) -> None:
        super().__init__()
        # Trunk up to the last conv stage.  The backbone's
        # ``features`` is a Sequential of inverted-residual
        # blocks; the final element ends with a 1280-dim
        # ReLU6 (no flatten).  We add the global avgpool
        # here so the first output is 1×1280, exactly the
        # shape ``SemanticSearchEngine`` expects.
        self.features = base.features
        self.pool = nn.AdaptiveAvgPool2d(1)
        # Keep the original classifier head so the second
        # output is the same shape the legacy callers used.
        self.classifier = base.classifier

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        feats = self.features(x)
        # 1280-dim penultimate vector.
        features = self.pool(feats).flatten(1)
        # 1000-dim logits via the same classifier head.
        class_logits = self.classifier(features)
        return features, class_logits


# ── Export ────────────────────────────────────────────────────────────


REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "monitoring" / "models" / "MobileNet-v2-features.onnx"


def export() -> Path:
    """Build the wrapped model and write it to disk.

    Returns the output path on success.  Raises
    ``RuntimeError`` if the ONNX export cannot produce a
    valid model (e.g. operator-set mismatch on the host
    torch version) so the operator can investigate
    without leaving a half-written file behind.
    """
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading MobileNetV2 (ImageNet1K_V1 weights)…", file=sys.stderr)
    base = M.mobilenet_v2(weights=M.MobileNet_V2_Weights.IMAGENET1K_V1)
    base.eval()

    wrapped = MobileNetV2Features(base)
    wrapped.eval()

    # Dummy input: standard ImageNet 224×224 RGB, batch=1.
    # Channels-first to match the original
    # ``MobileNet-v2.onnx`` input shape.
    dummy = torch.zeros(1, 3, 224, 224)

    print(
        f"Exporting to {OUTPUT_PATH.relative_to(REPO_ROOT)} "
        f"(opset 13, dynamic batch)…",
        file=sys.stderr,
    )

    # Atomic write: export to a .tmp first, then rename.
    tmp_path = OUTPUT_PATH.with_suffix(".onnx.tmp")
    try:
        torch.onnx.export(
            wrapped,
            dummy,
            str(tmp_path),
            input_names=["image_tensor"],
            output_names=["features", "class_logits"],
            opset_version=13,
            dynamic_axes={
                "image_tensor": {0: "batch"},
                "features": {0: "batch"},
                "class_logits": {0: "batch"},
            },
        )
        # ``torch.onnx.export`` may not flush to disk on
        # all torch versions; ``rename`` is the only
        # cross-platform atomic swap.
        tmp_path.replace(OUTPUT_PATH)
    except Exception:
        # Clean up the half-written file so the next run
        # does not pick up a corrupt model.
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    size_mb = OUTPUT_PATH.stat().st_size / (1024 * 1024)
    print(
        f"Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} "
        f"({size_mb:.2f} MB, 2 outputs: features[1280] + "
        f"class_logits[1000])",
        file=sys.stderr,
    )

    # Smoke-test the on-disk model with onnxruntime to
    # confirm both outputs are reachable and the shapes
    # are what ``SemanticSearchEngine`` expects.
    print("Smoke-testing with onnxruntime…", file=sys.stderr)
    import onnxruntime as ort

    session = ort.InferenceSession(
        str(OUTPUT_PATH), providers=["CPUExecutionProvider"],
    )
    outputs = {o.name: o.shape for o in session.get_outputs()}
    print(f"  outputs: {outputs}", file=sys.stderr)
    if outputs.get("features") != ["batch", 1280] and outputs.get("features") != [1, 1280]:
        raise RuntimeError(
            f"Unexpected 'features' shape: {outputs.get('features')!r}; "
            f"expected ['batch', 1280] or [1, 1280]",
        )
    if outputs.get("class_logits") != ["batch", 1000] and outputs.get("class_logits") != [1, 1000]:
        raise RuntimeError(
            f"Unexpected 'class_logits' shape: "
            f"{outputs.get('class_logits')!r}; expected "
            f"['batch', 1000] or [1, 1000]",
        )
    print("Smoke-test OK.", file=sys.stderr)
    return OUTPUT_PATH


if __name__ == "__main__":
    export()
