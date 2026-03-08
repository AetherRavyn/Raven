import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
import yt_dlp
from ultralytics import YOLO

# =========================
# CONFIG
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_NAME = os.path.join(BASE_DIR, "yolo11n.pt")
IMG_SIZE = 640
CAM_W, CAM_H = 640, 360
TARGET_FPS = 25
FRAME_TIME = 1.0 / TARGET_FPS
GRID_COLS = 2
HOST = "0.0.0.0"
PORT = 8080
BOX_LINE_WIDTH = 1
BOX_FONT_SIZE = 0.45
STATUS_FONT_SCALE = 0.55
STATUS_FONT_THICKNESS = 1

streams = [
    ("https://www.youtube.com/watch?v=rnXIjl_Rzy4", "Cam-1"),
    ("https://www.youtube.com/watch?v=2aCKWFq_j8g", "Cam-2"),
]


def get_direct_url(youtube_url):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "best[ext=mp4][vcodec*=avc1]/best",
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
        return info["url"]


def make_grid(images, cols):
    if not images:
        return None

    h, w = images[0].shape[:2]
    rows = (len(images) + cols - 1) // cols
    total = rows * cols
    padded = images[:]

    while len(padded) < total:
        padded.append(np.zeros((h, w, 3), np.uint8))

    grid_rows = []
    for r in range(rows):
        row = np.hstack(padded[r * cols : (r + 1) * cols])
        grid_rows.append(row)

    return np.vstack(grid_rows)


class TrackerServer:
    def __init__(self):
        self.latest_jpeg = None
        self.jpeg_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.caps = []
        self.models = []
        self.stream_names = {}

    def setup_streams(self):
        print("Resolving streams...")
        direct_urls = []
        for i, (url, name) in enumerate(streams):
            try:
                direct = get_direct_url(url)
                direct_urls.append(direct)
                self.stream_names[i] = name
                print(f"  {name} OK")
            except Exception as exc:
                print(f"  {name} FAILED: {exc}")

        if not direct_urls:
            raise RuntimeError("No valid streams")

        print("Loading YOLO models...")
        # One model per stream keeps tracker state independent per camera.
        self.models = [YOLO(MODEL_NAME) for _ in direct_urls]

        for url in direct_urls:
            cap = cv2.VideoCapture(url)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.caps.append(cap)

    def tracking_loop(self):
        next_frame_time = time.time()
        print("Tracking loop started.")
        while not self.stop_event.is_set():
            frames = []

            for idx, cap in enumerate(self.caps):
                ok, frame = cap.read()
                if not ok:
                    frame = np.zeros((CAM_H, CAM_W, 3), np.uint8)
                else:
                    frame = cv2.resize(frame, (CAM_W, CAM_H))

                result = self.models[idx].track(
                    frame,
                    persist=True,
                    imgsz=IMG_SIZE,
                    tracker="bytetrack.yaml",
                    verbose=False,
                )[0]
                frame = result.plot(
                    line_width=BOX_LINE_WIDTH,
                    font_size=BOX_FONT_SIZE,
                )
                tracks = len(result.boxes.id) if result.boxes.id is not None else 0
                name = self.stream_names.get(idx, f"Cam-{idx + 1}")
                cv2.putText(
                    frame,
                    f"{name} | Tracks: {tracks}",
                    (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    STATUS_FONT_SCALE,
                    (0, 255, 0),
                    STATUS_FONT_THICKNESS,
                )
                frames.append(frame)

            grid = make_grid(frames, GRID_COLS)
            if grid is not None:
                ok, encoded = cv2.imencode(
                    ".jpg", grid, [int(cv2.IMWRITE_JPEG_QUALITY), 80]
                )
                if ok:
                    with self.jpeg_lock:
                        self.latest_jpeg = encoded.tobytes()

            next_frame_time += FRAME_TIME
            sleep_time = next_frame_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                next_frame_time = time.time()

        print("Tracking loop stopped.")

    def get_latest_jpeg(self):
        with self.jpeg_lock:
            return self.latest_jpeg

    def cleanup(self):
        self.stop_event.set()
        for cap in self.caps:
            cap.release()
        print("Cleanup complete.")


tracker = TrackerServer()


class CCTVHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self._serve_index()
            return
        if self.path == "/video_feed":
            self._serve_video_feed()
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not Found")

    def _serve_index(self):
        html = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CCTV Tracker</title>
  <style>
    body { margin: 0; background: #0f172a; color: #e2e8f0; font-family: sans-serif; }
    .wrap { max-width: 1400px; margin: 24px auto; padding: 0 16px; }
    h1 { font-size: 20px; margin: 0 0 12px; }
    .feed { border: 1px solid #334155; border-radius: 8px; overflow: hidden; background: #020617; }
    img { width: 100%; display: block; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Live CCTV Tracking</h1>
    <div class="feed">
      <img src="/video_feed" alt="Live tracking feed">
    </div>
  </div>
</body>
</html>"""
        payload = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _serve_video_feed(self):
        self.send_response(200)
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        try:
            while not tracker.stop_event.is_set():
                frame = tracker.get_latest_jpeg()
                if frame is None:
                    time.sleep(0.02)
                    continue

                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(
                    f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii")
                )
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(FRAME_TIME)
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, _format, *_args):
        return


def main():
    tracker.setup_streams()
    worker = threading.Thread(target=tracker.tracking_loop, daemon=True)
    worker.start()

    server = ThreadingHTTPServer((HOST, PORT), CCTVHandler)
    print(f"Server running at http://{HOST}:{PORT}")
    print("Open in browser. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        tracker.cleanup()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
