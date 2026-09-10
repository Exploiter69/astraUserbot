#!/usr/bin/env python3
# language: Python, file: astra.py, target: Arch Linux / Terminal
"""
Unified CLI for the local clipboard-bridge workflow.

    python astra.py                    # smart dispatcher: inspects state, tells you what to do
    python astra.py auto               # same as above, explicit
    python astra.py pack [task]        # full codebase -> clipboard (task: debug/review/architecture)
    python astra.py sync               # tests + git diff + untracked files -> clipboard
    python astra.py diff               # just git diff -> clipboard (lightweight review)
    python astra.py apply              # validated clipboard diff -> applied to repo
    python astra.py rollback           # undo the last apply's checkpoint
    python astra.py loop               # sync, and if tests fail, walk straight into the prompt
    python astra.py status             # what you last ran, and whether tests were passing
    python astra.py metrics            # file/extension/token breakdown of what pack would send
    python astra.py history            # last 10 things copied to clipboard, with an index
    python astra.py restore <n>        # put history item n back on the clipboard
    python astra.py clean              # remove temp.patch and __pycache__ clutter

Architecture (for anyone extending this file):
    1. Command Registry   -> self-registering subcommands, no central if/elif ladder.
    2. Environment layer   -> all git/pytest/clipboard calls go through adapters.
    3. Storage manager     -> single owner of .astra_state.json + .astra_history/.
    4. Auto rule pipeline  -> `auto`/`do` walks an ordered, appendable list of rules.
Adding a new subcommand or a new `auto` heuristic never requires touching the
dispatch code in main() or cmd_auto() — see the bottom of each section.
"""
from __future__ import annotations

import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

THIS_SCRIPT = Path(__file__).name

# A minimal but reasonably strict signal that clipboard text is a unified diff.
# Real .patch files use "diff --git" + "@@ ... @@" hunk headers; both should
# be present in anything git apply would accept.
DIFF_GIT_HEADER = re.compile(r'^diff --git ', re.MULTILINE)
HUNK_HEADER = re.compile(r'^@@ .* @@', re.MULTILINE)

CHECKPOINT_LABEL = "astra-checkpoint"

# ---------------------------------------------------------------------------
# Pack task presets — validated set only; an unrecognized preset name is a
# hard error with the valid list shown, never a silent fallback to generic.
# ---------------------------------------------------------------------------

PACK_PRESETS = {
    'debug': (
        "I'm hunting a bug in this codebase. Here's the full baseline.\n"
        "Please look for the likely cause before I describe symptoms — ask me for "
        "the specific error or behavior if you need it, then reply with a fix as a unified git diff."
    ),
    'review': (
        "Please review this codebase for code quality, security issues, and anything "
        "that looks fragile or worth cleaning up. Summarize findings first; only propose "
        "a diff for anything you'd consider a real problem, not style nitpicks."
    ),
    'architecture': (
        "Please look at the overall structure of this codebase — module boundaries, "
        "coupling, anything that looks like it'll cause pain as this grows. "
        "I'm looking for structural feedback, not a line-by-line review."
    ),
    'refactor': (
        "Here's my current codebase. I want to refactor [describe the target area] "
        "without changing behavior. Propose the refactor as a unified git diff, and call out "
        "anywhere the behavior might shift even slightly."
    ),
}


# =============================================================================
# TERMINAL STYLING
#
# A tiny ANSI helper so warnings, successes, and tips are visually distinct
# in the terminal — zero dependencies, stdlib escape codes only. This is
# strictly a terminal-output concern: colored output is NEVER written into
# clipboard payloads, history archives, or the state file — copy_to_clipboard
# and everything upstream of it (pack/sync/diff bundles) never touch UI.*, so
# colored escape codes can't leak into what gets pasted elsewhere.
# =============================================================================

class Style:
    """Prefix + color for each message level, auto-disabled when it would do
    more harm than good (non-TTY output, NO_COLOR set, or piped/redirected).

    Also the single choke point all stdout writes pass through (_print_lock),
    which is what lets a live Spinner and a plain UI.info()/warn()/etc. share
    the terminal safely — see Spinner below.
    """

    RESET = "\033[0m"
    BOLD = "\033[1m"
    _COLORS = {
        'blue': "\033[94m",
        'green': "\033[92m",
        'yellow': "\033[93m",
        'red': "\033[91m",
        'cyan': "\033[96m",
        'magenta': "\033[95m",
    }
    # level -> (bracket text, color)
    _LEVELS = {
        'info': ('[*]', 'blue'),
        'success': ('[+]', 'green'),
        'warn': ('[!]', 'yellow'),
        'error': ('[-]', 'red'),
        'tip': ('[>]', 'cyan'),
        'ask': ('[?]', 'magenta'),
    }

    def __init__(self) -> None:
        self.enabled = (
            sys.stdout.isatty()
            and not os.environ.get('NO_COLOR')
            and not os.environ.get('ASTRA_NO_COLOR')
        )
        # Guards every stdout write astra.py makes through UI.*, so a Spinner
        # thread redrawing its line and the main thread printing a warning
        # mid-operation can never interleave into garbled output.
        self._print_lock = threading.Lock()
        self._active_spinner: Optional["Spinner"] = None

    def _tag(self, level: str) -> str:
        bracket, color = self._LEVELS[level]
        if not self.enabled:
            return bracket
        return f"{self.BOLD}{self._COLORS[color]}{bracket}{self.RESET}"

    def _emit(self, level: str, msg: str) -> None:
        with self._print_lock:
            if self._active_spinner is not None:
                self._active_spinner._clear_line_locked()
            print(f"{self._tag(level)} {msg}")

    def info(self, msg: str) -> None:
        self._emit('info', msg)

    def success(self, msg: str) -> None:
        self._emit('success', msg)

    def warn(self, msg: str) -> None:
        self._emit('warn', msg)

    def error(self, msg: str) -> None:
        self._emit('error', msg)

    def tip(self, msg: str) -> None:
        self._emit('tip', msg)

    def ask(self, msg: str) -> str:
        with self._print_lock:
            if self._active_spinner is not None:
                self._active_spinner._clear_line_locked()
        return input(f"{self._tag('ask')} {msg}")

    def prompt_block(self, message: str) -> None:
        """The clearly-delimited block telling the user exactly what to
        type/paste next, so there's nothing to remember or improvise."""
        bar = self._COLORS['cyan'] + ("-" * 60) + self.RESET if self.enabled else "-" * 60
        with self._print_lock:
            if self._active_spinner is not None:
                self._active_spinner._clear_line_locked()
            print("\n" + bar)
            print(f"{self._tag('tip')} Say this in the chat (data is already on your clipboard):")
            print(bar)
            print(message)
            print(bar + "\n")

    def spinner(self, message: str) -> "Spinner":
        """Context manager: `with UI.spinner("Running tests..."): ...`. Live
        animated status while the wrapped block runs, on a TTY; a single
        static line (no redraws) everywhere else, so piped/redirected output
        stays clean plain text."""
        return Spinner(self, message)


class Spinner:
    """Non-blocking live status line for a blocking call (subprocess.run,
    typically). Draws in a background thread via carriage-return redraws;
    the wrapped call still runs — and blocks — on the calling thread, so
    this never changes execution order, only what's visible while waiting.
    """

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    INTERVAL = 0.08

    def __init__(self, ui: Style, message: str) -> None:
        self.ui = ui
        self.message = message
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._start_time = 0.0
        self._frame = 0
        self._line_len = 0

    def _render(self) -> str:
        elapsed = time.time() - self._start_time
        glyph = self.FRAMES[self._frame % len(self.FRAMES)]
        return f"{self.ui._tag('info')} {glyph} {self.message} ({elapsed:0.1f}s)"

    def _clear_line_locked(self) -> None:
        """Caller must hold ui._print_lock. Wipes the current spinner line
        so a normal UI.* message (or the final result) can print cleanly."""
        if self._line_len:
            sys.stdout.write("\r" + " " * self._line_len + "\r")
            sys.stdout.flush()
            self._line_len = 0

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self.ui._print_lock:
                line = self._render()
                pad = max(0, self._line_len - len(line))
                sys.stdout.write("\r" + line + (" " * pad))
                sys.stdout.flush()
                self._line_len = len(line)
            self._frame += 1
            self._stop.wait(self.INTERVAL)

    def __enter__(self) -> "Spinner":
        if not self.ui.enabled:
            # Non-TTY / NO_COLOR: one static line, no redraws — never write
            # carriage returns into piped or redirected output.
            print(f"{self.ui._tag('info')} {self.message}")
            return self
        self._start_time = time.time()
        self.ui._active_spinner = self
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._thread is not None:
            self._stop.set()
            self._thread.join()
            with self.ui._print_lock:
                self._clear_line_locked()
            self.ui._active_spinner = None
        return False  # never swallow exceptions from the wrapped block


UI = Style()



# =============================================================================
# 1. MODULAR CORE & COMMAND REGISTRY
#
# Any subcommand self-registers its name, aliases, description and execution
# logic via @COMMANDS.register(...). main() never needs to know the list of
# commands in advance — it just asks the registry.
# =============================================================================

@dataclass(frozen=True)
class CommandSpec:
    name: str
    description: str
    handler: Callable[["AppContext", list[str]], None]
    aliases: tuple[str, ...] = ()
    arg_hint: str = ""


class CommandRegistry:
    """Self-registering command table. Replaces the old rigid global dict —
    a new subcommand is added by decorating its handler, nowhere else."""

    def __init__(self) -> None:
        self._by_name: dict[str, CommandSpec] = {}
        self._order: list[CommandSpec] = []  # insertion order, primary names only

    def register(self, name: str, description: str, aliases: tuple[str, ...] = (), arg_hint: str = ""):
        def decorator(func: Callable[["AppContext", list[str]], None]):
            spec = CommandSpec(name=name, description=description, handler=func,
                                aliases=aliases, arg_hint=arg_hint)
            self._by_name[name] = spec
            for alias in aliases:
                self._by_name[alias] = spec
            self._order.append(spec)
            return func
        return decorator

    def get(self, name: str) -> Optional[CommandSpec]:
        return self._by_name.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    # Preferred display order for `--help`; commands not listed here (i.e.
    # anything registered later by a future extension) simply appear after,
    # in registration order — the registry stays authoritative, this is
    # purely cosmetic.
    DISPLAY_ORDER = (
        'pack', 'sync', 'diff', 'apply', 'rollback', 'loop',
        'status', 'metrics', 'history', 'restore', 'clean', 'auto',
    )

    def usage(self) -> str:
        lines = [
            "Unified CLI for the local clipboard-bridge workflow.\n",
            "    python astra.py                    # smart dispatcher: inspects state, tells you what to do",
        ]
        rank = {name: i for i, name in enumerate(self.DISPLAY_ORDER)}
        ordered = sorted(self._order, key=lambda s: rank.get(s.name, len(rank)))
        for spec in ordered:
            label = spec.name
            if spec.arg_hint:
                label += " " + spec.arg_hint
            if spec.aliases:
                label += " / " + " / ".join(spec.aliases)
            lines.append(f"    python astra.py {label:<22} # {spec.description}")
        return "\n".join(lines)


COMMANDS = CommandRegistry()


# =============================================================================
# 2. ENVIRONMENT & TOOL ADAPTER LAYER
#
# Every external system call (git, pytest, the clipboard) lives behind one of
# these adapters. Command logic never shells out directly — it goes through
# `ctx.env.git`, `ctx.env.clipboard`, or `ctx.env.tests`, which keeps the
# actual subprocess plumbing swappable (e.g. a future macOS `pbcopy` adapter)
# without touching any command implementation.
# =============================================================================

class ClipboardAdapter:
    """Wayland (wl-copy/wl-paste) or X11 (xclip) clipboard access."""

    def _copy_cmd(self) -> list[str]:
        return ['wl-copy'] if os.environ.get('WAYLAND_DISPLAY') else ['xclip', '-selection', 'clipboard']

    def _paste_cmd(self) -> list[str]:
        return ['wl-paste'] if os.environ.get('WAYLAND_DISPLAY') else ['xclip', '-o', '-selection', 'clipboard']

    def copy(self, text: str) -> bool:
        try:
            subprocess.run(self._copy_cmd(), input=text.encode('utf-8'), check=True)
            UI.success("Copied to clipboard.")
            return True
        except Exception as e:
            UI.error(f"Clipboard copy failed: {e}. Printing to console instead.")
            print(text[:500] + "\n... [truncated]")
            return False

    def paste(self) -> str:
        try:
            result = subprocess.run(self._paste_cmd(), capture_output=True, text=True, check=True)
            return result.stdout
        except Exception as e:
            UI.error(f"Failed to read clipboard: {e}")
            return ""


class GitAdapter:
    """All git subprocess calls, isolated in one place."""

    def is_repo(self, root: Path = Path('.')) -> bool:
        return (root / '.git').exists()

    def status_porcelain(self) -> str:
        result = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, check=False)
        return result.stdout

    def has_uncommitted_changes(self) -> bool:
        return bool(self.status_porcelain().strip())

    def untracked_files(self, root: Path = Path('.')) -> list[Path]:
        """Files git sees as new/untracked — `git diff` alone misses these
        entirely, so sync/diff would silently omit brand-new files otherwise."""
        if not self.is_repo(root):
            return []
        untracked = []
        for line in self.status_porcelain().splitlines():
            # '??' = untracked file, per `git status --porcelain` format
            if line.startswith('?? '):
                untracked.append(root / line[3:].strip())
        return untracked

    def diff(self) -> str:
        result = subprocess.run(['git', 'diff'], capture_output=True, text=True, check=False)
        return result.stdout

    def check_ignore(self, paths: list[Path]) -> set[str]:
        result = subprocess.run(
            ['git', 'check-ignore', '--stdin'],
            input='\n'.join(str(p) for p in paths),
            capture_output=True, text=True, check=False,
        )
        if result.returncode not in (0, 1):
            UI.warn(f"Warning: git check-ignore exited with code {result.returncode}: {result.stderr.strip()}")
            return set()
        return set(result.stdout.splitlines())

    def stash_push(self, message: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', 'stash', 'push', '-m', message], capture_output=True, text=True, check=False)

    def stash_list(self) -> subprocess.CompletedProcess:
        return subprocess.run(['git', 'stash', 'list'], capture_output=True, text=True, check=False)

    def stash_pop(self, ref: str) -> subprocess.CompletedProcess:
        return subprocess.run(['git', 'stash', 'pop', ref], capture_output=True, text=True, check=False)

    def reset_hard_head(self) -> subprocess.CompletedProcess:
        return subprocess.run(['git', 'reset', '--hard', 'HEAD'], capture_output=True, text=True, check=False)

    def apply_check(self, patch_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git', 'apply', '--check', '--whitespace=fix', str(patch_path)],
            capture_output=True, text=True, check=False,
        )

    def apply(self, patch_path: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            ['git', 'apply', '--whitespace=fix', str(patch_path)],
            capture_output=True, text=True, check=False,
        )


class TestRunner:
    """pytest invocation, isolated so swapping test runners is a one-class change."""

    def run(self) -> tuple[bool, str]:
        try:
            with UI.spinner("Running local test suite..."):
                result = subprocess.run(
                    ['pytest', '--maxfail=1', '--disable-warnings', '-q'],
                    capture_output=True, text=True, check=False,
                )
            return result.returncode == 0, result.stdout + result.stderr
        except FileNotFoundError:
            return False, "[-] Error: 'pytest' command not found on PATH."


class Environment:
    """Single provider for every external-system adapter. Command code depends
    on this, not on subprocess/os directly, so the whole tool stays testable
    and portable to a different OS/clipboard/test-runner with local changes."""

    def __init__(self) -> None:
        self.git = GitAdapter()
        self.clipboard = ClipboardAdapter()
        self.tests = TestRunner()


# =============================================================================
# 3. PLUGGABLE STATE & STORAGE MANAGER
#
# Single owner of .astra_state.json and .astra_history/: pruning, gitignore
# syncing, and secret filtering all happen here, uniformly, instead of being
# re-implemented per command.
# =============================================================================

class StorageManager:
    STATE_PATH = Path('.astra_state.json')
    HISTORY_DIR = Path('.astra_history')
    HISTORY_CAP = 10

    EXCLUDE_DIRS = {'.git', 'data', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', HISTORY_DIR.name}
    # Binary/compiled/archive artifacts — never useful as pasted "code" and,
    # for true binaries, unsafe to even open in text mode (garbage bytes via
    # errors='replace'). Deliberately broad: covers common object/library/
    # executable/archive/media formats, not just the ones a given test hits.
    EXCLUDE_EXTS = {
        '.db', '.pyc', '.pyo', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.ico',
        '.csv', '.parquet', '.tar', '.gz', '.bz2', '.xz', '.7z', '.rar',
        '.o', '.obj', '.a', '.lib', '.so', '.dll', '.dylib', '.class', '.jar',
        '.exe', '.bin', '.wasm', '.pdf', '.mp3', '.mp4', '.wav', '.mov',
    }

    FORBIDDEN_FILENAMES = {
        'secrets.env',
        'id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa',
    }
    FORBIDDEN_EXTENSIONS = {'.key', '.pem', '.cert', '.p12'}

    # Our own tooling/state — never part of packed/diffed project context.
    OWN_FILES = {THIS_SCRIPT, 'sync_bridge.py', 'local_agent.py', 'apply_patch.py', STATE_PATH.name}

    def __init__(self, env: Environment) -> None:
        self.env = env

    # -- .gitignore ----------------------------------------------------------

    def ensure_gitignored(self, entry: str) -> None:
        """Append `entry` to .gitignore if a .gitignore exists and doesn't
        already list it. Never creates a .gitignore from scratch — that's a
        project-level decision this tool shouldn't make unasked."""
        gitignore = Path('.gitignore')
        try:
            if gitignore.exists():
                if entry not in gitignore.read_text(encoding='utf-8'):
                    with gitignore.open('a', encoding='utf-8') as f:
                        f.write(f'\n{entry}\n')
        except Exception:
            pass  # non-critical — worst case it shows up in `git status`

    # -- state file ------------------------------------------------------------
    # Local bookkeeping only. Never stores diff/patch content or anything
    # from is_secret_file() candidates; just timestamps, the action name,
    # and a test pass/fail flag. Intended to be .gitignore'd.

    def load_state(self) -> dict:
        if not self.STATE_PATH.exists():
            return {}
        try:
            return json.loads(self.STATE_PATH.read_text(encoding='utf-8'))
        except Exception:
            return {}

    def save_state(self, action: str, tests_passed) -> None:
        state = {
            'last_action': action,
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'tests_passed': tests_passed,  # True / False / None (not run this action)
        }
        try:
            self.STATE_PATH.write_text(json.dumps(state, indent=2), encoding='utf-8')
        except Exception as e:
            UI.warn(f"Warning: could not write {self.STATE_PATH}: {e}")
        self.ensure_gitignored(self.STATE_PATH.name)

    # -- clipboard history -----------------------------------------------------
    # Every successful clipboard copy also archives a timestamped copy
    # locally, capped at HISTORY_CAP with automatic pruning, so an accidental
    # overwrite doesn't lose an earlier bundle or patch. Guardrails:
    # .astra_history/ is gitignored, excluded from pack's own file walk, and
    # hard-capped.

    def archive_to_history(self, text: str, label: str) -> None:
        try:
            self.HISTORY_DIR.mkdir(exist_ok=True)
            self.ensure_gitignored(self.HISTORY_DIR.name + '/')

            ts = time.strftime('%Y-%m-%d_%H-%M-%S')
            base = f"{label}_{ts}"
            candidate = self.HISTORY_DIR / f"{base}.txt"
            n = 1
            while candidate.exists():  # tiebreaker for same-second collisions
                n += 1
                candidate = self.HISTORY_DIR / f"{base}_{n}.txt"
            candidate.write_text(text, encoding='utf-8')

            # Prune down to the cap, oldest first, by filesystem mtime.
            entries = sorted(self.HISTORY_DIR.glob('*.txt'), key=lambda p: p.stat().st_mtime)
            while len(entries) > self.HISTORY_CAP:
                oldest = entries.pop(0)
                oldest.unlink(missing_ok=True)
        except Exception as e:
            UI.warn(f"Warning: could not archive to history: {e}")

    def list_history(self) -> list[Path]:
        """Most-recent-first, capped list of archived clipboard items."""
        if not self.HISTORY_DIR.exists():
            return []
        return sorted(self.HISTORY_DIR.glob('*.txt'), key=lambda p: p.stat().st_mtime, reverse=True)

    # -- secret filtering & file safety -----------------------------------------
    # Uniform gatekeeping used by pack, metrics, and the untracked-file walk
    # in sync/diff, so "what's safe to leave the machine" is defined once.

    def is_secret_file(self, path: Path) -> bool:
        if path.name.startswith('.env'):
            return True
        if path.name in self.FORBIDDEN_FILENAMES:
            return True
        if path.suffix in self.FORBIDDEN_EXTENSIONS:
            return True
        return False

    def list_candidate_files(self, root: Path) -> list[Path]:
        files = []
        for path in root.rglob('*'):
            if any(part in self.EXCLUDE_DIRS for part in path.parts):
                continue
            if path.is_file():
                files.append(path)
        return files

    def get_ignored_paths(self, root: Path, candidate_files: list[Path]) -> set[str]:
        if not self.env.git.is_repo(root):
            UI.warn("Warning: not a git repository — .gitignore filtering disabled, relying on the static backstop only.")
            return set()
        if not candidate_files:
            return set()
        try:
            return self.env.git.check_ignore(candidate_files)
        except Exception as e:
            UI.error(f"Failed to batch-check .gitignore patterns: {e}")
            return set()

    def is_safe_file(self, path: Path, ignored_paths: set[str]) -> bool:
        if path.name in self.OWN_FILES:
            return False
        if path.suffix in self.EXCLUDE_EXTS:
            return False
        if self.is_secret_file(path):
            UI.warn(f"Skipping potential secret file: {path}")
            return False
        if str(path) in ignored_paths:
            return False
        return True


# =============================================================================
# Application context — bundles env + storage so command handlers take one
# argument instead of threading globals through every call.
# =============================================================================

@dataclass
class AppContext:
    env: Environment
    storage: StorageManager

    def copy_to_clipboard(self, text: str, label: str = "copy", archive: bool = True) -> bool:
        if archive:
            self.storage.archive_to_history(text, label)
        return self.env.clipboard.copy(text)

    def read_clipboard(self) -> str:
        return self.env.clipboard.paste()


# ---------------------------------------------------------------------------
# Small stateless helpers shared across commands (no external I/O of their
# own, so they stay plain functions rather than adapter/storage methods).
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    return len(text) // 4


def estimate_tokens_by_chars(char_count: int) -> int:
    return char_count // 4


def print_prompt_block(message: str) -> None:
    """Print a clearly-delimited block telling the user exactly what to
    type/paste next, so there's nothing to remember or improvise."""
    UI.prompt_block(message)


def build_ascii_tree(paths: list[Path], root: Path = Path('.')) -> str:
    """Compact directory tree from a flat file list, for a quick structural
    overview at the top of the pack payload."""
    tree: dict = {}
    for p in paths:
        parts = p.relative_to(root).parts
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault('__files__', []).append(parts[-1])

    lines: list[str] = []

    def walk(node: dict, prefix: str = ''):
        dirs = sorted(k for k in node if k != '__files__')
        files = sorted(node.get('__files__', []))
        entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        for i, (name, is_dir) in enumerate(entries):
            connector = '└── ' if i == len(entries) - 1 else '├── '
            lines.append(f"{prefix}{connector}{name}{'/' if is_dir else ''}")
            if is_dir:
                extension = '    ' if i == len(entries) - 1 else '│   '
                walk(node[name], prefix + extension)

    walk(tree)
    return '\n'.join(lines) if lines else '(empty)'


def looks_like_diff(text: str) -> bool:
    """Heuristic pre-flight check, not a guarantee. Real validation still
    happens via `git apply --check` — this just catches the common mistake
    of pasting the wrong thing (or nothing) before we touch disk."""
    if not text.strip():
        return False
    return bool(DIFF_GIT_HEADER.search(text)) or bool(HUNK_HEADER.search(text))


def extract_patched_python_files(patch_content: str) -> list[Path]:
    """Pull the post-patch file paths out of a unified diff's '+++ b/...'
    lines, filtered to .py files that still exist (skips deleted files)."""
    paths = []
    for match in re.finditer(r'^\+\+\+ b/(.+)$', patch_content, re.MULTILINE):
        candidate = match.group(1).strip()
        if candidate == '/dev/null':
            continue  # file was deleted by this patch
        p = Path(candidate)
        if p.suffix == '.py' and p.exists():
            paths.append(p)
    return paths


def run_syntax_preflight(patch_content: str) -> bool:
    """Compile-check every .py file the patch touched. Returns False if any
    of them fail to compile — this only validates Python files; anything
    else the patch touched isn't covered by this check."""
    py_files = extract_patched_python_files(patch_content)
    if not py_files:
        return True

    failures = []
    for f in py_files:
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append((f, str(e)))

    if failures:
        UI.error(f"Syntax check FAILED on {len(failures)} of {len(py_files)} Python file(s):")
        for f, err in failures:
            print(f"    {f}: {err.splitlines()[-1] if err else 'compile error'}")
        UI.info("The patch is already applied. Run 'python astra.py rollback' to undo it.")
        return False

    UI.success(f"{len(py_files)} Python file(s) checked, syntax OK.")
    return True


def build_untracked_section(ctx: AppContext, root: Path = Path('.')) -> str:
    untracked = ctx.env.git.untracked_files(root)
    if not untracked:
        return ""
    parts = ["\n=== NEW / UNTRACKED FILES (not in git diff) ==="]
    for path in untracked:
        if not path.is_file():
            continue  # skip untracked directories, e.g. a fresh venv
        if path.name in ctx.storage.OWN_FILES:
            continue
        if path.suffix in ctx.storage.EXCLUDE_EXTS:
            continue
        if ctx.storage.is_secret_file(path):
            UI.warn(f"Skipping potential secret file (untracked): {path}")
            continue
        parts.append(f"\n---- NEW FILE: {path} ----")
        try:
            parts.append(path.read_text(encoding='utf-8', errors='replace'))
        except Exception as err:
            parts.append(f"[Error reading file: {err}]")
    return '\n'.join(parts)


def create_checkpoint(ctx: AppContext) -> bool:
    """Stash current tracked-file state under a labeled stash before a patch
    touches anything, so `rollback` has something specific to restore.

    Note: like `git diff`, `git stash` only covers tracked files by default —
    a patch can't touch a file it doesn't reference, so this is fine for
    rollback purposes, but it's not a snapshot of untracked files.
    """
    with UI.spinner("Creating checkpoint before apply..."):
        result = ctx.env.git.stash_push(CHECKPOINT_LABEL)
    if 'No local changes to save' in result.stdout:
        UI.info("Working tree was already clean — no checkpoint needed before this apply.")
        return False
    if result.returncode != 0:
        UI.warn(f"Warning: could not create a checkpoint: {result.stderr.strip()}")
        return False
    UI.success(f"Checkpoint saved ('{CHECKPOINT_LABEL}') — run 'python astra.py rollback' to undo this apply.")
    return True


def find_checkpoint_ref(ctx: AppContext) -> Optional[str]:
    result = ctx.env.git.stash_list()
    for line in result.stdout.splitlines():
        if CHECKPOINT_LABEL in line:
            return line.split(':', 1)[0].strip()  # e.g. "stash@{0}"
    return None


# =============================================================================
# Commands
# =============================================================================

# ---------------------------------------------------------------------------
# history / restore
# ---------------------------------------------------------------------------

@COMMANDS.register('history', "last 10 things copied to clipboard, with an index")
def cmd_history(ctx: AppContext, args: list[str]) -> None:
    entries = ctx.storage.list_history()
    if not entries:
        UI.info("No history yet — it fills in as you run pack/sync/diff.")
        return
    UI.info(f"Last {len(entries)} clipboard item(s) (most recent first):")
    for i, path in enumerate(entries, start=1):
        size_kb = path.stat().st_size / 1024
        mtime = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(path.stat().st_mtime))
        print(f"    {i}. {path.stem}  ({size_kb:.1f} KB, {mtime})")
    print("\n[>] Run 'python astra.py restore <n>' to put one back on your clipboard.")


@COMMANDS.register('restore', "put history item n back on the clipboard", arg_hint='<n>')
def cmd_restore(ctx: AppContext, args: list[str]) -> None:
    if not args:
        UI.error("Usage: python astra.py restore <n>   (see 'python astra.py history' for indices)")
        return
    try:
        index = int(args[0])
    except ValueError:
        UI.error("That's not a number. Run 'python astra.py history' to see valid indices.")
        return

    entries = ctx.storage.list_history()
    if not entries:
        UI.error("No history yet.")
        return
    if not (1 <= index <= len(entries)):
        UI.error(f"No item #{index}. Valid range: 1-{len(entries)}.")
        return

    chosen = entries[index - 1]
    ctx.copy_to_clipboard(chosen.read_text(encoding='utf-8'), archive=False)
    UI.success(f"Restored '{chosen.stem}' to your clipboard.")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@COMMANDS.register('status', "what you last ran, and whether tests were passing")
def cmd_status(ctx: AppContext, args: list[str]) -> None:
    state = ctx.storage.load_state()
    if not state:
        UI.info("No recorded state yet — run 'pack', 'sync', or 'apply' at least once.")
        return

    tests = state.get('tests_passed')
    tests_str = {True: 'PASSING', False: 'FAILING', None: 'not run'}.get(tests, 'unknown')
    changes_str = "Yes" if ctx.env.git.has_uncommitted_changes() else "No"

    print(f"Last action:        {state.get('last_action', 'unknown')}")
    print(f"When:                {state.get('timestamp', 'unknown')}")
    print(f"Tests:               {tests_str}")
    print(f"Uncommitted changes: {changes_str}")


# ---------------------------------------------------------------------------
# pack — full codebase
# ---------------------------------------------------------------------------

@COMMANDS.register('pack', "full codebase -> clipboard (task: debug/review/architecture)", arg_hint='[task]')
def cmd_pack(ctx: AppContext, args: list[str]) -> None:
    task = args[0] if args else None
    if task is not None and task not in PACK_PRESETS:
        UI.error(f"Unknown pack preset '{task}'. Valid options: {', '.join(PACK_PRESETS)}")
        UI.info("Nothing was packed — run again with a valid preset or no preset for the generic prompt.")
        return

    root = Path('.')
    with UI.spinner("Scanning project tree..."):
        candidates = ctx.storage.list_candidate_files(root)

    with UI.spinner("Resolving .gitignore patterns (batch mode)..."):
        ignored_paths = ctx.storage.get_ignored_paths(root, candidates)

    safe_paths = [p for p in candidates if ctx.storage.is_safe_file(p, ignored_paths)]
    tree = build_ascii_tree(safe_paths, root)

    bundle = ["=== CODEBASE BASELINE BUNDLE ===", "\n=== PROJECT STRUCTURE ===", tree]
    file_count = 0
    for path in safe_paths:
        bundle.append(f"\n\n==================== FILE: {path} ====================")
        try:
            bundle.append(path.read_text(encoding='utf-8', errors='replace'))
            file_count += 1
        except Exception as err:
            bundle.append(f"[Error reading file: {err}]")

    full_text = "\n".join(bundle)
    tokens = estimate_tokens(full_text)
    UI.success(f"Bundled {file_count} files (~{tokens:,} estimated tokens).")
    if tokens > 100_000:
        UI.warn("Warning: payload exceeds ~100k tokens. Consider 'python astra.py diff' instead.")

    ctx.copy_to_clipboard(full_text, label='pack')
    ctx.storage.save_state('pack', tests_passed=None)
    prompt = PACK_PRESETS.get(task) if task else (
        "Here's my current codebase baseline. I'd like your help with [describe the task].\n"
        "When you give me a fix, please reply with the change as a unified git diff."
    )
    print_prompt_block(prompt)


# ---------------------------------------------------------------------------
# metrics
# ---------------------------------------------------------------------------

@COMMANDS.register('metrics', "file/extension/token breakdown of what pack would send")
def cmd_metrics(ctx: AppContext, args: list[str]) -> None:
    """Shows what `pack` would actually send, before you send it — per-extension
    file counts and a total token estimate, using the same filtering pack uses."""
    root = Path('.')
    candidates = ctx.storage.list_candidate_files(root)
    ignored_paths = ctx.storage.get_ignored_paths(root, candidates)

    counts: dict[str, int] = {}
    total_chars = 0
    secret_skipped = 0

    for path in candidates:
        if ctx.storage.is_secret_file(path):
            secret_skipped += 1
            continue
        if not ctx.storage.is_safe_file(path, ignored_paths):
            continue
        ext = path.suffix or '(no extension)'
        counts[ext] = counts.get(ext, 0) + 1
        try:
            total_chars += path.stat().st_size
        except OSError:
            pass

    if not counts:
        UI.info("Nothing to pack — check you're in the right directory.")
        return

    UI.info("What 'pack' would currently send:")
    for ext, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {ext:<16} {count}")
    total_files = sum(counts.values())
    tokens = estimate_tokens_by_chars(total_chars)
    print(f"    {'—' * 24}")
    print(f"    {total_files} files, ~{tokens:,} estimated tokens")
    if secret_skipped:
        UI.warn(f"{secret_skipped} secret file(s) excluded from this count.")
    if tokens > 100_000:
        UI.warn("That would exceed ~100k tokens — consider 'python astra.py diff' instead of a full pack.")


# ---------------------------------------------------------------------------
# sync / loop — tests + diff (the debugging loop)
# ---------------------------------------------------------------------------

@COMMANDS.register('sync', "tests + git diff + untracked files -> clipboard")
def cmd_sync(ctx: AppContext, args: list[str], precomputed: Optional[tuple] = None) -> bool:
    """precomputed, if given, is (success, test_log) from a test run the
    caller already did — lets `auto` avoid running pytest twice."""
    if precomputed is not None:
        success, test_log = precomputed
    else:
        success, test_log = ctx.env.tests.run()

    diff_text = ctx.env.git.diff() or "No uncommitted changes to tracked files."
    untracked_section = build_untracked_section(ctx)

    payload = "=== LOCAL AGENT STATE REPORT ===\n"
    payload += f"Tests Passed: {success}\n\n"
    payload += f"=== TEST LOGS ===\n{test_log}\n\n"
    payload += f"=== GIT DIFF (tracked files) ===\n{diff_text}\n"
    payload += untracked_section

    ctx.copy_to_clipboard(payload, label='sync')
    ctx.storage.save_state('sync', tests_passed=success)

    if success:
        print_prompt_block(
            "Tests are passing. Here's my current diff — could you review it "
            "for anything worth improving before I commit?"
        )
    else:
        print_prompt_block(
            "My tests are failing — here's the actual test output and my current diff. "
            "Please diagnose the failure and reply with a fix as a unified git diff."
        )
    return success


@COMMANDS.register('loop', "sync, and if tests fail, walk straight into the prompt")
def cmd_loop(ctx: AppContext, args: list[str]) -> None:
    """Runs sync; if tests are already failing, this IS the debug hand-off —
    nothing extra to chain. If they're passing, says so and stops rather than
    manufacturing busywork."""
    UI.info("Running the check-and-report loop...")
    success = cmd_sync(ctx, args)
    if success:
        UI.success("Tests are passing — nothing to hand off. Go build the next thing.")
    else:
        UI.tip("Tests are failing — the report above is ready to paste in as-is.")


# ---------------------------------------------------------------------------
# diff — lightweight, no test run
# ---------------------------------------------------------------------------

@COMMANDS.register('diff', "just git diff -> clipboard (lightweight review)")
def cmd_diff(ctx: AppContext, args: list[str]) -> None:
    try:
        diff_text = ctx.env.git.diff() or "No uncommitted local changes found in git."
        untracked_section = build_untracked_section(ctx)
        output = f"=== LOCAL GIT DIFF DELTA ===\n{diff_text}{untracked_section}"
        ctx.copy_to_clipboard(output, label='diff')
        ctx.storage.save_state('diff', tests_passed=None)
        UI.success(f"Git diff copied (~{estimate_tokens(output):,} tokens).")
        if untracked_section:
            UI.info("Included new/untracked files not yet tracked by git.")
        print_prompt_block(
            "Here's what I just changed locally. Take a look and let me know if it's correct, "
            "or reply with a fix as a unified git diff if something's off."
        )
    except Exception as e:
        UI.error(f"Failed to run git diff: {e}")


# ---------------------------------------------------------------------------
# apply — validated clipboard diff -> git apply
# ---------------------------------------------------------------------------

@COMMANDS.register('apply', "validated clipboard or file diff -> applied to repo", arg_hint='[file]')
def cmd_apply(ctx: AppContext, args: list[str]) -> None:
    if args:
        patch_path_arg = Path(args[0])
        if not patch_path_arg.exists():
            UI.error(f"No such file: {patch_path_arg}")
            return
        UI.info(f"Reading patch from file: {patch_path_arg}...")
        raw_content = patch_path_arg.read_text(encoding='utf-8')
    else:
        UI.info("Reading patch from clipboard...")
        raw_content = ctx.read_clipboard()

    if not raw_content.strip():
        source = "file" if args else "clipboard"
        UI.error(f"Nothing to apply — your {source} is empty.")
        if not args:
            UI.info("Did you mean to run 'python astra.py sync' first to get a fix from the model?")
        return

    # Strip markdown fences / conversational prose around the diff, in case
    # the raw paste (clipboard or file) has surrounding chat formatting.
    patch_lines, in_patch = [], False
    for line in raw_content.splitlines():
        if line.startswith("diff --git"):
            in_patch = True
        if in_patch:
            if line.strip() == "```":
                break
            patch_lines.append(line)
    patch_content = "\n".join(patch_lines) if in_patch else raw_content

    if not looks_like_diff(patch_content):
        UI.error("Clipboard/file does not look like a git patch (no 'diff --git' or '@@' hunk header found).")
        UI.info("Did you copy the model's code block properly? Make sure you copied the")
        print("    diff itself, not surrounding prose, and that you asked for a unified diff.")
        return

    if not ctx.env.git.is_repo():
        UI.error("No .git directory found here — run this from your project root.")
        return

    patch_path = Path("temp.patch")
    patch_path.write_text(patch_content, encoding='utf-8')

    try:
        with UI.spinner("Verifying patch with dry-run check..."):
            check_res = ctx.env.git.apply_check(patch_path)
        if check_res.returncode != 0:
            UI.error("Patch verification failed! The context lines do not match cleanly:")
            print(check_res.stderr)
            UI.info("Tip: ask the model to regenerate the diff, or check for soft-wrapped lines in the paste.")
            return

        # Checkpoint AFTER the dry-run passes (no point stashing for a patch
        # that was never going to apply) but BEFORE the real, file-touching apply.
        create_checkpoint(ctx)

        with UI.spinner("Applying patch to workspace..."):
            apply_res = ctx.env.git.apply(patch_path)
        if apply_res.returncode == 0:
            UI.success("Patch applied successfully to workspace!")
            syntax_ok = run_syntax_preflight(patch_content)
            ctx.storage.save_state('apply', tests_passed=None)
            if not syntax_ok:
                return  # rollback tip already printed by run_syntax_preflight
            answer = UI.ask("Run tests now to confirm it works? (y/n): ").strip().lower()
            if answer == 'y':
                cmd_sync(ctx, [])
            else:
                UI.tip("Okay — run 'python astra.py sync' whenever you're ready to check.")
        else:
            UI.error(f"Unexpected apply failure:\n{apply_res.stderr}")
    finally:
        patch_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------

@COMMANDS.register('rollback', "undo the last apply's checkpoint")
def cmd_rollback(ctx: AppContext, args: list[str]) -> None:
    if not ctx.env.git.is_repo():
        UI.error("No .git directory found here — run this from your project root.")
        return
    ref = find_checkpoint_ref(ctx)
    if not ref:
        UI.error(f"No '{CHECKPOINT_LABEL}' stash found. Nothing to roll back — "
                 "either you haven't run 'apply' yet, or you already rolled back.")
        return

    # Rollback means "discard whatever the patch did and restore the
    # pre-patch state" — so the current (post-patch) working tree changes
    # are expected to be thrown away here, not merged with the stash.
    UI.warn("This will discard the current changes in your working tree (the applied patch)")
    print(f"    and restore the state saved in '{CHECKPOINT_LABEL}'.")
    confirm = UI.ask("Continue? (y/n): ").strip().lower()
    if confirm != 'y':
        UI.info("Rollback cancelled. Your stash is still there if you change your mind.")
        return

    with UI.spinner("Restoring working tree..."):
        reset_res = ctx.env.git.reset_hard_head()
    if reset_res.returncode != 0:
        UI.error(f"Could not clear the working tree before rollback: {reset_res.stderr.strip()}")
        print(f"    Your checkpoint is still safe in the stash ({ref}) — nothing was lost.")
        return

    with UI.spinner("Restoring checkpoint..."):
        result = ctx.env.git.stash_pop(ref)
    if result.returncode == 0:
        UI.success(f"Rolled back to the state before the last apply (popped {ref}).")
    else:
        UI.error(f"Rollback failed: {result.stderr.strip()}")
        print(f"    Your checkpoint is still in the stash ({ref}) — resolve manually with 'git stash list'.")


# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------

@COMMANDS.register('clean', "remove temp.patch and __pycache__ clutter")
def cmd_clean(ctx: AppContext, args: list[str]) -> None:
    removed = []
    temp = Path('temp.patch')
    if temp.exists():
        temp.unlink()
        removed.append(str(temp))
    for cache_dir in Path('.').rglob('__pycache__'):
        if any(part in ctx.storage.EXCLUDE_DIRS for part in cache_dir.parts if part != '__pycache__'):
            continue
        shutil.rmtree(cache_dir, ignore_errors=True)
        removed.append(str(cache_dir))
    if removed:
        UI.success(f"Cleaned up {len(removed)} item(s):")
        for r in removed:
            print(f"    {r}")
    else:
        UI.info("Nothing to clean.")


# =============================================================================
# 4. EXTENSIBLE RULE PIPELINE FOR THE SMART DISPATCHER (`auto`)
#
# `auto` walks an ordered, appendable list of rule functions. Each rule
# inspects the shared AutoState and either claims the turn (does something
# and returns True, ending the pipeline) or declines (returns False, so the
# next rule gets a look). Adding a new heuristic is one @auto_rule function —
# no branching logic to thread it through.
# =============================================================================

@dataclass
class AutoState:
    ctx: AppContext
    state: dict
    clip: str = ""
    tests_passed: Optional[bool] = None
    test_log: str = ""


AUTO_RULES: list[Callable[[AutoState], bool]] = []


def auto_rule(func: Callable[[AutoState], bool]) -> Callable[[AutoState], bool]:
    """Appends `func` to the ordered rule pipeline. Rules run in registration
    order; the first one to return True stops the pipeline for this run."""
    AUTO_RULES.append(func)
    return func


@auto_rule
def rule_pending_patch(a: AutoState) -> bool:
    """A pending patch on the clipboard is almost always why you're back at
    the terminal — handle that before anything else touches the clipboard
    and overwrites it."""
    a.clip = a.ctx.read_clipboard()
    if a.clip.strip() and looks_like_diff(a.clip):
        UI.info("Detected what looks like a patch on your clipboard.")
        answer = UI.ask("Apply it now? (y/n): ").strip().lower()
        if answer == 'y':
            cmd_apply(a.ctx, [])
            return True
        UI.info("Skipping. Note: continuing past this will overwrite that clipboard content.")
    return False


@auto_rule
def rule_failing_tests(a: AutoState) -> bool:
    """Establish live state with a single test run; a failure is always the
    next thing to act on."""
    success, log = a.ctx.env.tests.run()
    a.tests_passed = success
    a.test_log = log
    if not success:
        UI.tip("Tests are failing — packaging the failure report now.")
        cmd_sync(a.ctx, [], precomputed=(success, log))
        return True
    return False


@auto_rule
def rule_uncommitted_changes(a: AutoState) -> bool:
    has_changes = a.ctx.env.git.has_uncommitted_changes() or bool(a.ctx.env.git.untracked_files())
    if has_changes:
        UI.success("Tests are passing, and you have uncommitted changes.")
        answer = UI.ask("Copy a diff for review now? (y/n): ").strip().lower()
        if answer == 'y':
            cmd_diff(a.ctx, [])
        else:
            UI.info("Okay — run 'python astra.py diff' or 'sync' whenever you're ready.")
        return True
    return False


@auto_rule
def rule_nothing_to_do(a: AutoState) -> bool:
    """Backstop rule — always claims, so the pipeline always ends cleanly."""
    UI.success("Tests are passing and the working tree is clean. Nothing to do.")
    return True


@COMMANDS.register('auto', "smart dispatcher: inspects state, tells you what to do", aliases=('do',))
def cmd_auto(ctx: AppContext, args: list[str]) -> None:
    """Never applies or overwrites anything without confirmation. Walks
    AUTO_RULES in order until one of them claims the turn."""
    state = ctx.storage.load_state()
    if state:
        tests = state.get('tests_passed')
        tests_str = {True: 'passing', False: 'failing', None: 'not recorded'}.get(tests, 'unknown')
        UI.info(f"Last recorded action: {state.get('last_action', 'unknown')} "
                f"({state.get('timestamp', 'unknown')}) — tests were {tests_str}.")
    else:
        UI.info("No recorded state yet — this looks like a fresh start.")

    auto_state = AutoState(ctx=ctx, state=state)
    for rule in AUTO_RULES:
        if rule(auto_state):
            return


# =============================================================================
# entrypoint
# =============================================================================

def build_context() -> AppContext:
    env = Environment()
    storage = StorageManager(env)
    return AppContext(env=env, storage=storage)


def main() -> None:
    ctx = build_context()

    # Bare invocation -> the smart dispatcher, not just the help text.
    if len(sys.argv) < 2:
        cmd_auto(ctx, [])
        return

    arg = sys.argv[1]

    if arg in ('-h', '--help'):
        print(COMMANDS.usage())
        return

    spec = COMMANDS.get(arg)
    if spec is None:
        UI.error(f"Unknown command '{arg}'.\n")
        print(COMMANDS.usage())
        sys.exit(1)

    spec.handler(ctx, sys.argv[2:])


if __name__ == '__main__':
    main()
