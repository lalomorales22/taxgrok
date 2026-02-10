from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from taxgrok.files import DocumentQueue


class DocumentQueueTests(unittest.TestCase):
    def test_add_file_rejects_unsupported_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = Path(tmp_dir) / "photo.jpg"
            image_path.write_text("not supported", encoding="utf-8")

            queue = DocumentQueue()
            result = queue.add_file(image_path)

        self.assertFalse(result.added)
        self.assertIn("unsupported extension", result.reason)

    def test_add_folder_adds_supported_files_recursively(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "notes.txt").write_text("hello", encoding="utf-8")
            (root / "readme.md").write_text("# md", encoding="utf-8")
            (root / "return.pdf").write_text("pdf-text", encoding="utf-8")
            (root / "w2.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (root / "skip.jpg").write_text("skip", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "nested.txt").write_text("nested", encoding="utf-8")

            queue = DocumentQueue()
            result = queue.add_folder(root)

        self.assertEqual(len(result.added), 5)
        self.assertEqual(len(queue.items), 5)
        self.assertTrue(any("unsupported extension" in item.reason for item in result.skipped))

    def test_duplicate_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_path = Path(tmp_dir) / "notes.txt"
            file_path.write_text("duplicate", encoding="utf-8")

            queue = DocumentQueue()
            first = queue.add_file(file_path)
            second = queue.add_file(file_path)

        self.assertTrue(first.added)
        self.assertFalse(second.added)
        self.assertEqual(second.reason, "already queued")


if __name__ == "__main__":
    unittest.main()
