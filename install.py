#!/usr/bin/env python3
"""
Transcript Bot — Setup & Installer
====================================
Handles full installation on macOS (dev) and Ubuntu (production).
Uses only Python stdlib — safe to run before the project venv exists.

Usage:
  python3 install.py            Full interactive setup
  python3 install.py --check    Show current config values and exit
  python3 install.py --restart  (Ubuntu only) Restart the systemd service and exit
"""

import argparse
import getpass
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

# ─────────────────────────────────────────────────────────────
# ANSI COLOR CODES
# ─────────────────────────────────────────────────────────────
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
WHITE  = "\033[97m"


# ─────────────────────────────────────────────────────────────
# PATH CONSTANTS
# ─────────────────────────────────────────────────────────────
PROJECT_DIR  = pathlib.Path(__file__).parent.resolve()
ENV_FILE     = PROJECT_DIR / ".env"
SYSTEMD_SRC  = PROJECT_DIR / "systemd" / "transcript-bot.service"
OPT_DIR      = pathlib.Path("/opt/transcript-bot")
OPT_ENV      = OPT_DIR / ".env"
SYSTEMD_DEST = pathlib.Path("/etc/systemd/system/transcript-bot.service")
SERVICE_NAME = "transcript-bot"
SERVICE_USER = "transcript-bot"


# ─────────────────────────────────────────────────────────────
# ENV FIELD DEFINITIONS
# Each dict drives one step of the interactive config wizard.
# ─────────────────────────────────────────────────────────────
ENV_FIELDS = [
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "label": "Telegram Bot Token",
        "required": True,
        "sensitive": True,
        "default": "",
        "choices": None,
        "help": (
            "You need a bot token from Telegram's @BotFather.\n"
            "  1. Open Telegram and search for @BotFather\n"
            "  2. Send:  /newbot\n"
            "  3. Choose a display name (e.g. 'My Transcript Bot')\n"
            "  4. Choose a username ending in 'bot' (e.g. 'mytranscript_bot')\n"
            "  5. BotFather will reply with your token — copy it here.\n"
            "     It looks like:  1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ123456789\n"
            "\n"
            "  Keep this token private — anyone with it controls your bot."
        ),
        "validate": "token",
    },
    {
        "key": "ALLOWED_USER_IDS",
        "label": "Allowed Telegram User IDs",
        "required": True,
        "sensitive": False,
        "default": "",
        "choices": None,
        "help": (
            "Your Telegram user ID — controls who can send transcripts to this bot.\n"
            "  1. Open Telegram and search for @userinfobot\n"
            "  2. Send any message to it\n"
            "  3. It replies with your numeric ID (e.g. 123456789)\n"
            "\n"
            "  For multiple users, separate with commas:  111111111,222222222"
        ),
        "validate": "user_ids",
    },
    {
        "key": "WHISPER_MODEL",
        "label": "Whisper Model Size",
        "required": False,
        "sensitive": False,
        "default": "small",
        "choices": ["tiny", "base", "small", "medium", "large-v2", "large-v3"],
        "help": (
            "Controls the accuracy/speed tradeoff for local Whisper transcription.\n"
            "  tiny     ~1 GB RAM  — fastest, lower accuracy (good for Mac dev)\n"
            "  base     ~1 GB RAM  — fast, decent accuracy\n"
            "  small    ~2 GB RAM  — good balance  ← recommended default\n"
            "  medium   ~5 GB RAM  — high accuracy, noticeably slower\n"
            "  large-v2 ~10 GB RAM — best accuracy, slow without GPU\n"
            "  large-v3 ~10 GB RAM — latest large model, same resources as large-v2\n"
            "\n"
            "  On Mac (CPU only): 'tiny' or 'base' recommended for dev speed."
        ),
        "validate": "whisper_model",
    },
    {
        "key": "WHISPER_COMPUTE_TYPE",
        "label": "Whisper Compute Type",
        "required": False,
        "sensitive": False,
        "default": "",
        "choices": None,
        "help": (
            "Leave blank to auto-detect (strongly recommended).\n"
            "  Auto selects: float16 on NVIDIA GPU, int8 on CPU\n"
            "  Only change this if you're tuning performance and know your hardware.\n"
            "  Valid values: float16, int8, int8_float16, float32"
        ),
        "validate": None,
    },
    {
        "key": "WHISPER_LANGUAGE",
        "label": "Whisper Language Hint",
        "required": False,
        "sensitive": False,
        "default": "",
        "choices": None,
        "help": (
            "Leave blank to auto-detect the language (recommended).\n"
            "  Enter an ISO 639-1 language code to force a specific language.\n"
            "  Examples: en  es  fr  de  ja  zh  pt  ko\n"
            "  Auto-detect is reliable and handles mixed-language content well."
        ),
        "validate": None,
    },
    {
        "key": "WORK_DIR",
        "label": "Working Directory",
        "required": False,
        "sensitive": False,
        "default": "/tmp/transcript_bot",
        "choices": None,
        "help": (
            "Temporary directory used to store audio files during transcription.\n"
            "  Files are automatically cleaned up after each transcription.\n"
            "  The default is fine for almost all setups."
        ),
        "validate": None,
    },
    {
        "key": "LOG_LEVEL",
        "label": "Log Level",
        "required": False,
        "sensitive": False,
        "default": "INFO",
        "choices": ["DEBUG", "INFO", "WARNING", "ERROR"],
        "help": (
            "Controls how much the bot logs.\n"
            "  DEBUG   — verbose (shows all internals, good for troubleshooting)\n"
            "  INFO    — normal operation messages  ← recommended\n"
            "  WARNING — only issues worth noting\n"
            "  ERROR   — only failures"
        ),
        "validate": "log_level",
    },
]

FIELD_COMMENTS = {
    "TELEGRAM_BOT_TOKEN":   "# Required: your Telegram bot token from @BotFather",
    "ALLOWED_USER_IDS":     "# Required: comma-separated Telegram user IDs (get yours from @userinfobot)",
    "WHISPER_MODEL":        "# Whisper model: tiny, base, small, medium, large-v2, large-v3",
    "WHISPER_COMPUTE_TYPE": "# Compute type: leave blank for auto-detection (float16 on GPU, int8 on CPU)",
    "WHISPER_LANGUAGE":     "# Language hint (e.g. en). Leave blank for auto-detect.",
    "WORK_DIR":             "# Temporary working directory for audio files",
    "LOG_LEVEL":            "# Log level: DEBUG, INFO, WARNING, ERROR",
}


# ─────────────────────────────────────────────────────────────
# OUTPUT HELPERS
# ─────────────────────────────────────────────────────────────

def hr(char="─", width=62):
    print(f"{DIM}{char * width}{RESET}")

def print_header(msg: str):
    print()
    hr("═")
    print(f"{BOLD}{BLUE}  {msg}{RESET}")
    hr("═")
    print()

def print_step(msg: str):
    print(f"{BLUE}  ──▶ {msg}{RESET}")

def print_ok(msg: str):
    print(f"{GREEN}  ✓  {msg}{RESET}")

def print_warn(msg: str):
    print(f"{YELLOW}  ⚠  {msg}{RESET}")

def print_err(msg: str):
    print(f"{RED}  ✗  {msg}{RESET}", file=sys.stderr)

def print_info(msg: str):
    print(f"{CYAN}     {msg}{RESET}")

def c(text: str, code: str) -> str:
    return f"{code}{text}{RESET}"


# ─────────────────────────────────────────────────────────────
# ENV FILE HELPERS
# ─────────────────────────────────────────────────────────────

def load_dotenv_raw(path: pathlib.Path) -> dict:
    """Parse a .env file into a plain dict without touching os.environ."""
    result = {}
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
            value = value[1:-1]
        if key:
            result[key] = value
    return result


def write_dotenv(path: pathlib.Path, values: dict):
    """Write a clean .env file preserving field order and comments."""
    lines = []
    for spec in ENV_FIELDS:
        key = spec["key"]
        comment = FIELD_COMMENTS.get(key, "")
        if comment:
            lines.append(comment)
        val = values.get(key, spec.get("default", ""))
        if " " in val:
            val = f'"{val}"'
        lines.append(f"{key}={val}")
        lines.append("")  # blank line between fields
    path.write_text("\n".join(lines), encoding="utf-8")


# ─────────────────────────────────────────────────────────────
# VALIDATORS
# ─────────────────────────────────────────────────────────────

def validate_token(val: str):
    if not re.match(r"^\d+:[A-Za-z0-9_-]{35,}$", val):
        return (
            "Token format should be: 123456789:ABCdefGHI...\n"
            "       (digits, colon, 35+ alphanumeric chars — get it from @BotFather)"
        )
    return None

def validate_user_ids(val: str):
    parts = [p.strip() for p in val.split(",") if p.strip()]
    if not parts:
        return "At least one numeric user ID is required."
    for p in parts:
        if not p.isdigit():
            return f"'{p}' is not a valid numeric Telegram user ID."
    return None

def validate_whisper_model(val: str):
    valid = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
    if val not in valid:
        return f"Must be one of: {', '.join(valid)}"
    return None

def validate_log_level(val: str):
    valid = ["DEBUG", "INFO", "WARNING", "ERROR"]
    if val not in valid:
        return f"Must be one of: {', '.join(valid)}"
    return None

VALIDATORS = {
    "token":         validate_token,
    "user_ids":      validate_user_ids,
    "whisper_model": validate_whisper_model,
    "log_level":     validate_log_level,
}


# ─────────────────────────────────────────────────────────────
# INTERACTIVE PROMPTING
# ─────────────────────────────────────────────────────────────

def prompt_field(spec: dict, current_values: dict) -> str:
    """
    Prompt the user for a single config field.
    If a current value exists, offer to keep it (re-run awareness).
    Loops until valid input is provided.
    """
    key      = spec["key"]
    label    = spec["label"]
    required = spec["required"]
    sensitive = spec["sensitive"]
    default  = spec.get("default", "")
    validate_key = spec.get("validate")
    choices  = spec.get("choices")
    current  = current_values.get(key, "")

    print()
    hr()
    print(f"{BOLD}{WHITE}  {label}{RESET}  {DIM}({key}){RESET}")
    if required:
        print(f"  {RED}required{RESET}")

    # Print help text
    help_text = spec.get("help", "")
    if help_text:
        print()
        for line in help_text.strip().splitlines():
            print(f"  {DIM}{line}{RESET}")

    if choices:
        print(f"\n  {DIM}Options: {', '.join(choices)}{RESET}")

    # Re-run path: offer to keep existing value
    if current:
        display = f"...{current[-4:]}" if sensitive else current
        print()
        keep = input(
            f"  Current: {CYAN}{display}{RESET}  Keep? {BOLD}[Y/n]{RESET}: "
        ).strip().lower()
        if keep in ("", "y", "yes"):
            return current
        print()

    # Prompt loop
    if default and not required:
        hint = f" {DIM}[default: {default}]{RESET}"
    elif choices:
        hint = f" {DIM}[{'/'.join(choices)}]{RESET}"
    else:
        hint = ""

    prompt_str = f"\n  Enter {label}{hint}: "
    if required:
        prompt_str = f"\n  Enter {label} {RED}(required){RESET}: "

    while True:
        try:
            if sensitive:
                value = getpass.getpass(prompt=prompt_str).strip()
            else:
                value = input(prompt_str).strip()
        except (EOFError, OSError):
            # Non-TTY fallback
            print_warn("Non-interactive terminal detected, falling back to plain input.")
            value = input(prompt_str).strip()

        # Normalize case for certain fields
        if validate_key == "whisper_model":
            value = value.lower()
        elif validate_key == "log_level":
            value = value.upper()

        # Blank input handling
        if not value:
            if default:
                value = default
                print_info(f"Using default: {value}")
            elif not required:
                return ""  # blank optional field is valid
            else:
                print_err("This field is required — please enter a value.")
                continue

        # Validate
        if value and validate_key:
            validator = VALIDATORS.get(validate_key)
            if validator:
                error = validator(value)
                if error:
                    print_err(f"Invalid input: {error}")
                    continue

        return value


# ─────────────────────────────────────────────────────────────
# SYSTEM HELPERS
# ─────────────────────────────────────────────────────────────

def detect_platform() -> str:
    s = platform.system().lower()
    if s == "darwin":
        return "macos"
    if s == "linux":
        return "linux"
    return s

def check_command(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run_cmd(
    args: list,
    *,
    check: bool = True,
    capture: bool = False,
    cwd: pathlib.Path | None = None,
    error_hint: str = "",
) -> subprocess.CompletedProcess:
    display = " ".join(str(a) for a in args)
    print_step(f"Running: {display}")
    result = subprocess.run(
        args,
        capture_output=capture,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    if check and result.returncode != 0:
        print_err(f"Command failed (exit {result.returncode}): {display}")
        if result.stderr and result.stderr.strip():
            print(f"\n  {DIM}{result.stderr.strip()}{RESET}\n", file=sys.stderr)
        if error_hint:
            print_warn(f"Hint: {error_hint}")
        sys.exit(1)
    return result


# ─────────────────────────────────────────────────────────────
# DEPENDENCY INSTALLATION
# ─────────────────────────────────────────────────────────────

def install_homebrew_deps():
    print_header("Installing macOS Dependencies")
    if not check_command("brew"):
        print_err("Homebrew is not installed.")
        print_info("Install it from: https://brew.sh")
        print_info("Then re-run this script.")
        sys.exit(1)
    print_ok("Homebrew found")

    if check_command("ffmpeg"):
        print_ok("ffmpeg already installed — skipping")
    else:
        print_step("Installing ffmpeg via Homebrew (this may take a moment)...")
        run_cmd(
            ["brew", "install", "ffmpeg"],
            error_hint="Run 'brew install ffmpeg' manually to see detailed output.",
        )
        print_ok("ffmpeg installed")


def install_ubuntu_deps():
    print_header("Installing Ubuntu/Linux Dependencies")
    print_step("Updating apt package list...")
    run_cmd(
        ["sudo", "apt-get", "update", "-y"],
        error_hint="Check that you have sudo access and network connectivity.",
    )

    to_install = []

    if not check_command("ffmpeg"):
        to_install.append("ffmpeg")
    else:
        print_ok("ffmpeg already installed")

    # Check for Python 3.11+
    py_found = False
    for candidate in ("python3.11", "python3.12", "python3.13"):
        if check_command(candidate):
            print_ok(f"{candidate} found")
            py_found = True
            break
    if not py_found:
        to_install += ["python3.11", "python3.11-venv", "python3.11-dev"]

    if to_install:
        print_step(f"Installing: {' '.join(to_install)}")
        run_cmd(
            ["sudo", "apt-get", "install", "-y"] + to_install,
            error_hint=(
                "Try manually: sudo apt-get install "
                + " ".join(to_install)
            ),
        )
        print_ok(f"Installed: {' '.join(to_install)}")


def install_uv():
    print_header("Installing uv (Python Package Manager)")

    if check_command("uv"):
        print_ok("uv already installed — skipping")
        return

    print_step("Downloading and running the uv installer...")
    installer_url = "https://astral.sh/uv/install.sh"

    try:
        with urllib.request.urlopen(installer_url) as resp:
            script = resp.read().decode()
    except Exception as e:
        print_err(f"Failed to download uv installer: {e}")
        print_info("Install uv manually: https://docs.astral.sh/uv/getting-started/installation/")
        sys.exit(1)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False) as f:
        f.write(script)
        tmp_path = f.name

    try:
        os.chmod(tmp_path, 0o700)
        result = subprocess.run(["sh", tmp_path], text=True)
        if result.returncode != 0:
            print_err("uv installer script returned a non-zero exit code.")
            sys.exit(1)
    finally:
        os.unlink(tmp_path)

    # Patch PATH so uv is findable in this process
    home = pathlib.Path.home()
    for candidate_dir in [
        home / ".cargo" / "bin",
        home / ".local" / "bin",
    ]:
        if (candidate_dir / "uv").exists():
            os.environ["PATH"] = str(candidate_dir) + ":" + os.environ.get("PATH", "")
            break

    if not check_command("uv"):
        print_warn("uv was installed but is not yet in PATH.")
        print_info("You may need to open a new terminal or run:")
        print_info("  source ~/.bashrc   (Linux)")
        print_info("  source ~/.zshrc    (macOS)")
        print_info("Then re-run: python3 setup.py")
        sys.exit(1)

    print_ok("uv installed successfully")


def run_uv_sync(project_dir: pathlib.Path):
    print_header("Installing Python Dependencies")
    run_cmd(
        ["uv", "sync"],
        cwd=project_dir,
        error_hint=(
            "Check that pyproject.toml is valid and you have network access. "
            "Try running 'uv sync' manually from the project directory."
        ),
    )
    print_ok("Python dependencies installed")


# ─────────────────────────────────────────────────────────────
# UBUNTU SYSTEM SETUP
# ─────────────────────────────────────────────────────────────

def create_system_user():
    result = run_cmd(["id", SERVICE_USER], check=False, capture=True)
    if result.returncode == 0:
        print_ok(f"System user '{SERVICE_USER}' already exists")
        return
    print_step(f"Creating system user '{SERVICE_USER}'...")
    run_cmd(
        [
            "sudo", "useradd",
            "--system",
            "--no-create-home",
            "--shell", "/usr/sbin/nologin",
            SERVICE_USER,
        ],
        error_hint=f"Try: sudo useradd --system --no-create-home {SERVICE_USER}",
    )
    print_ok(f"System user '{SERVICE_USER}' created")


def deploy_to_opt(project_dir: pathlib.Path):
    print_step(f"Deploying project files to {OPT_DIR}...")
    run_cmd(["sudo", "mkdir", "-p", str(OPT_DIR)])

    exclude_args = [
        "--exclude=.git",
        "--exclude=__pycache__",
        "--exclude=.venv",
        "--exclude=dist",
        "--exclude=build",
        "--exclude=*.egg-info",
        "--exclude=*.m4a",
        "--exclude=*.mp3",
        "--exclude=*.wav",
        "--exclude=*_transcript.txt",
        "--exclude=.env",
        "--exclude=bot.log",
    ]

    if check_command("rsync"):
        run_cmd(
            ["sudo", "rsync", "-a", "--delete"] + exclude_args
            + [str(project_dir) + "/", str(OPT_DIR) + "/"],
            error_hint="Check sudo permissions on /opt/",
        )
    else:
        # rsync not available — fall back to cp
        print_warn("rsync not found — using cp (slower, less precise)")
        run_cmd(
            ["sudo", "cp", "-r", str(project_dir) + "/.", str(OPT_DIR)],
            error_hint="Could not copy files to /opt/transcript-bot/",
        )

    run_cmd(
        ["sudo", "chown", "-R", f"{SERVICE_USER}:{SERVICE_USER}", str(OPT_DIR)],
        error_hint=f"Could not set ownership of {OPT_DIR}",
    )
    print_ok(f"Files deployed to {OPT_DIR}")


def write_opt_env(values: dict):
    """Write the .env file to /opt with restricted permissions."""
    print_step(f"Writing .env to {OPT_ENV}...")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".env", delete=False, encoding="utf-8"
    ) as f:
        tmp_path = f.name
        for spec in ENV_FIELDS:
            key = spec["key"]
            val = values.get(key, spec.get("default", ""))
            if " " in val:
                val = f'"{val}"'
            f.write(f"{key}={val}\n")

    try:
        run_cmd(["sudo", "cp", tmp_path, str(OPT_ENV)])
    finally:
        os.unlink(tmp_path)

    run_cmd(["sudo", "chown", f"{SERVICE_USER}:{SERVICE_USER}", str(OPT_ENV)])
    run_cmd(["sudo", "chmod", "640", str(OPT_ENV)])
    print_ok(f".env written to {OPT_ENV} (permissions: 640)")


def run_uv_sync_opt():
    """Create the production venv in /opt/transcript-bot."""
    print_step(f"Running uv sync in {OPT_DIR}...")
    # Pass current user's PATH so uv is found even under sudo
    env_path = os.environ.get("PATH", "")
    run_cmd(
        ["sudo", "env", f"PATH={env_path}", "uv", "sync",
         "--project", str(OPT_DIR)],
        error_hint=(
            "uv sync failed in /opt/. "
            "Try: sudo env PATH=$PATH uv sync --project /opt/transcript-bot"
        ),
    )
    # Fix ownership of the newly created .venv
    run_cmd(
        ["sudo", "chown", "-R", f"{SERVICE_USER}:{SERVICE_USER}",
         str(OPT_DIR / ".venv")],
    )
    print_ok(f"Production venv created at {OPT_DIR / '.venv'}")


def install_systemd_service():
    if not SYSTEMD_SRC.exists():
        print_err(f"Service file not found: {SYSTEMD_SRC}")
        print_info("Make sure you're running setup.py from the project directory.")
        sys.exit(1)

    print_step("Installing systemd service...")
    run_cmd(["sudo", "cp", str(SYSTEMD_SRC), str(SYSTEMD_DEST)])
    run_cmd(
        ["sudo", "systemctl", "daemon-reload"],
        error_hint="systemctl daemon-reload failed — check system logs",
    )
    run_cmd(
        ["sudo", "systemctl", "enable", SERVICE_NAME],
        error_hint=f"Could not enable {SERVICE_NAME}",
    )
    print_ok("systemd service installed and enabled")


def stop_service_if_running() -> bool:
    """Stop the service if it's active. Returns True if it was running."""
    result = run_cmd(
        ["sudo", "systemctl", "is-active", SERVICE_NAME],
        check=False, capture=True,
    )
    if result.stdout.strip() == "active":
        print_step(f"Service '{SERVICE_NAME}' is running — stopping before update...")
        run_cmd(
            ["sudo", "systemctl", "stop", SERVICE_NAME],
            error_hint=f"Could not stop {SERVICE_NAME}",
        )
        print_ok("Service stopped")
        return True
    return False


def enable_and_start_service():
    print_step(f"Starting service '{SERVICE_NAME}'...")
    run_cmd(
        ["sudo", "systemctl", "start", SERVICE_NAME],
        error_hint=(
            f"Check logs: sudo journalctl -u {SERVICE_NAME} -n 50 --no-pager"
        ),
    )
    time.sleep(2)
    check_service_status()


def check_service_status() -> bool:
    result = run_cmd(
        ["sudo", "systemctl", "is-active", SERVICE_NAME],
        check=False, capture=True,
    )
    status = result.stdout.strip()
    if status == "active":
        print_ok(f"Service '{SERVICE_NAME}' is ACTIVE ✓")
        print_info(f"Follow logs:  sudo journalctl -u {SERVICE_NAME} -f")
        return True
    else:
        print_err(f"Service '{SERVICE_NAME}' status: {status}")
        print_warn(
            f"Check logs: sudo journalctl -u {SERVICE_NAME} -n 50 --no-pager"
        )
        return False


# ─────────────────────────────────────────────────────────────
# CONFIGURATION FLOW
# ─────────────────────────────────────────────────────────────

def configure_env(project_dir: pathlib.Path) -> dict:
    print_header("Configuration")

    env_file = project_dir / ".env"
    current_values = load_dotenv_raw(env_file)

    if current_values:
        print_info(f"Found existing .env — current values will be offered to keep.")
    else:
        print_info("No existing .env found — starting fresh configuration.")

    new_values = {}
    for spec in ENV_FIELDS:
        value = prompt_field(spec, current_values)
        new_values[spec["key"]] = value

    write_dotenv(env_file, new_values)
    print()
    print_ok(f".env written to {env_file}")
    return new_values


# ─────────────────────────────────────────────────────────────
# FINAL OUTPUT
# ─────────────────────────────────────────────────────────────

def print_siri_instructions():
    print_header("iOS Share Sheet Setup (Siri Shortcuts)")
    print(f"""  This bot accepts YouTube URLs and returns the transcript as a .txt file.
  You can trigger it directly from the iOS Share Sheet using Siri Shortcuts.

  {BOLD}─── Mode 1: Full Whisper Transcription (accurate, takes a few minutes) ───{RESET}

  1. Open the {BOLD}Shortcuts{RESET} app on your iPhone
  2. Tap {BOLD}+{RESET} to create a new shortcut
  3. Add action: {CYAN}Receive Input from Share Sheet{RESET}  (type: URLs)
  4. Add action: {CYAN}Open URLs{RESET}
     URL value:
       {YELLOW}tg://msg?to=YOUR_BOT_USERNAME&text=[Shortcut Input]{RESET}
     Replace {BOLD}YOUR_BOT_USERNAME{RESET} with your bot's @username (no @ symbol)
  5. Tap the shortcut name → {BOLD}Add to Share Sheet{RESET}
  6. Name it something like: {DIM}"Transcript Bot"{RESET}

  {BOLD}─── Mode 2: Fast Captions Fetch (instant, uses YouTube's auto-captions) ───{RESET}

  1. Create another new shortcut
  2. Add action: {CYAN}Receive Input from Share Sheet{RESET}  (type: URLs)
  3. Add action: {CYAN}Text{RESET}  — enter the value: {YELLOW}/fast {RESET}
  4. Add action: {CYAN}Combine Text{RESET}
     Combine: the Text from step 3, then [Shortcut Input]
  5. Add action: {CYAN}Open URLs{RESET}
     URL value:
       {YELLOW}tg://msg?to=YOUR_BOT_USERNAME&text=[Combined Text]{RESET}
  6. Add to Share Sheet — name it: {DIM}"Transcript Bot Fast"{RESET}

  {BOLD}How it works:{RESET}
    • Share any YouTube URL from Safari → select your shortcut
    • Telegram opens with the URL pre-filled → tap {BOLD}Send{RESET}
    • The bot replies with a .txt file of the full transcript

  {DIM}Note: The tg:// URL scheme opens Telegram and pre-fills the message.
  You tap Send once — the transcript arrives as a file attachment.{RESET}
""")


def print_macos_run_instructions(project_dir: pathlib.Path):
    print_header("Running the Bot (macOS)")
    print(f"""  The bot runs directly on macOS — no systemd needed.

  {BOLD}Start the bot:{RESET}
    cd {project_dir}
    uv run transcript-bot

  {BOLD}Run in the background (keeps running after closing the terminal):{RESET}
    cd {project_dir}
    nohup uv run transcript-bot > bot.log 2>&1 &
    tail -f bot.log        {DIM}# follow the log{RESET}
    kill %1                {DIM}# stop the background process{RESET}

  {BOLD}Stop a background run:{RESET}
    pkill -f "transcript-bot"
""")


def print_summary(plat: str, values: dict, project_dir: pathlib.Path):
    print_header("Setup Complete — Summary")

    token = values.get("TELEGRAM_BOT_TOKEN", "")
    token_display = f"...{token[-4:]}" if len(token) >= 4 else c("(configured)", DIM)

    rows = [
        ("Platform",       plat),
        ("Project dir",    str(project_dir)),
        ("Bot token",      token_display),
        ("Allowed users",  values.get("ALLOWED_USER_IDS", c("[not set]", RED))),
        ("Whisper model",  values.get("WHISPER_MODEL", "small")),
        ("Compute type",   values.get("WHISPER_COMPUTE_TYPE", "") or c("(auto)", DIM)),
        ("Language",       values.get("WHISPER_LANGUAGE", "") or c("(auto-detect)", DIM)),
        ("Work dir",       values.get("WORK_DIR", "/tmp/transcript_bot")),
        ("Log level",      values.get("LOG_LEVEL", "INFO")),
    ]
    if plat == "linux":
        rows.append(("Service status", f"sudo systemctl status {SERVICE_NAME}"))
        rows.append(("Follow logs",    f"sudo journalctl -u {SERVICE_NAME} -f"))
    else:
        rows.append(("Start bot",      f"cd {project_dir} && uv run transcript-bot"))

    for label, value in rows:
        print(f"  {BOLD}{label:<18}{RESET} {CYAN}{value}{RESET}")
    print()


# ─────────────────────────────────────────────────────────────
# COMMANDS
# ─────────────────────────────────────────────────────────────

def cmd_check(project_dir: pathlib.Path):
    print_header("Current Configuration")

    env_file = project_dir / ".env"
    values = load_dotenv_raw(env_file)

    if not values:
        print_warn(f"No .env file found at {env_file}")
        print_info("Run 'python3 setup.py' to configure.")
        return

    print(f"  {DIM}Reading from: {env_file}{RESET}\n")
    for spec in ENV_FIELDS:
        key     = spec["key"]
        label   = spec["label"]
        val     = values.get(key, "")
        default = spec.get("default", "")

        if spec.get("sensitive") and val:
            display = c(f"...{val[-4:]}", CYAN)
        elif val:
            display = c(val, CYAN)
        else:
            display = c("[not set]", DIM)

        suffix = ""
        if val and val == default:
            suffix = c("  (default)", DIM)
        elif not val and not spec["required"]:
            suffix = c("  (using default: " + (default or "blank") + ")", DIM)

        print(f"  {BOLD}{label:<28}{RESET} {display}{suffix}")

    print()


def cmd_restart():
    plat = detect_platform()
    if plat != "linux":
        print_err("--restart is only supported on Linux (Ubuntu).")
        print_info("On macOS, stop and restart the bot process manually.")
        sys.exit(1)

    print_header("Restarting transcript-bot Service")
    run_cmd(
        ["sudo", "systemctl", "restart", SERVICE_NAME],
        error_hint=f"Try: sudo journalctl -u {SERVICE_NAME} -n 30 --no-pager",
    )
    time.sleep(2)
    check_service_status()


def cmd_setup(project_dir: pathlib.Path):
    print_header("Transcript Bot — Setup")
    plat = detect_platform()
    print_info(f"Platform:         {BOLD}{plat}{RESET}")
    print_info(f"Project directory: {project_dir}")

    # ── Step 1: System dependencies
    if plat == "macos":
        install_homebrew_deps()
    elif plat == "linux":
        install_ubuntu_deps()
    else:
        print_warn(f"Unknown platform '{plat}' — skipping system dependency installation.")

    # ── Step 2: uv
    install_uv()

    # ── Step 3: Python deps (in project dir)
    run_uv_sync(project_dir)

    # ── Step 4: Configure .env
    values = configure_env(project_dir)

    # ── Step 5: Ubuntu-specific deployment
    if plat == "linux":
        print_header("Ubuntu Production Deployment")
        stop_service_if_running()
        create_system_user()
        deploy_to_opt(project_dir)
        write_opt_env(values)
        run_uv_sync_opt()
        install_systemd_service()
        enable_and_start_service()

    # ── Step 6: Platform-specific run instructions
    if plat == "macos":
        print_macos_run_instructions(project_dir)

    # ── Step 7: Siri Shortcut instructions
    print_siri_instructions()

    # ── Step 8: Summary
    print_summary(plat, values, project_dir)


# ─────────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transcript Bot — setup and installer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 setup.py             Full interactive setup\n"
            "  python3 setup.py --check     Show current config values\n"
            "  python3 setup.py --restart   (Ubuntu) Restart the service\n"
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print current configuration values and exit",
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="(Ubuntu only) Restart the systemd service and exit",
    )
    args = parser.parse_args()

    project_dir = PROJECT_DIR

    if args.check:
        cmd_check(project_dir)
        return

    if args.restart:
        cmd_restart()
        return

    cmd_setup(project_dir)


if __name__ == "__main__":
    main()
