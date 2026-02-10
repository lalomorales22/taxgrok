"""Minimal xAI REST client used by phase 2 pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import uuid
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from . import __version__
from .constants import DEFAULT_TIMEOUT_SECONDS, XAI_BASE_URL


class XAIClientError(RuntimeError):
    """Raised on xAI HTTP or payload handling errors."""


@dataclass(frozen=True)
class UploadedRemoteFile:
    """Uploaded file metadata returned by xAI."""

    file_id: str
    filename: str
    bytes_uploaded: int


@dataclass(frozen=True)
class GenerationResult:
    """Text generation output and source metadata."""

    text: str
    citations: list[dict[str, Any]]
    sources_used: int | None
    raw_response: dict[str, Any]
    api_path: str


class XAIClient:
    """Small REST wrapper for files + chat completion requests."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = XAI_BASE_URL,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "User-Agent": f"taxgrok/{__version__}",
        }

    def _request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        body: bytes | None = None
        headers = self._auth_headers()
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib_request.Request(url=url, data=body, headers=headers, method=method.upper())
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise XAIClientError(f"{method.upper()} {path} failed ({exc.code}): {detail}") from exc
        except urllib_error.URLError as exc:
            raise XAIClientError(f"{method.upper()} {path} network error: {exc}") from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise XAIClientError(f"{method.upper()} {path} returned non-JSON response.") from exc

    def _upload_multipart(
        self,
        *,
        path: str,
        file_path: Path,
        purpose: str | None,
    ) -> dict[str, Any]:
        file_bytes = file_path.read_bytes()
        boundary = uuid.uuid4().hex
        payload = self._build_multipart_payload(
            boundary=boundary,
            purpose=purpose,
            filename=file_path.name,
            file_bytes=file_bytes,
        )

        url = f"{self.base_url}{path}"
        headers = self._auth_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        req = urllib_request.Request(url=url, data=payload, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise XAIClientError(f"POST {path} failed ({exc.code}): {detail}") from exc
        except urllib_error.URLError as exc:
            raise XAIClientError(f"POST {path} network error: {exc}") from exc

        try:
            return json.loads(raw) if raw else {}
        except json.JSONDecodeError as exc:
            raise XAIClientError(f"POST {path} returned non-JSON response.") from exc

    @staticmethod
    def _build_multipart_payload(
        *,
        boundary: str,
        purpose: str | None,
        filename: str,
        file_bytes: bytes,
    ) -> bytes:
        boundary_bytes = boundary.encode("utf-8")
        lines: list[bytes] = []

        def add_line(value: bytes) -> None:
            lines.append(value)

        if purpose:
            add_line(b"--" + boundary_bytes)
            add_line(b'Content-Disposition: form-data; name="purpose"')
            add_line(b"")
            add_line(purpose.encode("utf-8"))

        add_line(b"--" + boundary_bytes)
        add_line(
            f'Content-Disposition: form-data; name="file"; filename="{filename}"'.encode("utf-8")
        )
        add_line(b"Content-Type: application/octet-stream")
        add_line(b"")
        add_line(file_bytes)

        add_line(b"--" + boundary_bytes + b"--")
        add_line(b"")
        return b"\r\n".join(lines)

    def upload_file(self, file_path: Path, *, purpose: str = "assistants") -> UploadedRemoteFile:
        """Upload one local file to xAI Files API."""
        try:
            response = self._upload_multipart(path="/v1/files", file_path=file_path, purpose=purpose)
        except XAIClientError:
            response = self._upload_multipart(path="/v1/files", file_path=file_path, purpose=None)
        file_id = response.get("id")
        if not isinstance(file_id, str) or not file_id:
            raise XAIClientError(f"Unexpected file upload response (missing id): {response}")
        return UploadedRemoteFile(
            file_id=file_id,
            filename=file_path.name,
            bytes_uploaded=file_path.stat().st_size,
        )

    def delete_file(self, file_id: str) -> None:
        """Delete remote file by id."""
        self._request_json(method="DELETE", path=f"/v1/files/{file_id}", payload=None)

    def _extract_message_text(self, raw_response: dict[str, Any]) -> str:
        choices = raw_response.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
            return "\n".join(part.strip() for part in parts if part.strip()).strip()
        return ""

    @staticmethod
    def _extract_responses_text(raw_response: dict[str, Any]) -> str:
        output_text = raw_response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        outputs = raw_response.get("output")
        if not isinstance(outputs, list):
            return ""

        parts: list[str] = []
        for item in outputs:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, str):
                    if block.strip():
                        parts.append(block.strip())
                    continue
                if not isinstance(block, dict):
                    continue
                for key in ("text", "output_text", "content"):
                    candidate = block.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        parts.append(candidate.strip())
                        break
        return "\n".join(parts).strip()

    @staticmethod
    def _extract_citations(raw_response: dict[str, Any]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        top_level = raw_response.get("citations")
        if isinstance(top_level, list):
            citations.extend([item for item in top_level if isinstance(item, dict)])

        choices = raw_response.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message", {})
            for key in ("citations", "annotations", "sources"):
                value = message.get(key)
                if isinstance(value, list):
                    citations.extend([item for item in value if isinstance(item, dict)])

        outputs = raw_response.get("output")
        if isinstance(outputs, list):
            for item in outputs:
                if not isinstance(item, dict):
                    continue
                for key in ("citations", "annotations", "sources"):
                    value = item.get(key)
                    if isinstance(value, list):
                        citations.extend([entry for entry in value if isinstance(entry, dict)])
                content = item.get("content")
                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        for key in ("citations", "annotations", "sources"):
                            value = block.get(key)
                            if isinstance(value, list):
                                citations.extend([entry for entry in value if isinstance(entry, dict)])
        return citations

    @staticmethod
    def _extract_sources_used(raw_response: dict[str, Any]) -> int | None:
        usage = raw_response.get("usage", {})
        if isinstance(usage, dict):
            for key in ("num_sources_used", "sources_used"):
                value = usage.get(key)
                if isinstance(value, int):
                    return value
        return None

    def chat_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        """Run one chat completion request with optional file attachments."""
        user_content: str | list[dict[str, Any]]
        if attached_file_ids:
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
            for file_id in attached_file_ids:
                content_parts.append({"type": "file", "file": {"file_id": file_id}})
            user_content = content_parts
        else:
            # Keep text-only requests simple for maximum OpenAI-compatible endpoint support.
            user_content = user_prompt

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }

        raw_response = self._request_json(method="POST", path="/v1/chat/completions", payload=payload)
        return GenerationResult(
            text=self._extract_message_text(raw_response),
            citations=self._extract_citations(raw_response),
            sources_used=self._extract_sources_used(raw_response),
            raw_response=raw_response,
            api_path="/v1/chat/completions",
        )

    def responses_completion(
        self,
        *,
        model: str,
        system_prompt: str,
        user_prompt: str,
        attached_file_ids: list[str] | None = None,
        temperature: float = 0.1,
    ) -> GenerationResult:
        """Run one request via the Responses API with attached files."""
        user_content: list[dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
        for file_id in attached_file_ids or []:
            user_content.append({"type": "input_file", "file_id": file_id})

        payload: dict[str, Any] = {
            "model": model,
            "input": [
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }
        raw_response = self._request_json(method="POST", path="/v1/responses", payload=payload)
        text = self._extract_responses_text(raw_response)
        return GenerationResult(
            text=text,
            citations=self._extract_citations(raw_response),
            sources_used=self._extract_sources_used(raw_response),
            raw_response=raw_response,
            api_path="/v1/responses",
        )

    def analyze_png(self, *, png_path: Path, model: str) -> str:
        """Use xAI image understanding to convert one PNG into normalized notes."""
        uploaded = self.upload_file(png_path)
        try:
            result = self.chat_completion(
                model=model,
                system_prompt=(
                    "You extract tax-relevant details from screenshots of tax documents. "
                    "Be factual. If text is unreadable, say what is unreadable."
                ),
                user_prompt=(
                    "Analyze the attached PNG document screenshot. Return concise markdown with sections:\n"
                    "1) Detected document type\n"
                    "2) Key tax fields and values\n"
                    "3) Missing/unclear fields\n"
                    "4) Follow-up questions for taxpayer"
                ),
                attached_file_ids=[uploaded.file_id],
                temperature=0.0,
            )
            return result.text.strip()
        finally:
            try:
                self.delete_file(uploaded.file_id)
            except Exception:
                # Cleanup failures are non-fatal for image normalization.
                pass

    def extract_pdf_text(self, *, pdf_path: Path, model: str) -> str:
        """Attempt OCR/text extraction on a PDF via xAI file-aware chat."""
        uploaded = self.upload_file(pdf_path)
        try:
            result = self.chat_completion(
                model=model,
                system_prompt=(
                    "You extract text from U.S. tax PDF documents. "
                    "If the PDF is image-based, apply OCR. "
                    "Return plain text only, preserving key field labels and values when possible."
                ),
                user_prompt=(
                    "Extract the attached PDF into plain text for downstream parsing. "
                    "Do not summarize. "
                    "If a section is unreadable, include a short line noting the unreadable section."
                ),
                attached_file_ids=[uploaded.file_id],
                temperature=0.0,
            )
            return result.text.strip()
        finally:
            try:
                self.delete_file(uploaded.file_id)
            except Exception:
                # Cleanup failures are non-fatal for OCR fallback.
                pass
