import logging
from logging.handlers import RotatingFileHandler

def setup_logging(log_to_file: bool, log_file_path: str):
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    if log_to_file:
        fh = RotatingFileHandler(log_file_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)