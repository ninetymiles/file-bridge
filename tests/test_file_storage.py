"""Unit tests for file storage, naming conventions, and sanitization."""

import os
from datetime import datetime
import pytest
from app.utils.file_storage import (
    sanitize_sender_id,
    sanitize_extension,
    generate_saved_filename,
    save_file,
)


def test_sanitize_sender_id():
    assert sanitize_sender_id("Alice") == "Alice"
    assert sanitize_sender_id("Bob/Admin") == "BobAdmin"
    assert sanitize_sender_id("User: [Test]") == "User Test"
    assert sanitize_sender_id("../../evil") == "evil"
    assert sanitize_sender_id("") == ""
    assert sanitize_sender_id(None) == ""


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
        sender_staff_id="staff-001",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "20260924_153045_-001.pdf"


def test_generate_saved_filename_truncates_to_last_four_chars():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)

    long_id = generate_saved_filename(
        sender_staff_id="1234567890123456",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert long_id == "20260924_153045_3456.pdf"

    short_id = generate_saved_filename(
        sender_staff_id="manager4521",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert short_id == "20260924_153045_4521.pdf"


def test_generate_saved_filename_keeps_ids_shorter_than_four_chars():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)
    filename = generate_saved_filename(
        sender_staff_id="abc",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "20260924_153045_abc.pdf"


def test_generate_saved_filename_truncates_after_sanitizing():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)
    # Trailing space is stripped before slicing, so the suffix keeps four
    # real characters instead of fewer plus a trailing blank.
    filename = generate_saved_filename(
        sender_staff_id="abc def ",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "20260924_153045_ def.pdf"


def test_generate_saved_filename_without_sender_id():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)
    filename = generate_saved_filename(
        sender_staff_id=None,
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "20260924_153045.pdf"


def test_generate_saved_filename_with_empty_sender_id():
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)
    filename = generate_saved_filename(
        sender_staff_id="   ",
        original_filename="document.pdf",
        timestamp=fixed_time,
    )
    assert filename == "20260924_153045.pdf"


def test_save_file_directory_structure_and_collision(tmp_path):
    output_dir = tmp_path / "storage"
    fixed_time = datetime(2026, 9, 24, 15, 30, 45, 123456)

    # Create dummy temp file
    temp_file1 = tmp_path / "temp1.tmp"
    temp_file1.write_text("content 1")

    saved_path1 = save_file(
        temp_path=str(temp_file1),
        output_dir=str(output_dir),
        sender_staff_id="staff-001",
        original_filename="data.txt",
        timestamp=fixed_time,
    )

    assert saved_path1 == str(output_dir / "20260924_153045_-001.txt")
    assert os.path.exists(saved_path1)

    # Collision check: save another file with same timestamp and sender
    temp_file2 = tmp_path / "temp2.tmp"
    temp_file2.write_text("content 2")

    saved_path2 = save_file(
        temp_path=str(temp_file2),
        output_dir=str(output_dir),
        sender_staff_id="staff-001",
        original_filename="data.txt",
        timestamp=fixed_time,
    )

    assert saved_path2 != saved_path1
    assert os.path.exists(saved_path2)
    assert "_1.txt" in saved_path2
