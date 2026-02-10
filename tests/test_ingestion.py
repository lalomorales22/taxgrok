from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from taxgrok.ingestion import build_image_document, chunk_text, extract_local_document, write_artifact


class IngestionTests(unittest.TestCase):
    def test_chunk_text_generates_stable_ids(self) -> None:
        text = "A" * 2600
        chunks = chunk_text(text, source_key="source-key", chunk_size=1000, overlap=100)
        self.assertEqual(len(chunks), 3)
        self.assertEqual(chunks[0].chunk_id, "source-key-chunk-001")
        self.assertEqual(chunks[1].chunk_id, "source-key-chunk-002")

    def test_extract_local_document_from_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "notes.txt"
            path.write_text("line one\nline two\n", encoding="utf-8")
            doc = extract_local_document(path)
        self.assertEqual(doc.source_kind, "txt")
        self.assertIn("line one", doc.text)
        self.assertGreaterEqual(len(doc.chunks), 1)

    def test_build_image_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "w2.png"
            path.write_bytes(b"\x89PNG\r\n\x1a\n")
            doc = build_image_document(path, "Detected wages: 100000")
        self.assertEqual(doc.source_kind, "png")
        self.assertEqual(len(doc.chunks), 1)

    def test_write_artifact_contains_chunk_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            source_path = Path(tmp_dir) / "return.md"
            source_path.write_text("# return", encoding="utf-8")
            doc = extract_local_document(source_path)
            artifact = write_artifact(doc, Path(tmp_dir), 1)
            content = artifact.read_text(encoding="utf-8")
        self.assertIn("## Chunk index", content)
        self.assertIn(doc.chunks[0].chunk_id, content)
        self.assertIn("- Source file: `return.md`", content)
        self.assertIn("- Source ref:", content)
        self.assertNotIn("Source path", content)


if __name__ == "__main__":
    unittest.main()
