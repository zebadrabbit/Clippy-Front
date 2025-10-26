#!/usr/bin/env python3
# ruff: noqa: I001
"""
Blessed-based TUI console for live monitoring of workers and logs.

- Top pane: key status (workers online, active tasks, projects processing)
- Bottom pane: live log tail from instance/logs/*.log with colorized levels

Controls:
  q           Quit
  f           Cycle log level filter (INFO -> WARNING -> ERROR -> DEBUG)
  d/i/w/e     Toggle individual log levels (Debug/Info/Warning/Error)
  c           Clear log view
  PgUp/PgDn   Scroll log view
  Home/End    Jump to top/bottom

This script assumes the virtual environment is active and the repo root is on
PYTHONPATH. It reads logs from <instance>/logs (or LOG_DIR env var).
"""
import argparse
import io
import os
import signal
import sys
import time
from collections import deque
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path

from blessed import Terminal


LOG_FILES = ("app.log", "worker.log", "beat.log")
DEFAULT_MAX_LINES = 2000
DEFAULT_TAIL_LINES = 300


class LogTailer:
    def __init__(
        self, directory: str, files: Iterable[str], max_lines: int = DEFAULT_MAX_LINES
    ):
        self.dir = Path(directory)
        self.files = [self.dir / f for f in files]
        self.max_lines = max_lines
        self.buffers: dict[Path, deque[str]] = {
            f: deque(maxlen=max_lines) for f in self.files
        }
        self.positions: dict[Path, int] = {f: 0 for f in self.files}
        self.inodes: dict[Path, int | None] = {f: None for f in self.files}

    def _open_file(self, path: Path) -> io.TextIOWrapper | None:
        try:
            return open(path, encoding="utf-8", errors="replace")
        except Exception:
            return None

    def _stat_inode(self, path: Path) -> int | None:
        try:
            return path.stat().st_ino
        except Exception:
            return None

    def _init_tail(self, path: Path, tail_lines: int = DEFAULT_TAIL_LINES) -> None:
        f = self._open_file(path)
        if not f:
            return
        try:
            # Tail last N lines efficiently
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 4096
            data = b""
            lines_found = 0
            while size > 0 and lines_found <= tail_lines:
                step = min(block, size)
                size -= step
                f.seek(size)
                data = f.read(step).encode("utf-8", "replace") + data
                lines_found = data.count(b"\n")
            text = data.decode("utf-8", "replace")
            lines = text.splitlines()[-tail_lines:]
            self.buffers[path].extend(lines)
            self.positions[path] = f.tell()
            self.inodes[path] = self._stat_inode(path)
        finally:
            try:
                f.close()
            except Exception:
                pass

    def initialize(self) -> None:
        for p in self.files:
            self._init_tail(p)

    def poll(self) -> list[str]:
        """Read any new lines from the files, handling rotation.
        Returns a combined list of new lines with prefixed filename.
        """
        out: list[str] = []
        for p in self.files:
            fh = self._open_file(p)
            if not fh:
                continue
            try:
                current_inode = self._stat_inode(p)
                # Detect rotation (inode changed or file shrank)
                rotated = (
                    self.inodes.get(p) is not None
                    and current_inode is not None
                    and current_inode != self.inodes.get(p)
                )
                if rotated or self.positions.get(p, 0) > os.path.getsize(p):
                    self.positions[p] = 0
                    self.inodes[p] = current_inode
                fh.seek(self.positions.get(p, 0))
                for line in fh:
                    line = line.rstrip("\n")
                    self.buffers[p].append(line)
                    out.append(f"{p.name}: {line}")
                self.positions[p] = fh.tell()
            finally:
                try:
                    fh.close()
                except Exception:
                    pass
        return out

    def get_view(self) -> list[str]:
        # Merge buffers in filename order (simple approach)
        merged: list[str] = []
        for p in self.files:
            merged.extend(list(self.buffers[p]))
        return merged[-self.max_lines :]

    def set_files(self, files: list[str]) -> None:
        """Switch the tailed files and reset internal buffers/positions."""
        self.files = [self.dir / f for f in files]
        self.buffers = {f: deque(maxlen=self.max_lines) for f in self.files}
        self.positions = {f: 0 for f in self.files}
        self.inodes = {f: None for f in self.files}
        self.initialize()


class StatusProvider:
    def __init__(self, app):
        self.app = app
        self.last_celery_query: float = 0.0
        self.cached_celery: dict = {}

    def celery_status(self, throttle_seconds: float = 3.0) -> dict:
        now = time.time()
        if now - self.last_celery_query < throttle_seconds and self.cached_celery:
            return self.cached_celery
        try:
            # Lazy import to avoid top-level local imports ordering issues
            from app.tasks.celery_app import celery_app as _celery_app

            insp = _celery_app.control.inspect(timeout=1.0)
            stats = insp.stats() or {}
            active = insp.active() or {}
            registered = insp.registered() or {}
        except Exception:
            stats, active, registered = {}, {}, {}
        self.cached_celery = {
            "workers": list(stats.keys()),
            "active": active,
            "registered_count": sum(len(v or []) for v in registered.values()),
        }
        self.last_celery_query = now
        return self.cached_celery

    def project_counts(self) -> tuple[int, int, int]:
        # processing, completed (24h), failed (24h)
        processing = 0
        completed_24h = 0
        failed_24h = 0
        try:
            # Lazy import models/db
            from app.models import Project, ProjectStatus, db

            with self.app.app_context():
                processing = (
                    db.session.query(Project)
                    .filter(Project.status == ProjectStatus.PROCESSING)
                    .count()
                )
                since = datetime.utcnow() - timedelta(days=1)
                completed_24h = (
                    db.session.query(Project)
                    .filter(Project.status == ProjectStatus.COMPLETED)
                    .filter(Project.completed_at.isnot(None))
                    .filter(Project.completed_at >= since)
                    .count()
                )
                failed_24h = (
                    db.session.query(Project)
                    .filter(Project.status == ProjectStatus.FAILED)
                    .filter(Project.updated_at >= since)
                    .count()
                )
        except Exception:
            pass
        return processing, completed_24h, failed_24h

    def job_counts(self) -> tuple[int, int, int]:
        # pending, running, errored
        pending = running = errored = 0
        try:
            from app.models import ProcessingJob, db

            with self.app.app_context():
                pending = (
                    db.session.query(ProcessingJob)
                    .filter(ProcessingJob.status == "pending")
                    .count()
                )
                running = (
                    db.session.query(ProcessingJob)
                    .filter(ProcessingJob.status.in_(["running", "started"]))
                    .count()
                )
                errored = (
                    db.session.query(ProcessingJob)
                    .filter(ProcessingJob.status.in_(["failure", "revoked"]))
                    .count()
                )
        except Exception:
            pass
        return pending, running, errored


def color_for_level(term: Terminal, line: str):
    lower = line.lower()
    if " error" in lower or lower.startswith("error") or ") [error]" in lower:
        return term.bold_red
    if " warning" in lower or lower.startswith("warning") or ") [warning]" in lower:
        return term.yellow
    if " debug" in lower or lower.startswith("debug") or ") [debug]" in lower:
        return term.dim + term.cyan
    if " info" in lower or lower.startswith("info") or ") [info]" in lower:
        return term.green
    return term.white


def level_included(levels: set[str], line: str) -> bool:
    lower = line.lower()
    # Default include if no explicit level found
    implied = "info"
    lvl = implied
    for candidate in ("debug", "info", "warning", "error"):
        if f"[{candidate}]" in lower:
            lvl = candidate
            break
    return lvl in levels


def draw(
    term: Terminal,
    sp: StatusProvider,
    tailer: LogTailer,
    levels: set[str],
    scroll: int,
    search: str,
    enabled_files: list[str],
    refresh: float,
) -> None:
    height, width = term.height, term.width
    top_h = max(5, int(height * 0.35))
    bottom_h = height - top_h - 1

    # Gather status
    celery = sp.celery_status()
    processing, c24, f24 = sp.project_counts()
    pending, running, errored = sp.job_counts()

    # Top pane
    print(term.move(0, 0) + term.on_black + term.clear)
    title = f" Clippy Console — Workers: {len(celery.get('workers', []))} | Processing: {processing} | Jobs P/R/E: {pending}/{running}/{errored} (24h C/F: {c24}/{f24}) "
    print(term.reverse + title.ljust(width) + term.normal)

    # Workers line(s)
    workers = celery.get("workers", [])
    active = celery.get("active", {})
    line1 = f"Workers: {', '.join(workers) or '—'}"
    print(term.move(1, 0) + term.bold + line1[:width] + term.normal)

    # Active tasks
    act_sum = sum(len(v or []) for v in active.values())
    print(term.move(2, 0) + f"Active tasks: {act_sum}")
    row = 3
    for w, tasks in list(active.items())[: top_h - 4]:
        tdesc = ", ".join(t.get("name", "?") for t in (tasks or []))
        print(term.move(row, 2) + f"{w}: {tdesc}"[: width - 2])
        row += 1

    # Separator
    print(term.move(top_h, 0) + term.white + ("-" * width) + term.normal)

    # Bottom pane: logs
    all_lines = tailer.get_view()
    filtered = [ln for ln in all_lines if level_included(levels, ln)]
    if search:
        needle = search.lower()
        filtered = [ln for ln in filtered if needle in ln.lower()]
    # Scroll from the end by scroll offset
    start = max(0, len(filtered) - bottom_h - scroll)
    view = filtered[start : start + bottom_h]

    for i, ln in enumerate(view):
        color = color_for_level(term, ln)
        print(term.move(top_h + 1 + i, 0) + color + ln[:width] + term.normal)

    # Footer
    footer = (
        " q:quit f:cycle v:verbosity d/i/w/e:toggle c:clear /:search +/-:rate "
        f"levels={','.join(sorted(levels))} search='{search or ''}' refresh={refresh:.2f}s files:"
    )
    # Show up to first 9 files with indices for toggling
    files_disp = []
    try:
        # Reconstruct names from tailer.files order
        names = [p.name for p in tailer.files]
        for idx, name in enumerate(names[:9], start=1):
            mark = "*" if name in enabled_files else " "
            files_disp.append(f" {idx}:{name}{mark}")
    except Exception:
        pass
    footer = (
        footer
        + "".join(files_disp)
        + " "
        + datetime.utcnow().isoformat(timespec="seconds")
        + "Z"
    )
    print(term.move(height - 1, 0) + term.reverse + footer.ljust(width) + term.normal)


def main() -> int:
    parser = argparse.ArgumentParser(description="Clippy console TUI")
    parser.add_argument(
        "--refresh", type=float, default=0.5, help="Refresh rate in seconds"
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default=None,
        help="Override log dir; defaults to instance/logs",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        default=DEFAULT_MAX_LINES,
        help="Max buffered log lines",
    )
    args = parser.parse_args()

    # Initialize Flask app (for DB access) but don't run server
    # Ensure repo root on sys.path for local imports
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from app import create_app  # local import
    from app.logging_config import get_log_dir  # local import

    app = create_app()
    instance_path = app.instance_path
    log_dir = args.log_dir or get_log_dir(instance_path)

    # Discover available log files
    try:
        available = sorted([p.name for p in Path(log_dir).glob("*.log")])
        if not available:
            available = list(LOG_FILES)
    except Exception:
        available = list(LOG_FILES)

    # Load persisted prefs
    prefs_path = Path(instance_path) / "data" / "console_prefs.json"
    try:
        prefs_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    prefs = {
        "levels": ["info", "warning", "error"],
        "refresh": args.refresh,
        "files": [f for f in available if f in {"app.log", "worker.log"}],
        "search": "",
    }
    try:
        import json as _json

        if prefs_path.exists():
            with open(prefs_path, encoding="utf-8") as f:
                loaded = _json.load(f)
                if isinstance(loaded, dict):
                    prefs.update(loaded)
    except Exception:
        pass

    enabled_files = (
        [f for f in prefs.get("files", []) if f in available]
        or [f for f in available if f in {"app.log", "worker.log"}]
        or available[:2]
    )
    levels = set(prefs.get("levels", ["info", "warning", "error"]))
    refresh = float(prefs.get("refresh", args.refresh))
    search = str(prefs.get("search", ""))

    tailer = LogTailer(log_dir, enabled_files, max_lines=args.max_lines)
    tailer.initialize()

    sp = StatusProvider(app)

    term = Terminal()
    scroll = 0

    # Graceful quit on Ctrl+C
    def _sigint(signum, frame):
        print(term.normal + term.clear)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    with term.fullscreen(), term.cbreak(), term.hidden_cursor():
        while True:
            ch = term.inkey(timeout=refresh)
            # Consume new logs
            tailer.poll()

            if ch:
                if ch.lower() == "q":
                    break
                elif ch.lower() == "c":
                    # Clear buffers
                    tailer = LogTailer(log_dir, enabled_files, max_lines=args.max_lines)
                    tailer.initialize()
                    scroll = 0
                elif ch.lower() == "f":
                    order = [
                        {"warning", "error"},
                        {"error"},
                        {"info", "warning", "error"},
                        {"debug", "info", "warning", "error"},
                    ]
                    # cycle to next set
                    try:
                        idx = next(i for i, s in enumerate(order) if s == levels)
                        levels = order[(idx + 1) % len(order)]
                    except StopIteration:
                        levels = order[0]
                elif ch.lower() == "v":
                    presets = [
                        {"debug", "info", "warning", "error"},
                        {"info", "warning", "error"},
                        {"warning", "error"},
                        {"error"},
                        set(),
                    ]
                    try:
                        idx = next(i for i, s in enumerate(presets) if s == levels)
                        levels = presets[(idx + 1) % len(presets)]
                    except StopIteration:
                        levels = presets[1]
                elif ch.name == "KEY_PGUP":
                    scroll = min(scroll + 5, max(0, DEFAULT_MAX_LINES))
                elif ch.name == "KEY_PGDOWN":
                    scroll = max(0, scroll - 5)
                elif ch.name == "KEY_HOME":
                    scroll = DEFAULT_MAX_LINES
                elif ch.name == "KEY_END":
                    scroll = 0
                elif ch.lower() in {"d", "i", "w", "e"}:
                    m = {"d": "debug", "i": "info", "w": "warning", "e": "error"}
                    lvl = m[ch.lower()]
                    if lvl in levels:
                        levels.remove(lvl)
                    else:
                        levels.add(lvl)
                elif ch == "/":
                    # Search input mode
                    query = search
                    prompt = "Search: "
                    print(
                        term.move(term.height - 1, 0)
                        + term.reverse
                        + (prompt + query).ljust(term.width)
                        + term.normal
                    )
                    while True:
                        k = term.inkey()
                        if not k:
                            continue
                        if k.name in ("KEY_ENTER", "KEY_RETURN"):
                            search = query
                            break
                        if k.name == "KEY_ESCAPE":
                            search = ""
                            break
                        if k.name in ("KEY_BACKSPACE", "KEY_DELETE"):
                            query = query[:-1]
                        elif k.is_sequence:
                            continue
                        else:
                            query += str(k)
                        print(
                            term.move(term.height - 1, 0)
                            + term.reverse
                            + (prompt + query).ljust(term.width)
                            + term.normal
                        )
                elif ch == "+":
                    refresh = min(5.0, max(0.1, refresh + 0.1))
                elif ch == "-":
                    refresh = min(5.0, max(0.1, refresh - 0.1))
                elif ch.isdigit() and 1 <= int(ch) <= 9:
                    idx = int(ch) - 1
                    try:
                        all_files = available
                        if idx < len(all_files):
                            fname = all_files[idx]
                            if fname in enabled_files:
                                enabled_files.remove(fname)
                            else:
                                enabled_files.append(fname)
                            if not enabled_files:
                                enabled_files.append(all_files[0])
                            tailer.set_files(enabled_files)
                            scroll = 0
                    except Exception:
                        pass

            draw(term, sp, tailer, levels, scroll, search, enabled_files, refresh)
    # Save preferences on exit
    try:
        import json as _json

        data = {
            "levels": sorted(levels),
            "refresh": refresh,
            "files": enabled_files,
            "search": search,
        }
        with open(prefs_path, "w", encoding="utf-8") as f:
            _json.dump(data, f)
    except Exception:
        pass

    print(term.normal + term.clear)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
