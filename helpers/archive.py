"""Safe ZIP/TAR extraction with traversal, link, and expansion limits."""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


class ArchiveSafetyError(ValueError):
    """Raised when an archive violates the extraction policy."""


DEFAULT_MAX_ENTRIES = 2_000
DEFAULT_MAX_FILE_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 256 * 1024 * 1024


def _safe_destination(root: Path, name: str) -> Path:
    if not name or "\x00" in name:
        raise ArchiveSafetyError("Archive member has an invalid name")
    normalized = PurePosixPath(name.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ArchiveSafetyError("Archive member escapes extraction root")
    destination = (root / Path(*normalized.parts)).resolve()
    try:
        destination.relative_to(root.resolve())
    except ValueError as exc:
        raise ArchiveSafetyError("Archive member escapes extraction root") from exc
    return destination


def _ensure_parent(root: Path, destination: Path) -> None:
    parent = destination.parent.resolve()
    try:
        parent.relative_to(root.resolve())
    except ValueError as exc:
        raise ArchiveSafetyError("Archive parent escapes extraction root") from exc
    parent.mkdir(parents=True, exist_ok=True)


def extract_zip(
    archive: str | Path,
    destination: str | Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> int:
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    with zipfile.ZipFile(archive) as zf:
        infos = zf.infolist()
        if len(infos) > max_entries:
            raise ArchiveSafetyError("Archive contains too many entries")
        for info in infos:
            count += 1
            destination_path = _safe_destination(root, info.filename)
            is_dir = info.is_dir() or info.filename.endswith(("/", "\\"))
            if is_dir:
                destination_path.mkdir(parents=True, exist_ok=True)
                continue
            if info.file_size < 0 or info.file_size > max_file_bytes:
                raise ArchiveSafetyError("Archive member exceeds file-size limit")
            total += info.file_size
            if total > max_total_bytes:
                raise ArchiveSafetyError("Archive exceeds total extracted-size limit")
            _ensure_parent(root, destination_path)
            with zf.open(info, "r") as source, destination_path.open("wb") as target:
                remaining = info.file_size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ArchiveSafetyError("Archive member ended before declared size")
                    target.write(chunk)
                    remaining -= len(chunk)
    return count


def extract_tar(
    archive: str | Path,
    destination: str | Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> int:
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=True)
    total = 0
    count = 0
    with tarfile.open(archive, mode="r:*") as tf:
        members = tf.getmembers()
        if len(members) > max_entries:
            raise ArchiveSafetyError("Archive contains too many entries")
        for member in members:
            count += 1
            destination_path = _safe_destination(root, member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ArchiveSafetyError("Archive links and special files are not allowed")
            if member.isdir():
                destination_path.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile() or member.size < 0 or member.size > max_file_bytes:
                raise ArchiveSafetyError("Unsupported or oversized archive member")
            total += member.size
            if total > max_total_bytes:
                raise ArchiveSafetyError("Archive exceeds total extracted-size limit")
            _ensure_parent(root, destination_path)
            source = tf.extractfile(member)
            if source is None:
                raise ArchiveSafetyError("Unable to read archive member")
            with source, destination_path.open("wb") as target:
                remaining = member.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ArchiveSafetyError("Archive member ended before declared size")
                    target.write(chunk)
                    remaining -= len(chunk)
    return count


def extract_archive(
    archive: str | Path,
    destination: str | Path,
    *,
    max_entries: int = DEFAULT_MAX_ENTRIES,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> int:
    """Extract ZIP or TAR safely; never follows archive-provided links."""
    archive_path = Path(archive).resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(archive_path)
    if os.path.getsize(archive_path) > max_total_bytes:
        raise ArchiveSafetyError("Archive file exceeds configured size limit")
    try:
        if zipfile.is_zipfile(archive_path):
            return extract_zip(
                archive_path,
                destination,
                max_entries=max_entries,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
            )
        if tarfile.is_tarfile(archive_path):
            return extract_tar(
                archive_path,
                destination,
                max_entries=max_entries,
                max_file_bytes=max_file_bytes,
                max_total_bytes=max_total_bytes,
            )
    except (zipfile.BadZipFile, tarfile.TarError) as exc:
        raise ArchiveSafetyError("Invalid archive") from exc
    raise ArchiveSafetyError("Unsupported archive format")
