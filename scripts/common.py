"""Small helpers shared by the scripts: times, numbers, the weekly window and
owner-only writes."""

import json
import math
import os
import tempfile
from datetime import datetime


def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo is not None else None
        except ValueError:
            return None
    return None


def number(value):
    return epoch(value) if not isinstance(value, str) else None


def weekly(observation):
    return next((w for w in observation["windows"] if w["durationMinutes"] == 10080), None)


def write_private(path, state):
    handle, name = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        with os.fdopen(handle, "w") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
