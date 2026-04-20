import uvicorn
import logging
from app.api.server import app
from app.settings.config import Config

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(Config.WEB_DASHBOARD_PORT) if hasattr(Config, "WEB_DASHBOARD_PORT") else 8090
    host = Config.WEB_DASHBOARD_HOST if hasattr(Config, "WEB_DASHBOARD_HOST") else "0.0.0.0"
    
    print(f"Starting SARAS Decoupled API (Phase 3) on {host}:{port}...")
    print("Frontend Clients (Next.js, Tauri, iOS) can now connect via REST and WebSockets.")
    
    uvicorn.run(app, host=host, port=port)
