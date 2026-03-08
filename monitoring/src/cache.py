import time
from collections import OrderedDict
from typing import Any, Dict, Optional, Tuple

class TTLCache:
    """
    A Least-Recently-Used (LRU) cache with Time-To-Live (TTL) expiration.
    Used on the Edge to prevent redundant ML inferences on static objects or known faces.
    """
    def __init__(self, maxsize: int = 1000, default_ttl: float = 60.0):
        self.cache: OrderedDict[str, Tuple[float, Any]] = OrderedDict()
        self.maxsize = maxsize
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key not in self.cache:
            return None
            
        expiry, value = self.cache[key]
        if time.time() > expiry:
            # Expired
            self.pop(key)
            return None
            
        # Move to end (most recently used)
        self.cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None):
        if ttl is None:
            ttl = self.default_ttl
            
        if key in self.cache:
            self.cache.move_to_end(key)
            
        self.cache[key] = (time.time() + ttl, value)
        
        if len(self.cache) > self.maxsize:
            # Pop least recently used (first item)
            self.cache.popitem(last=False)

    def pop(self, key: str) -> Optional[Any]:
        if key in self.cache:
            _, value = self.cache.pop(key)
            return value
        return None

    def clear(self):
        self.cache.clear()

class SmartCacheSystem:
    """
    Edge-optimized caching layer tailored for computer vision results.
    """
    def __init__(self):
        # Cache object detections (e.g., bounding boxes for static objects) 
        # Key: camera_id_object_id
        self.detections = TTLCache(maxsize=5000, default_ttl=5.0)
        
        # Cache face embeddings (e.g., ArcFace vectors)
        # Key: face_crop_hash
        self.embeddings = TTLCache(maxsize=1000, default_ttl=30.0)
        
        # Cache identity matches (prevent hitting DB constantly for same track)
        # Key: track_id
        self.identities = TTLCache(maxsize=500, default_ttl=10.0)

    def get_cached_detection(self, camera_id: str, object_id: str) -> Optional[Dict]:
        """Skip YOLO if the object hasn't moved significantly."""
        return self.detections.get(f"{camera_id}_{object_id}")
        
    def set_cached_detection(self, camera_id: str, object_id: str, bbox: list, ttl: float = 2.0):
        self.detections.set(f"{camera_id}_{object_id}", bbox, ttl=ttl)

    def get_cached_embedding(self, face_hash: str) -> Optional[Any]:
        """Return pre-computed 512d face vector."""
        return self.embeddings.get(face_hash)
        
    def set_cached_embedding(self, face_hash: str, embedding: Any):
        self.embeddings.set(face_hash, embedding, ttl=60.0) # Embeddings are valid slightly longer

    def get_cached_identity(self, track_id: int) -> Optional[Dict]:
        """Return identity mapping for a tracking ID."""
        return self.identities.get(str(track_id))
        
    def set_cached_identity(self, track_id: int, identity_data: Dict, ttl: float = 10.0):
        self.identities.set(str(track_id), identity_data, ttl=ttl)

# Global singleton for edge use
edge_cache = SmartCacheSystem()

if __name__ == "__main__":
    # Test script output
    print("Testing Smart Cache...")
    cache = TTLCache(maxsize=2, default_ttl=1.0)
    cache.set("a", 1)
    cache.set("b", 2)
    print("A:", cache.get("a")) # 1
    cache.set("c", 3) # b pushed out
    print("B:", cache.get("b")) # None
    print("Sleeping 1.5s...")
    time.sleep(1.5)
    print("A (expired):", cache.get("a")) # None
