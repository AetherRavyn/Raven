"""
GPU-accelerated array operations via CuPy (CUDA).
Falls back to numpy transparently if CuPy is unavailable.

Usage:
    from monitoring.src.gpu import xp, to_gpu, to_cpu, gpu_cosine_similarity, gpu_iou_matrix
"""

import logging
import numpy as np

logger = logging.getLogger(__name__)

# ── CuPy import with graceful fallback ────────────────────────────────────────
try:
    import cupy as cp
    # Verify CUDA is actually accessible
    cp.cuda.Device(0).compute_capability
    GPU_AVAILABLE = True
    xp = cp  # Use CuPy as the array library
    logger.info("CuPy GPU acceleration ENABLED  (device: %s)", cp.cuda.Device(0))
except Exception:
    GPU_AVAILABLE = False
    xp = np  # Fallback to numpy
    cp = None
    logger.info("CuPy not available — using numpy (CPU)")


def to_gpu(arr: np.ndarray):
    """Move a numpy array to GPU. No-op if CuPy unavailable."""
    if GPU_AVAILABLE:
        return cp.asarray(arr)
    return arr


def to_cpu(arr) -> np.ndarray:
    """Move a CuPy array to CPU numpy. No-op if already numpy."""
    if GPU_AVAILABLE and hasattr(arr, 'get'):
        return arr.get()
    return np.asarray(arr)


# ══════════════════════════════════════════════════════════════════════════════
# GPU-ACCELERATED OPERATIONS
# ══════════════════════════════════════════════════════════════════════════════

def gpu_cosine_similarity(query: np.ndarray, database: np.ndarray) -> np.ndarray:
    """
    Compute cosine similarity between a query embedding and a database of embeddings.
    Runs on GPU if available, else CPU.

    Args:
        query: (D,) embedding vector
        database: (N, D) matrix of N embeddings

    Returns:
        (N,) array of cosine similarities
    """
    if database.shape[0] == 0:
        return np.array([], dtype=np.float32)

    q = to_gpu(query.astype(np.float32))
    db = to_gpu(database.astype(np.float32))

    # Normalize
    q_norm = q / (xp.linalg.norm(q) + 1e-8)
    db_norms = xp.linalg.norm(db, axis=1, keepdims=True) + 1e-8
    db_normed = db / db_norms

    # Dot product = cosine similarity (both unit vectors)
    sims = db_normed @ q_norm

    return to_cpu(sims)


def gpu_iou_matrix(bboxes_a: np.ndarray, bboxes_b: np.ndarray) -> np.ndarray:
    """
    Compute the IOU matrix between two sets of bounding boxes on GPU.
    Each bbox is [x1, y1, x2, y2].

    Args:
        bboxes_a: (N, 4) array
        bboxes_b: (M, 4) array

    Returns:
        (N, M) IOU matrix
    """
    if bboxes_a.shape[0] == 0 or bboxes_b.shape[0] == 0:
        return np.zeros((bboxes_a.shape[0], bboxes_b.shape[0]), dtype=np.float32)

    a = to_gpu(bboxes_a.astype(np.float32))
    b = to_gpu(bboxes_b.astype(np.float32))

    # Intersection
    x1 = xp.maximum(a[:, 0:1], b[:, 0:1].T)  # (N, M)
    y1 = xp.maximum(a[:, 1:2], b[:, 1:2].T)
    x2 = xp.minimum(a[:, 2:3], b[:, 2:3].T)
    y2 = xp.minimum(a[:, 3:4], b[:, 3:4].T)

    inter = xp.maximum(0, x2 - x1) * xp.maximum(0, y2 - y1)

    # Areas
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])  # (N,)
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])  # (M,)

    union = area_a[:, None] + area_b[None, :] - inter
    iou = inter / (union + 1e-6)

    return to_cpu(iou)


def gpu_distance_matrix(points_a: np.ndarray, points_b: np.ndarray) -> np.ndarray:
    """
    Euclidean distance matrix between two sets of 2D points.

    Args:
        points_a: (N, 2)
        points_b: (M, 2)

    Returns:
        (N, M) distance matrix
    """
    if points_a.shape[0] == 0 or points_b.shape[0] == 0:
        return np.zeros((points_a.shape[0], points_b.shape[0]), dtype=np.float32)

    a = to_gpu(points_a.astype(np.float32))
    b = to_gpu(points_b.astype(np.float32))

    # ||a - b||^2 = ||a||^2 + ||b||^2 - 2 * a . b
    a_sq = xp.sum(a ** 2, axis=1, keepdims=True)
    b_sq = xp.sum(b ** 2, axis=1, keepdims=True)
    dist_sq = a_sq + b_sq.T - 2 * (a @ b.T)
    dist = xp.sqrt(xp.maximum(dist_sq, 0))

    return to_cpu(dist)


def gpu_rgb_to_bgr(img_arr: np.ndarray) -> np.ndarray:
    """RGB→BGR conversion on GPU. Returns CPU numpy array."""
    if GPU_AVAILABLE:
        g = cp.asarray(img_arr)
        bgr = g[:, :, ::-1]
        return bgr.get()
    return img_arr[:, :, ::-1].copy()


def gpu_bgr_to_rgb(img_arr: np.ndarray) -> np.ndarray:
    """BGR→RGB conversion on GPU. Returns CPU numpy array."""
    return gpu_rgb_to_bgr(img_arr)  # Same operation (reverse channels)
