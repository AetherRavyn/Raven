import logging 
from pathlib import Path 



def setup_logging():
    """Configure logging."""
    log_dir = Path(CONFIG["storage"]["clips_dir"]).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    log_level = getattr(logging, CONFIG["logging"]["level"], logging.INFO)

    from logging.handlers import RotatingFileHandler

    file_handler = RotatingFileHandler(
        log_dir / "anomaly_handler.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger("AnomalyHandler")


logger = setup_logging()