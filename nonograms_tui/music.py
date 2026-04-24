"""Background music — fire-and-forget looping subprocess (nonograms-tui)."""

from __future__ import annotations

import atexit
import ctypes
import os
import random
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

MUSIC_DIR = Path(__file__).resolve().parent / "assets" / "music"
TRACKS: list[Path] = [
    MUSIC_DIR / "km_gymnopedie_no_1.mp3",
    MUSIC_DIR / "km_plucky_daisy.mp3",
]
ATTRIBUTIONS = [
    "Gymnopedie No. 1 — Kevin MacLeod (incompetech.com), CC-BY 4.0",
    "Plucky Daisy — Kevin MacLeod (incompetech.com), CC-BY 4.0",
]

_ACTIVE: list["MusicPlayer"] = []
_SIGNATURE = "nonograms_tui/assets/music/"


def _detect_player() -> list[str] | None:
    for cmd in (["paplay"], ["afplay"]):
        if shutil.which(cmd[0]):
            return cmd
    return None


def _install_parent_death_trap() -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(1, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


@atexit.register
def _kill_all_players() -> None:
    for p in list(_ACTIVE):
        try:
            p.stop()
        except Exception:
            pass


def _cleanup_orphans() -> None:
    try:
        out = subprocess.check_output(
            ["pgrep", "-af", _SIGNATURE],
            stderr=subprocess.DEVNULL,
        ).decode()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return
    my_pid = os.getpid()
    for line in out.splitlines():
        m = re.match(r"^(\d+)\s+", line)
        if not m:
            continue
        pid = int(m.group(1))
        if pid == my_pid:
            continue
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass


class MusicPlayer:
    def __init__(self, enabled: bool = True,
                 tracks: list[Path] | None = None) -> None:
        self.tracks = [t for t in (tracks or TRACKS) if t.exists()]
        self.enabled = enabled and bool(self.tracks)
        self._player = _detect_player() if self.enabled else None
        self._proc: subprocess.Popen | None = None
        if self.enabled and self._player is None:
            self.enabled = False

    def start(self) -> None:
        if not self.enabled or self._proc is not None or not self.tracks:
            return
        _cleanup_orphans()
        track = random.choice(self.tracks)
        try:
            player_cmd = " ".join(self._player or [])
            loop_cmd = (
                f"trap 'kill -TERM $(jobs -p) 2>/dev/null; exit 0' TERM INT HUP; "
                f'while true; do {player_cmd} "{track}" >/dev/null 2>&1 & wait $!; done'
            )
            self._proc = subprocess.Popen(
                ["bash", "-c", loop_cmd],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                preexec_fn=_install_parent_death_trap,
            )
            if self not in _ACTIVE:
                _ACTIVE.append(self)
        except (OSError, FileNotFoundError):
            self.enabled = False

    def stop(self) -> None:
        if self._proc is None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            self._proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        self._proc = None
        if self in _ACTIVE:
            _ACTIVE.remove(self)

    @property
    def is_playing(self) -> bool:
        return self._proc is not None

    def toggle(self) -> bool:
        if self.is_playing:
            self.stop()
            return False
        self.start()
        return self.is_playing
