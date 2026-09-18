"""Bounded media intelligence built on the existing MediaService and IntelGraph."""
from __future__ import annotations

import hashlib
import math
import mimetypes
import shutil
from pathlib import Path
from typing import Any

from core.errors import ResourceError


class MediaIntelService:
    """Turn authorized local media into durable, bounded, evidence-backed observations."""

    MAX_TEXT = 64 * 1024
    MAX_FRAME_BYTES = 2 * 1024 * 1024
    MAX_ROWS = 100
    MAX_FRAMES = 3
    FRAME_INTERVAL_SECONDS = (0, 5, 10)
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

    @staticmethod
    def _median(values: list[float]) -> float:
        ordered = sorted(values)
        if not ordered:
            return 0.0
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return ordered[middle]
        return (ordered[middle - 1] + ordered[middle]) / 2.0

    @staticmethod
    def _dct_phash(pixels: bytes) -> str:
        """Compute a deterministic 64-bit DCT pHash from a 32x32 grayscale frame."""
        size = 32
        values = [float(value) for value in pixels[: size * size]]
        coeffs: list[float] = []
        for u in range(8):
            for v in range(8):
                total = 0.0
                for x in range(size):
                    for y in range(size):
                        total += values[x * size + y] * math.cos((2 * x + 1) * u * math.pi / (2 * size)) * math.cos((2 * y + 1) * v * math.pi / (2 * size))
                alpha_u = 1 / math.sqrt(size) if u == 0 else math.sqrt(2 / size)
                alpha_v = 1 / math.sqrt(size) if v == 0 else math.sqrt(2 / size)
                coeffs.append(alpha_u * alpha_v * total)
        median = MediaIntelService._median(coeffs[1:])
        bits = "".join("1" if value >= median else "0" for value in coeffs[1:65])
        return f"{int(bits, 2):016x}"

    @staticmethod
    def _ahash(pixels: bytes) -> str:
        values = pixels[:64]
        average = sum(values) / len(values)
        return f"{int(''.join('1' if value >= average else '0' for value in values), 2):016x}"

    @staticmethod
    def _dhash(pixels: bytes) -> str:
        if len(pixels) < 72:
            return "0" * 16
        bits = []
        for row in range(8):
            start = row * 9
            bits.extend("1" if pixels[start + col] > pixels[start + col + 1] else "0" for col in range(8))
        return f"{int(''.join(bits), 2):016x}"

    async def _frame_hashes(self, source: Path, workspace) -> dict[str, str | None]:
        """Decode one bounded grayscale frame through the reviewed isolation boundary."""
        if not shutil.which("ffmpeg"):
            return {"phash": None, "ahash": None, "dhash": None}
        relative = source.relative_to(workspace.path).as_posix()
        result = await self.media.run_isolated([
            "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
            "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
            "-i", f"/workspace/{relative}", "-an", "-sn", "-dn", "-frames:v", "1",
            "-vf", "scale=32:32:flags=bilinear", "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1",
        ], workspace=workspace, timeout=30, max_output_bytes=16 * 1024)
        pixels = result.stdout.encode("latin-1") if result.stdout else b""
        if result.returncode != 0 or len(pixels) < 1024:
            pgm = workspace.resolve("hash.pgm")
            fallback = await self.media.run_isolated([
                "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
                "-threads", "1", "-filter_threads", "1", "-filter_complex_threads", "1",
                "-i", f"/workspace/{relative}", "-an", "-sn", "-dn", "-frames:v", "1",
                "-vf", "scale=32:32:flags=bilinear,format=gray",
                "-f", "image2", "-vcodec", "pgm", "-y", "/workspace/hash.pgm",
            ], workspace=workspace, timeout=30, max_output_bytes=16 * 1024)
            if fallback.returncode != 0 or not pgm.is_file():
                return {"phash": None, "ahash": None, "dhash": None}
            payload = pgm.read_bytes()
            marker = payload.find(b"\\n255\\n")
            if marker < 0:
                return {"phash": None, "ahash": None, "dhash": None}
            pixels = payload[marker + 5: marker + 5 + 1024]
        else:
            pixels = pixels[:1024]
        if len(pixels) < 1024:
            return {"phash": None, "ahash": None, "dhash": None}
        ahash_pixels = bytes(pixels[row * 32 + col] for row in range(0, 32, 4) for col in range(0, 32, 4))
        dhash_grid = bytearray()
        for row in range(8):
            y = row * 4
            for col in range(9):
                x = min(col * 4, 31)
                dhash_grid.append(pixels[y * 32 + x])
        return {"phash": self._dct_phash(pixels), "ahash": self._ahash(ahash_pixels), "dhash": self._dhash(bytes(dhash_grid))}
    async def _entity_observation(self, entity_type: str, value: str, *, matched_field: str, match_type: str, provenance: dict[str, Any], confidence: float = 1.0) -> str:
        entity_id = await self.intelgraph.add_entity(entity_type=entity_type, canonical_value=value, display_value=value)
        await self.intelgraph.add_observation(entity_id=entity_id, source_id="media-intel-local", source_family="MEDIA", matched_field=matched_field, match_type=match_type, evidence_state="OBSERVED", confidence=confidence, provenance=provenance)
        return entity_id

    async def _ingest_text(self, media_entity: str, text: str, *, sha: str, matched_field: str, match_type: str, confidence: float) -> int:
        indicators = await self.intelgraph.ingest_text(source_id="media-intel-local", source_family="MEDIA", text=text[: self.MAX_TEXT], query_context=f"media:{sha}")
        for indicator in indicators[: self.MAX_ROWS]:
            await self.intelgraph.add_relationship(from_entity_id=media_entity, relationship_type="MENTIONS", to_entity_id=indicator["entity_id"], evidence_state="DERIVED", confidence=confidence, observation_id=indicator.get("observation_id"))
        return len(indicators)

    async def _ocr(self, source: Path, workspace) -> str | None:
        if not shutil.which("tesseract"):
            return None
        result = await self.media.run_isolated(["tesseract", "/workspace/" + source.relative_to(workspace.path).as_posix(), "stdout", "-l", "eng"], workspace=workspace, timeout=60, max_output_bytes=512 * 1024)
        if result.returncode != 0:
            return None
        text = result.stdout.strip()
        return text[: self.MAX_TEXT] if text else None

    async def analyze_file(self, path: str | Path) -> dict[str, Any]:
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
            media_entity = await self._entity_observation("MEDIA", sha, matched_field="sha256", match_type="CONTENT_HASH", provenance={"size_bytes": size, "media_type": media_type, "filename": source.name})
            hash_entity = await self.intelgraph.add_entity(entity_type="HASH", canonical_value=sha, display_value=sha)
            await self.intelgraph.add_relationship(from_entity_id=media_entity, relationship_type="SHARES_HASH", to_entity_id=hash_entity, evidence_state="OBSERVED", confidence=1.0)
            result: dict[str, Any] = {"sha256": sha, "size_bytes": size, "media_type": media_type}
            hashes = await self._frame_hashes(source, workspace)
            for kind, match_type, confidence in (("phash", "PERCEPTUAL_HASH", 0.95), ("ahash", "PERCEPTUAL_HASH", 0.9), ("dhash", "PERCEPTUAL_HASH", 0.9)):
                value = hashes.get(kind)
                if value:
                    await self._entity_observation(kind.upper(), str(value), matched_field=kind, match_type=match_type, provenance={"source_sha256": sha, "algorithm": kind}, confidence=confidence)
                    result[kind] = value
            image_like = media_type.startswith("image/")
            video_like = media_type.startswith("video/")
            audio_like = media_type.startswith("audio/")
            frames: list[Path] = []
            if video_like and shutil.which("ffmpeg"):
                relative = source.relative_to(workspace.path).as_posix()
                for index, seconds in enumerate(self.FRAME_INTERVAL_SECONDS):
                    frame = workspace.resolve(f"frame-{index}.png")
                    probe = await self.media.run_isolated(
                        [
                            "ffmpeg",
                            "-hide_banner",
                            "-nostdin",
                            "-v",
                            "error",
                            "-threads",
                            "1",
                            "-filter_threads",
                            "1",
                            "-filter_complex_threads",
                            "1",
                            "-i",
                            f"/workspace/{relative}",
                            "-ss",
                            str(seconds),
                            "-copyts",
                            "-start_at_zero",
                            "-an",
                            "-sn",
                            "-dn",
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=640:-2:flags=bilinear",
                            "-y",
                            f"/workspace/frame-{index}.png",
                        ],
                        workspace=workspace,
                        timeout=30,
                        max_output_bytes=16 * 1024,
                    )
                    if probe.returncode == 0 and frame.is_file() and 0 < frame.stat().st_size <= self.MAX_FRAME_BYTES:
                        frames.append(frame)
            if image_like:
                frames = [source]
            result["frames_sampled"] = min(len(frames), self.MAX_FRAMES)
            ocr_texts: list[str] = []
            for frame in frames[: self.MAX_FRAMES]:
                text = await self._ocr(frame, workspace)
                if text:
                    ocr_texts.append(text)
            result["ioc_count"] = 0
            if ocr_texts:
                text = "\n".join(dict.fromkeys(ocr_texts))[: self.MAX_TEXT]
                text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                text_entity = await self._entity_observation("TEXT", text_hash, matched_field="ocr_text", match_type="OCR", provenance={"source_sha256": sha, "text_bytes": len(text.encode("utf-8")), "frames": len(ocr_texts), "bounded": True}, confidence=0.9)
                await self.intelgraph.add_relationship(from_entity_id=media_entity, relationship_type="MENTIONS", to_entity_id=text_entity, evidence_state="DERIVED", confidence=0.9)
                result["ocr_text"] = text
                result["ioc_count"] = await self._ingest_text(media_entity, text, sha=sha, matched_field="ocr_text", match_type="OCR", confidence=0.9)
            if video_like and shutil.which("ffmpeg"):
                audio = workspace.resolve("audio.wav")
                relative = source.relative_to(workspace.path).as_posix()
                extracted = await self.media.run_isolated(
                    [
                        "ffmpeg",
                        "-hide_banner",
                        "-nostdin",
                        "-v",
                        "error",
                        "-threads",
                        "1",
                        "-i",
                        f"/workspace/{relative}",
                        "-vn",
                        "-sn",
                        "-dn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-c:a",
                        "pcm_s16le",
                        "-y",
                        "/workspace/audio.wav",
                    ],
                    workspace=workspace,
                    timeout=90,
                    max_output_bytes=16 * 1024,
                )
                transcript_source = audio if extracted.returncode == 0 and audio.is_file() and audio.stat().st_size <= self.media.max_output_bytes else None
            else:
                transcript_source = source if audio_like else None
            if transcript_source and self.ai is not None:
                try:
                    transcript_result = await self.ai.transcribe(transcript_source)
                    text = str(getattr(transcript_result, "text", transcript_result) or "").strip()[: self.MAX_TEXT]
                except Exception:
                    text = None
                if text:
                    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
                    text_entity = await self._entity_observation("TEXT", text_hash, matched_field="transcript", match_type="SPEECH_TO_TEXT", provenance={"source_sha256": sha, "text_bytes": len(text.encode("utf-8")), "bounded": True}, confidence=0.85)
                    await self.intelgraph.add_relationship(from_entity_id=media_entity, relationship_type="MENTIONS", to_entity_id=text_entity, evidence_state="DERIVED", confidence=0.85)
                    result["transcript"] = text
                    result["ioc_count"] = result.get("ioc_count", 0) + await self._ingest_text(media_entity, text, sha=sha, matched_field="transcript", match_type="SPEECH_TO_TEXT", confidence=0.85)
                else:
                    result["transcript"] = "unavailable"
            elif transcript_source:
                result["transcript"] = "unavailable"
            return result
        finally:
            await self.media.cleanup(workspace)

    async def similar(self, phash: str, *, limit: int = 25) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), self.MAX_ROWS))
        rows = await self.intelgraph.storage.fetchall("SELECT entity_id,canonical_value,display_value FROM intel_entities WHERE entity_type='PHASH' ORDER BY updated_at DESC LIMIT ?", (self.MAX_ROWS,))
        matches = []
        for row in rows:
            distance = self._hamming(phash, str(row[1]))
            if distance <= self.PHASH_DISTANCE:
                matches.append({"entity_id": row[0], "phash": row[1], "display_value": row[2], "distance": distance})
        return sorted(matches, key=lambda item: (item["distance"], item["phash"]))[:bounded]
