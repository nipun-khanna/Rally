"""Content-free timing output for the inbound reply path."""

import logging


logger = logging.getLogger("rally.latency")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
logger.propagate = False


def record_latency(phase: str, seconds: float):
    logger.info("phase=%s seconds=%.3f", phase, seconds)
