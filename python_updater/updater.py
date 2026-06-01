from __future__ import annotations

import json
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QProcess, QTimer, QUrl, pyqtSignal
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

PROGRAM_EXE_NAME = "MyProgram.exe"
NEW_PROGRAM_EXE_NAME = "MyProgram_new.exe"
ZIP_NAME = "package.zip"
EXTRACT_DIR_NAME = "package_extract"
# Optional nested root folder name used by packaged zip releases.
OPTIONAL_PACKAGE_SUBDIR_NAME = "maeipmaechuljang"
PROTECTED_PATHS = {"data", "logs"}
SHUTDOWN_WAIT_MS = 2000
NETWORK_TIMEOUT_MS = 30000


@dataclass
class AssetInfo:
    name: str
    download_url: str
    is_exe: bool = False
    is_zip: bool = False


class Updater(QObject):
    status_message_changed = pyqtSignal(str)
    status_log_changed = pyqtSignal(str)
    progress_changed = pyqtSignal(int)
    finished = pyqtSignal()

    def __init__(self, current_version: str, repo_owner: str, repo_name: str) -> None:
        super().__init__()
        self._status_message = ""
        self._status_log = ""
        self._progress = 0

        self._current_version = current_version
        self._repo_owner = repo_owner
        self._repo_name = repo_name

        self._network_manager = QNetworkAccessManager(self)
        self._active_reply: Optional[QNetworkReply] = None
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._abort_active_reply)

        self._download_file: Optional[Path] = None
        self._download_fh = None
        self._download_write_failed = False
        self._download_case: Optional[str] = None

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def status_log(self) -> str:
        return self._status_log

    @property
    def progress(self) -> int:
        return self._progress

    def start_update(self) -> None:
        self._set_progress(0)
        self._set_status_message("Checking latest release information...")
        self._request_latest_release()

    def request_restart(self) -> None:
        target = Path.cwd() / os.getenv("UPDATER_TARGET_EXE", PROGRAM_EXE_NAME)
        QProcess.startDetached(str(target), [])

    def _request_latest_release(self) -> None:
        self._clear_reply()
        api_url = f"https://api.github.com/repos/{self._repo_owner}/{self._repo_name}/releases/latest"
        request = self._create_request(api_url)
        self._active_reply = self._network_manager.get(request)
        self._active_reply.finished.connect(self._on_update_info_received)
        self._arm_timeout()

    def _create_request(self, url: str) -> QNetworkRequest:
        request = QNetworkRequest()
        request.setUrl(QUrl(url))
        request.setRawHeader(
            b"User-Agent", f"qt-updater/1.0 (github.com/{self._repo_owner}/{self._repo_name})".encode()
        )
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        return request

    def _on_update_info_received(self) -> None:
        reply = self._active_reply
        self._active_reply = None
        self._timeout_timer.stop()

        if reply is None:
            self._handle_failure("Release check failed.")
            return

        ok = reply.error() == QNetworkReply.NetworkError.NoError
        payload = bytes(reply.readAll()) if ok else b""
        reply.deleteLater()

        if not ok or not payload:
            self._handle_failure("Failed to fetch release information.")
            return

        try:
            metadata = json.loads(payload.decode("utf-8"))
        except Exception:
            self._handle_failure("Failed to parse release metadata.")
            return

        latest_version = str(metadata.get("tag_name", "")).strip()
        if not latest_version:
            self._handle_failure("Release metadata missing tag_name.")
            return

        if not self._is_newer_version(latest_version, self._current_version):
            self._set_status_message("No update available.")
            self._finish_and_exit()
            return

        asset = self._choose_asset(metadata.get("assets", []))
        if asset is None:
            self._handle_failure("No downloadable .exe or .zip release asset found.")
            return

        if asset.is_exe:
            self._download_case = "exe"
            self._download_file = Path.cwd() / NEW_PROGRAM_EXE_NAME
        else:
            self._download_case = "zip"
            self._download_file = Path.cwd() / ZIP_NAME

        self._set_status_message("Downloading file...")
        self._start_asset_download(asset.download_url)

    def _start_asset_download(self, url: str) -> None:
        self._clear_reply()
        if self._download_file is None:
            self._handle_failure("Failed to create local update package file.")
            return

        try:
            self._download_file.parent.mkdir(parents=True, exist_ok=True)
            self._download_fh = self._download_file.open("wb")
        except OSError:
            self._download_fh = None
            self._handle_failure("Failed to create local update package file.")
            return

        self._download_write_failed = False
        self._set_progress(0)

        self._active_reply = self._network_manager.get(self._create_request(url))
        self._active_reply.readyRead.connect(self._on_download_ready_read)
        self._active_reply.downloadProgress.connect(self._on_download_progress)
        self._active_reply.finished.connect(self._on_download_finished)
        self._arm_timeout()

    def _on_download_ready_read(self) -> None:
        if self._active_reply is None or self._download_fh is None:
            return

        data = bytes(self._active_reply.readAll())
        if not data:
            return

        try:
            self._download_fh.write(data)
        except OSError:
            self._download_write_failed = True
            self._abort_active_reply()

    def _on_download_progress(self, bytes_received: int, bytes_total: int) -> None:
        if bytes_total <= 0:
            return
        self._arm_timeout()
        percentage = int((float(bytes_received) * 100.0) / float(bytes_total))
        self._set_progress(percentage)

    def _on_download_finished(self) -> None:
        self._on_download_ready_read()

        reply = self._active_reply
        self._active_reply = None
        self._timeout_timer.stop()

        request_ok = reply is not None and reply.error() == QNetworkReply.NetworkError.NoError
        if reply is not None:
            reply.deleteLater()

        if self._download_fh is not None:
            self._download_fh.flush()
            self._download_fh.close()
            self._download_fh = None

        if self._download_write_failed or not request_ok:
            if self._download_file is not None and self._download_file.exists():
                self._download_file.unlink(missing_ok=True)
            self._handle_failure("Failed to download update package.")
            return

        self._set_progress(100)
        self._set_status_message("Download complete.")
        QTimer.singleShot(SHUTDOWN_WAIT_MS, self._begin_apply_downloaded_update)

    def _begin_apply_downloaded_update(self) -> None:
        apply_success = False

        if self._download_case == "exe":
            self._set_status_message("Replacing old binaries...")
            apply_success = self._replace_exe()
        elif self._download_case == "zip":
            apply_success = self._apply_zip_package()

        if not apply_success:
            self._handle_failure("Failed to apply update package.")
            return

        self._set_status_message("Update complete! Click the button to restart.")
        self.finished.emit()

    def _replace_exe(self) -> bool:
        old_exe = Path.cwd() / os.getenv("UPDATER_TARGET_EXE", PROGRAM_EXE_NAME)
        new_exe = Path.cwd() / NEW_PROGRAM_EXE_NAME

        if not new_exe.exists():
            return False

        if old_exe.exists():
            try:
                old_exe.unlink()
            except OSError:
                return False

        try:
            new_exe.rename(old_exe)
            return True
        except OSError:
            return False

    def _apply_zip_package(self) -> bool:
        if sys.platform != "win32":
            self._set_status_message("ZIP updates are supported on Windows only.")
            return False

        zip_path = Path.cwd() / ZIP_NAME
        extract_path = Path.cwd() / EXTRACT_DIR_NAME
        work_dir = Path.cwd()

        if not zip_path.exists():
            self._set_status_message("package.zip not found.")
            return False

        try:
            if extract_path.exists():
                shutil.rmtree(extract_path, ignore_errors=False)
            extract_path.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_path)
        except Exception:
            self._set_status_message("Extraction failed.")
            return False

        nested_root = extract_path / OPTIONAL_PACKAGE_SUBDIR_NAME
        source_root = nested_root if nested_root.exists() else extract_path
        if not source_root.exists():
            self._set_status_message("Extracted source directory not found.")
            return False

        try:
            for entry in sorted(source_root.rglob("*")):
                relative = entry.relative_to(source_root)
                relative_str = str(relative).replace("\\", "/")
                if self._is_protected_relative_path(relative_str):
                    self._set_status_message(f"Skipping protected path: {relative_str}")
                    continue

                destination = work_dir / relative
                if entry.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                self._set_status_message(f"Copying: {relative_str}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    destination.unlink()
                shutil.copy2(entry, destination)

            shutil.rmtree(extract_path, ignore_errors=False)
            zip_path.unlink(missing_ok=True)
        except Exception:
            self._set_status_message("Failed to apply extracted files.")
            return False
        self._set_status_message("Update files copied successfully.")
        return True

    @staticmethod
    def _normalize_version(version: str) -> str:
        value = version.strip()
        if value.lower().startswith("v"):
            value = value[1:]
        return value

    @classmethod
    def _is_newer_version(cls, latest_tag: str, current_tag: str) -> bool:
        latest = cls._normalize_version(latest_tag)
        current = cls._normalize_version(current_tag)
        if latest == current:
            return False

        latest_parts = [int(x) for x in re.findall(r"(\d+)", latest)]
        current_parts = [int(x) for x in re.findall(r"(\d+)", current)]
        max_count = max(len(latest_parts), len(current_parts))
        latest_parts.extend([0] * (max_count - len(latest_parts)))
        current_parts.extend([0] * (max_count - len(current_parts)))

        return latest_parts > current_parts

    @staticmethod
    def _choose_asset(assets: list[dict]) -> Optional[AssetInfo]:
        first_exe: Optional[AssetInfo] = None
        first_zip: Optional[AssetInfo] = None

        for raw in assets:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name", ""))
            url = str(raw.get("browser_download_url", ""))
            if not name or not url:
                continue

            lower_name = name.lower()
            info = AssetInfo(
                name=name,
                download_url=url,
                is_exe=lower_name.endswith(".exe"),
                is_zip=lower_name.endswith(".zip"),
            )
            if info.is_exe and first_exe is None:
                first_exe = info
            if info.is_zip and first_zip is None:
                first_zip = info

        return first_exe or first_zip

    @staticmethod
    def _is_protected_relative_path(relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        parts = [part.lower() for part in normalized.strip("/").split("/") if part]
        return any(part in PROTECTED_PATHS for part in parts)

    def _set_status_message(self, message: str) -> None:
        if message:
            self._status_log = f"{self._status_log}\n{message}" if self._status_log else message
            self.status_log_changed.emit(self._status_log)

        if self._status_message == message:
            return

        self._status_message = message
        self.status_message_changed.emit(message)

    def _set_progress(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        if self._progress == value:
            return

        self._progress = value
        self.progress_changed.emit(value)

    def _handle_failure(self, message: str) -> None:
        self._set_status_message(message)
        self._finish_and_exit()

    def _finish_and_exit(self, delay_ms: int = 1200) -> None:
        QTimer.singleShot(delay_ms, self.finished.emit)

    def _abort_active_reply(self) -> None:
        if self._active_reply is not None:
            self._active_reply.abort()

    def _arm_timeout(self) -> None:
        self._timeout_timer.start(NETWORK_TIMEOUT_MS)

    def _clear_reply(self) -> None:
        if self._active_reply is not None:
            self._active_reply.abort()
            self._active_reply.deleteLater()
            self._active_reply = None
        self._timeout_timer.stop()
