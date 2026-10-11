from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_bytes(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        fd_dir = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd_dir)
        finally:
            os.close(fd_dir)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def atomic_json(path, obj):
    atomic_bytes(path, (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode())


def read_json(path):
    return json.loads(Path(path).read_text())


def disk_bytes(path):
    return sum(p.stat().st_size for p in Path(path).rglob("*") if p.is_file())


DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config.json"


def load_config(path=DEFAULT_CONFIG):
    cfg = read_json(path)
    cfg["output"] = str((Path(path).resolve().parent / cfg["output"]).resolve())
    if (cfg["fps"], cfg["duration"]) != (30, 3):
        raise ValueError("Experiments require exactly 90 frames at 30 FPS (3 seconds)")
    for key in ("width", "height", "rounds", "candidates", "max_runtime_seconds",
                "render_timeout_seconds", "max_disk_mb", "threads", "regression_every",
                "visual_evaluator_timeout_seconds"):
        if type(cfg[key]) is not int or cfg[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if cfg["width"] % 2 or cfg["height"] % 2 or cfg["width"] > 3840 or cfg["height"] > 2160:
        raise ValueError("Use even dimensions no larger than 3840 x 2160")
    if cfg["candidates"] > 4 or cfg["threads"] > 8 or not 0 <= cfg["retries"] <= 3:
        raise ValueError("Initial conservative limits: <=4 candidates, <=8 threads, <=3 retries")
    if cfg["regression_every"] > 10:
        raise ValueError("A broader regression must run at least every ten rounds")
    if not 0 < cfg["minimum_relative_gain"] < 1:
        raise ValueError("minimum_relative_gain must be between 0 and 1")
    weights = cfg["evaluation_weights"]
    expected = {"motion_smoothness", "timing_easing", "visual_hierarchy", "composition_spacing",
                "creativity_originality", "transitions", "professional_polish"}
    if set(weights) != expected or any(v < 0 for v in weights.values()) or abs(sum(weights.values()) - 1) > 1e-6:
        raise ValueError("Evaluation weights must contain the seven criteria and sum to one")
    cmd = cfg.get("visual_evaluator_command")
    if cmd is not None and (not isinstance(cmd, list) or not cmd or not all(isinstance(s, str) for s in cmd)):
        raise ValueError("Evaluator must be a command argument list; no shell execution")
    return cfg
