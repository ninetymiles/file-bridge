"""File storage utilities for sanitization, directory structure, and persisting downloaded files."""

import os
import re
import shutil
from datetime import datetime
from typing import Optional


ACTIVITY_FILENAME = ".activity"


def write_activity_file(output_dir: str) -> None:
    """Overwrite OUTPUT_DIR/.activity with the current timestamp, then fsync.

    Storage-warmup probe: a real write reaches the storage server and forces
    a sleeping disk to wake, unlike existence checks which may hit client
    caches and falsely succeed on a cold volume.
    """
    path = os.path.join(output_dir, ACTIVITY_FILENAME)
    with open(path, "w") as f:
        f.write(datetime.now().isoformat())
        f.flush()
        os.fsync(f.fileno())


def sanitize_sender_name(sender: Optional[str]) -> str:
    """Sanitize sender name for safe filename usage."""
    if not sender:
        return "unknown"
    # Remove characters invalid in filenames or dangerous for path traversal
    cleaned = re.sub(r'[\\/*?:"<>|\[\]\x00-\x1f]', '', sender).strip()
    # Strip leading/trailing dots or spaces
    cleaned = cleaned.strip('. ')
    return cleaned if cleaned else "unknown"


def sanitize_extension(original_filename: Optional[str], default_ext: str = "") -> str:
    """Extract and sanitize file extension from original filename."""
    if not original_filename:
        ext = default_ext
    else:
        # Strip path traversal and get extension
        base = os.path.basename(original_filename)
        _, ext = os.path.splitext(base)
        if not ext and default_ext:
            ext = default_ext

    if not ext:
        return ""

    if not ext.startswith("."):
        ext = "." + ext

    # Only allow alphanumeric extensions
    clean_ext = re.sub(r'[^a-zA-Z0-9.]', '', ext)
    return clean_ext


def generate_saved_filename(
    sender: Optional[str],
    original_filename: Optional[str],
    timestamp: Optional[datetime] = None,
    default_ext: str = "",
) -> str:
    """Generate safe filename in format '[sender]_timestamp.ext'."""
    clean_sender = sanitize_sender_name(sender)
    clean_ext = sanitize_extension(original_filename, default_ext=default_ext)

    ts = timestamp or datetime.now()
    # Format timestamp with milliseconds: YYYYMMDD_HHMMSS_fff
    time_str = ts.strftime("%Y%m%d_%H%M%S_%f")[:19]

    return f"[{clean_sender}]_{time_str}{clean_ext}"


def save_file(
    temp_path: str,
    output_dir: str,
    sender: Optional[str],
    original_filename: Optional[str],
    timestamp: Optional[datetime] = None,
    default_ext: str = "",
) -> str:
    """Move temporary file to target date directory with formatted filename."""
    ts = timestamp or datetime.now()
    date_dir = ts.strftime("%Y-%m-%d")
    target_dir = os.path.join(output_dir, date_dir)
    os.makedirs(target_dir, exist_ok=True)

    filename = generate_saved_filename(sender, original_filename, timestamp=ts, default_ext=default_ext)
    target_path = os.path.join(target_dir, filename)

    # Collision prevention if exact millisecond collision occurs
    counter = 1
    base_name, ext = os.path.splitext(target_path)
    while os.path.exists(target_path):
        target_path = f"{base_name}_{counter}{ext}"
        counter += 1

    shutil.move(temp_path, target_path)
    return os.path.abspath(target_path)
