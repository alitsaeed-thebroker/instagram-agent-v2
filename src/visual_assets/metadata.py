"""Recursive conversion of image/EXIF metadata into JSON-safe values."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time
import math
from typing import Any

try:
    from PIL.TiffImagePlugin import IFDRational
except ImportError:  # pragma: no cover - Pillow is a declared dependency.
    IFDRational = ()  # type: ignore[assignment,misc]


def json_safe_metadata(value: Any) -> Any:
    """Recursively preserve metadata while converting unsupported JSON types."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if IFDRational and isinstance(value, IFDRational):
        try:
            converted = float(value)
            return converted if math.isfinite(converted) else str(value)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Mapping) or hasattr(value, "items"):
        try:
            items = value.items()
        except Exception:
            return str(value)
        return {str(json_safe_metadata(key)): json_safe_metadata(item) for key, item in items}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_safe_metadata(item) for item in value]
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)
