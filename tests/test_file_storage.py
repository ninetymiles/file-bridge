"""Unit tests for file storage, naming conventions, and sanitization."""

import os
from datetime import datetime
import pytest
from lib.file_storage import (
    sanitize_sender_name,
    sanitize_extension,
    generate_saved_filename,
    save_file,
)


def test_sanitize_sender_name():
    assert sanitize_sender_name("Alice") == "Alice"
    assert sanitize_sender_name("Bob/Admin") == "BobAdmin"
    assert sanitize_sender_name("User: [Test]") == "User Test"
    assert sanitize_sender_name("../../evil") == "evil"
    assert sanitize_sender_name("") == "unknown"
    assert sanitize_sender_name(None) == "unknown"


def test_sanitize_extension():
    assert sanitize_extension("photo.png") == ".png"
    assert sanitize_extension("archive.tar.gz") == ".gz"
    assert sanitize_extension("path/to/file.PDF") == ".PDF"
    # Path traversal attempt
    assert sanitize_extension("../../etc/passwd") == ""
    assert sanitize_extension("../../etc/passwd", default_ext=".bin") == ".bin"
    # Missing extension with default
    assert sanitize_extension("noext", default_ext=".png") == ".png"


def test_generate_saved_filename():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)
    filename = generate_saved_filename(
        sender="Alice",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "[Alice]_20260924153045_123.pdf"


def test_save_file_directory_structure_and_collision(tmp_path):
    output_dir = tmp_path / "storage"
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)

    # Create dummy temp file
    temp_file1 = tmp_path / "temp1.tmp"
    temp_file1.write_text("content 1")

    saved_path1 = save_file(
        temp_path=str(temp_file1),
        output_dir=str(output_dir),
        sender="Bob",
        original_filename="data.txt",
        timestamp=fixed_time,
    )

    expected_date_dir = output_dir / "2026-09-24"
    assert os.path.exists(expected_date_dir)
    assert saved_path1 == str(expected_date_dir / "[Bob]_20260924153045_123.txt")
    assert os.path.exists(saved_path1)

    # Collision check: save another file with same timestamp and sender
    temp_file2 = tmp_path / "temp2.tmp"
    temp_file2.write_text("content 2")

    saved_path2 = save_file(
        temp_path=str(temp_file2),
        output_dir=str(output_dir),
        sender="Bob",
        original_filename="data.txt",
        timestamp=fixed_time,
    )

    assert saved_path2 != saved_path1
    assert os.path.exists(saved_path2)
    assert "_1.txt" in saved_path2
