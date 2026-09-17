"""Bounded media intelligence built on the existing MediaService and IntelGraph."""
from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from core.errors import ResourceError


class MediaIntelService:
    """Turn authorized local media into content-addressed, evidence-backed observations."""

    MAX_TEXT = 64 * 1024
    MAX_FRAME_BYTES = 2 * 1024 * 1024
    MAX_ROWS = 100
    PHASH_DISTANCE = 8

    def __init__(self, media, intelgraph, ai=None):
        self.media = media
        self.intelgraph = intelgraph
        self.ai = ai
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        await self.intelgraph.start()
        await self.intelgraph.add_source(
            source_id="media-intel-local",
            source_family="MEDIA",
            provider="local-media",
            source_type="LOCAL_ANALYSIS",
            lineage_class="LOCAL_DERIVED",
            lineage_confidence=1.0,
        )
        self._started = True

    async def close(self) -> None:
        self._started = False

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _hamming(left: str, right: str) -> int:
        try:
            return (int(left, 16) ^ int(right, 16)).bit_count()
        except ValueError:
            return 64

    async def _entity_observation(self, entity_type: str, value: str, *, matched_field: str, match_type: str, provenance: dict[str, Any], confidence: float = 1.0) -> str:
        entity_id = await self.intelgraph.add_entity(entity_type=entity_type, canonical_value=value, display_value=value)
        await self.intelgraph.add_observation(
            entity_id=entity_id,
            source_id="media-intel-local",
            source_family="MEDIA",
            matched_field=matched_field,
            match_type=match_type,
            evidence_state="OBSERVED",
            confidence=confidence,
            provenance=provenance,
        )
        return entity_id

    async def _phash(self, source: Path, workspace) -> str | None:
        if not shutil.which("ffmpeg"):
            return None
        raw = workspace.resolve("phash.raw")
        result = await self.media.run_isolated(
            [
                "ffmpeg", "-v", "error", "-i", "/workspace/" + source.relative_to(workspace.path).as_posix(),
                "-frames:v", "1", "-vf", "scale=8:8,format=gray", "-f", "rawvideo", "-y", "/workspace/phash.raw",
            ],
            workspace=workspace,
            timeout=30,
            max_output_bytes=1024,
        )
        if result.returncode != 0 or not raw.is_file() or raw.stat().st_size < 64:
            return None
        pixels = raw.read_bytes()[:64]
        average = sum(pixels) / len(pixels)
        bits = "".join("1" if value >= average else "0" for value in pixels)
        return f"{int(bits, 2):016x}"

    async def _ocr(self, source: Path, workspace) -> str | None:
        if not shutil.which("tesseract"):
            return None
        result = await self.media.run_isolated(
            ["tesseract", "/workspace/" + source.relative_to(workspace.path).as_posix(), "stdout", "-l", "eng"],
            workspace=workspace,
            timeout=60,
            max_output_bytes=512 * 1024,
        )
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        return text[: self.MAX_TEXT] if text else None

    async def analyze_file(self, path: str | Path) -> dict[str, Any]:
        """Analyze an already-authorized local media file inside a bounded workspace."""
        if not self._started:
            await self.start()
        source = self.media.validate_input(path)
        workspace = await self.media.create_workspace("media_intel")
        try:
            managed = workspace.resolve(source.name)
            if managed != source:
                shutil.copy2(source, managed)
            source = managed
            size = source.stat().st_size
            if size > self.media.max_input_bytes:
                raise ResourceError("Media input exceeds configured limit.")
            sha = self._sha256(source)
            media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            media_entity = await self._entity_observation(
                "MEDIA", sha,
                matched_field="sha256", match_type="CONTENT_HASH",
                provenance={"size_bytes": size, "media_type": media_type, "filename": source.name},
            )
            hash_entity = await self.intelgraph.add_entity(entity_type="HASH", canonical_value=sha, display_value=sha)
            await self.intelgraph.add_relationship(
                from_entity_id=media_entity, relationship_type="SHARES_HASH", to_entity_id=hash_entity,
                evidence_state="OBSERVED", confidence=1.0,
            )
            result: dict[str, Any] = {"sha256": sha, "size_bytes": size, "media_type": media_type}

            phash = await self._phash(source, workspace)
            if phash:
                phash_entity = await self._entity_observation(
                    "PHASH", phash, matched_field="phash", match_type="PERCEPTUAL_HASH",
                    provenance={"algorithm": "average-hash-8x8", "source_sha256": sha}, confidence=0.95,
                )
                await self.intelgraph.add_relationship(
                    from_entity_id=media_entity, relationship_type="SHARES_HASH", to_entity_id=phash_entity,
                    evidence_state="DERIVED", confidence=0.95,
                )
                result["phash"] = phash

            image_like = media_type.startswith("image/")
            video_like = media_type.startswith("video/")
            audio_like = media_type.startswith("audio/")
            frame: Path | None = None
            if video_like and shutil.which("ffmpeg"):
                frame = workspace.resolve("frame.png")
                probe = await self.media.run_isolated(
                    ["ffmpeg", "-v", "error", "-i", "/workspace/" + source.relative_to(workspace.path).as_posix(), "-frames:v", "1", "-vf", "scale=1280:-2", "-y", "/workspace/frame.png"],
                    workspace=workspace, timeout=30, max_output_bytes=16 * 1024,
                )
                if probe.returncode != 0 or not frame.is_file() or frame.stat().st_size > self.MAX_FRAME_BYTES:
                    frame = None
                else:
                    frame = self.media.validate_input(frame)
            ocr_source = frame if frame else source if image_like else None
            if ocr_source:
                text = await self._ocr(ocr_source, workspace)
                if text:
                    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    text_entity = await self._entity_observation(
                        "TEXT", text_hash, matched_field="ocr_text", match_type="OCR",
                        provenance={"source_sha256": sha, "text_bytes": len(text.encode("utf-8")), "bounded": True}, confidence=0.9,
                    )
                    await self.intelgraph.add_relationship(
                        from_entity_id=media_entity, relationship_type="MENTIONS", to_entity_id=text_entity,
                        evidence_state="DERIVED", confidence=0.9,
                    )
                    result["ocr_text"] = text

            if video_like and shutil.which("ffmpeg"):
                audio = workspace.resolve("audio.wav")
                extracted = await self.media.run_isolated(
                    ["ffmpeg", "-v", "error", "-i", "/workspace/" + source.relative_to(workspace.path).as_posix(), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", "/workspace/audio.wav"],
                    workspace=workspace, timeout=90, max_output_bytes=16 * 1024,
                )
                if extracted.returncode == 0 and audio.is_file() and audio.stat().st_size <= self.media.max_output_bytes:
                    transcript_source = self.media.validate_input(audio)
                else:
                    transcript_source = None
            else:
                transcript_source = source if audio_like else None

            if transcript_source and self.ai is not None:
                try:
                    transcript = await self.ai.transcribe(transcript_source)
                    text = str(getattr(transcript, "text", transcript) or "").strip()[: self.MAX_TEXT]
                except Exception:
                    text = None
                if text:
                    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    text_entity = await self._entity_observation(
                        "TEXT", text_hash, matched_field="transcript", match_type="SPEECH_TO_TEXT",
                        provenance={"source_sha256": sha, "text_bytes": len(text.encode("utf-8")), "bounded": True}, confidence=0.85,
                    )
                    await self.intelgraph.add_relationship(
                        from_entity_id=media_entity, relationship_type="MENTIONS", to_entity_id=text_entity,
                        evidence_state="DERIVED", confidence=0.85,
                    )
                    result["transcript"] = text
                else:
                    result["transcript"] = "unavailable"
            elif transcript_source:
                result["transcript"] = "unavailable"
            return result
        finally:
            await self.media.cleanup(workspace)

    async def similar(self, phash: str, *, limit: int = 25) -> list[dict[str, Any]]:
        """Return bounded perceptual-hash candidates using deterministic Hamming distance."""
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.intelgraph.storage.fetchall(
            "SELECT entity_id,canonical_value,display_value FROM intel_entities WHERE entity_type='PHASH' ORDER BY updated_at DESC LIMIT ?",
            (self.MAX_ROWS,),
        )
        matches = []
        for row in rows:
            distance = self._hamming(phash, str(row[1]))
            if distance <= self.PHASH_DISTANCE:
                matches.append({"entity_id": row[0], "phash": row[1], "display_value": row[2], "distance": distance})
        return sorted(matches, key=lambda item: (item["distance"], item["phash"]))[:bounded]
