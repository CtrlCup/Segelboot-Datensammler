"""WebDAV-Synchronisation für DB und Bilder.

Pull: neuere oder fehlende Remote-Dateien werden nach lokal geladen.
Push: neuere oder fehlende lokale Dateien werden nach remote geladen.

Vergleichskriterium: Remote-Datei ist "neuer", wenn ihre mtime (aus der
WebDAV-PROPFIND-Antwort) jünger ist als die lokale mtime. Fehlt eine
Seite komplett, wird kopiert.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from webdav3.client import Client
from webdav3.exceptions import RemoteResourceNotFound, WebDavException

from config import DB_PATH, IMAGES_DIR, WEBDAV

logger = logging.getLogger(__name__)

# Zeit-Toleranz in Sekunden, damit minimale Clock-Drift nicht ständig
# Uploads / Downloads triggert.
MTIME_TOLERANCE = 2.0


def _build_client() -> Client:
    options = {
        "webdav_hostname": WEBDAV["hostname"],
        "webdav_login": WEBDAV["login"],
        "webdav_password": WEBDAV["password"],
        "webdav_timeout": WEBDAV.get("timeout", 60),
    }
    client = Client(options)
    client.verify = WEBDAV.get("verify_ssl", True)
    return client


def _remote_join(*parts: str) -> str:
    """Join remote path segments with a single '/'."""
    cleaned = [p.strip("/") for p in parts if p]
    return "/" + "/".join(cleaned) if cleaned else "/"


def _ensure_remote_dir(client: Client, remote_dir: str) -> None:
    """Stellt sicher, dass das Verzeichnis (und alle Eltern) auf dem Server existiert."""
    parts = [p for p in remote_dir.strip("/").split("/") if p]
    current = ""
    for part in parts:
        current = f"{current}/{part}"
        if not client.check(current):
            try:
                client.mkdir(current)
            except WebDavException as e:
                logger.warning("WebDAV: mkdir %s fehlgeschlagen: %s", current, e)


def _remote_mtime(client: Client, remote_path: str) -> float | None:
    """mtime einer Remote-Datei als Unix-Timestamp, oder None wenn nicht vorhanden."""
    try:
        info = client.info(remote_path)
    except (RemoteResourceNotFound, WebDavException):
        return None
    modified = info.get("modified") if info else None
    if not modified:
        return None
    try:
        dt = parsedate_to_datetime(modified)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (TypeError, ValueError):
        return None


def _local_mtime(path: Path) -> float | None:
    if not path.exists():
        return None
    return path.stat().st_mtime


def _iter_remote_files(client: Client, remote_dir: str) -> list[str]:
    """Rekursiv alle Dateien unter remote_dir auflisten (absolute Remote-Pfade)."""
    results: list[str] = []
    try:
        entries = client.list(remote_dir, get_info=False)
    except (RemoteResourceNotFound, WebDavException):
        return results

    for entry in entries:
        # webdav3 liefert bei manchen Servern das Verzeichnis selbst als erstes Element
        name = entry.rstrip("/")
        if not name or name == remote_dir.rstrip("/").rsplit("/", 1)[-1]:
            continue
        child = _remote_join(remote_dir, name)
        if entry.endswith("/"):
            results.extend(_iter_remote_files(client, child))
        else:
            results.append(child)
    return results


def _iter_local_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def _download_if_newer(client: Client, remote_path: str, local_path: Path) -> bool:
    r_mtime = _remote_mtime(client, remote_path)
    if r_mtime is None:
        return False
    l_mtime = _local_mtime(local_path)
    if l_mtime is not None and l_mtime + MTIME_TOLERANCE >= r_mtime:
        return False
    local_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        client.download_sync(remote_path=remote_path, local_path=str(local_path))
        logger.info("WebDAV pull: %s", remote_path)
        return True
    except WebDavException as e:
        logger.warning("WebDAV pull fehlgeschlagen %s: %s", remote_path, e)
        return False


def _upload_if_newer(client: Client, local_path: Path, remote_path: str) -> str:
    """Lade lokale Datei hoch, falls neuer. Return: 'uploaded' | 'skipped' | 'failed'."""
    l_mtime = _local_mtime(local_path)
    if l_mtime is None:
        return "skipped"
    r_mtime = _remote_mtime(client, remote_path)
    if r_mtime is not None and r_mtime + MTIME_TOLERANCE >= l_mtime:
        return "skipped"
    _ensure_remote_dir(client, remote_path.rsplit("/", 1)[0])
    try:
        client.upload_sync(remote_path=remote_path, local_path=str(local_path))
        logger.info("WebDAV push: %s", remote_path)
        return "uploaded"
    except WebDavException as e:
        logger.warning("WebDAV push fehlgeschlagen %s: %s", remote_path, e)
        return "failed"


def _remote_base() -> str:
    return _remote_join(WEBDAV["remote_path"])


def _project_root() -> Path:
    return Path(DB_PATH).parent.parent


def _to_remote(local_path: Path) -> str:
    rel = local_path.relative_to(_project_root()).as_posix()
    return _remote_join(_remote_base(), rel)


def _to_local(remote_path: str) -> Path:
    base = _remote_base().rstrip("/")
    rel = remote_path[len(base):].lstrip("/") if remote_path.startswith(base) else remote_path.lstrip("/")
    return _project_root() / rel


def pull() -> None:
    """Nur die Datenbank vom Server nach lokal laden.

    Bilder werden absichtlich NICHT heruntergeladen, um Bandbreite zu
    sparen. Die Zuordnung Bild-Ordner → Boot bleibt trotzdem erhalten,
    weil `boote.id` via AUTOINCREMENT nach dem Pull bei `max(id)+1`
    weiterzählt und neue Bilder damit in einen frischen Ordner mit
    eindeutigem Index landen.
    """
    if not WEBDAV.get("enabled") or not WEBDAV.get("pull_on_start", True):
        return

    logger.info("WebDAV: Pull startet (nur DB) (%s)", _remote_base())
    client = _build_client()
    _ensure_remote_dir(client, _remote_base())

    db_remote = _to_remote(DB_PATH)
    updated = _download_if_newer(client, db_remote, DB_PATH)
    logger.info(
        "WebDAV: Pull abgeschlossen (%s)",
        "DB aktualisiert" if updated else "DB bereits aktuell / nicht vorhanden",
    )


def push() -> None:
    """Neuere / fehlende lokale Dateien zum Server hochladen."""
    if not WEBDAV.get("enabled") or not WEBDAV.get("push_on_end", True):
        return

    logger.info("WebDAV: Push startet (%s)", _remote_base())
    client = _build_client()
    _ensure_remote_dir(client, _remote_base())

    db_uploaded = 0
    img_uploaded = 0
    # Pro Bilder-Unterordner merken, ob alle Dateien erfolgreich
    # hochgeladen oder bereits aktuell waren. Nur solche Ordner duerfen
    # danach lokal geloescht werden.
    folder_failed: dict[Path, bool] = {}

    # DB-Datei
    if DB_PATH.exists():
        if _upload_if_newer(client, DB_PATH, _to_remote(DB_PATH)) == "uploaded":
            db_uploaded = 1

    # Bilder-Ordner: nur neue / geaenderte werden dank mtime-Check
    # hochgeladen — bereits bekannte Ordner auf dem Server bleiben
    # unberuehrt.
    for local_file in _iter_local_files(IMAGES_DIR):
        status = _upload_if_newer(client, local_file, _to_remote(local_file))
        if status == "uploaded":
            img_uploaded += 1
        # Der erste Unterordner unterhalb von IMAGES_DIR = boat_id-Ordner
        try:
            rel = local_file.relative_to(IMAGES_DIR)
            boat_folder = IMAGES_DIR / rel.parts[0]
        except (ValueError, IndexError):
            continue
        folder_failed[boat_folder] = folder_failed.get(boat_folder, False) or (status == "failed")

    logger.info(
        "WebDAV: Push abgeschlossen (DB: %d, Bilder: %d)",
        db_uploaded, img_uploaded,
    )

    # Optionales lokales Aufraeumen der Bilder nach erfolgreichem Push.
    if WEBDAV.get("delete_images_after_push", False):
        _cleanup_local_images(folder_failed)


def _cleanup_local_images(folder_failed: dict[Path, bool]) -> None:
    """Lösche lokale Bild-Unterordner, deren Inhalte vollständig auf dem Server liegen."""
    deleted = 0
    kept = 0
    for folder, had_failure in folder_failed.items():
        if had_failure:
            logger.warning("Behalte %s lokal (Upload-Fehler)", folder)
            kept += 1
            continue
        try:
            shutil.rmtree(folder)
            deleted += 1
        except OSError as e:
            logger.warning("Konnte %s nicht löschen: %s", folder, e)
            kept += 1
    logger.info("WebDAV: Cleanup lokal — gelöscht: %d, behalten: %d", deleted, kept)
