# transcript-bot

A private Telegram bot that transcribes YouTube videos and Instagram Reels. Send a URL, get back a `.txt` file. Self-hosted, restricted to specific Telegram user IDs.

---

## How it works

Send the bot a YouTube or Instagram URL. It downloads the audio with yt-dlp, runs it through [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and replies with a transcript file.

For YouTube there's also a `/fast` command that skips Whisper and fetches YouTube's existing captions instead — instant results for videos that have them. Instagram has no caption API, so `/fast` on an Instagram URL falls back to Whisper automatically.

| Mode | How to trigger | Speed | Platforms |
|------|----------------|-------|-----------|
| Whisper transcription | Send URL directly | 1–5 min | YouTube, Instagram |
| Caption fetch | `/fast <url>` | Instant | YouTube only |

---

## Requirements

- Python 3.11+
- ffmpeg
- A Telegram bot token (from [@BotFather](https://t.me/botfather))
- Your Telegram user ID (from [@userinfobot](https://t.me/userinfobot))

Ubuntu 20.04+ for production (systemd service). macOS works fine for local use.

---

## Setup

```bash
git clone <repo>
cd transcript-getter
python3 install.py
```

The installer handles system dependencies (ffmpeg, Python), the Python venv via [uv](https://docs.astral.sh/uv/), and the `.env` config file interactively. On Ubuntu it also creates a dedicated system user, copies the project to `/opt/transcript-bot`, and installs a systemd service.

Running the installer again is safe — it loads existing `.env` values and asks before overwriting each one.

```bash
python3 install.py --check    # print current config and exit
python3 install.py --restart  # (Ubuntu) restart the service
```

---

## Configuration

Configuration goes in `.env` at the project root, or `/opt/transcript-bot/.env` in production.

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | From @BotFather |
| `ALLOWED_USER_IDS` | Yes | — | Comma-separated numeric Telegram IDs |
| `WHISPER_MODEL` | No | `small` | `tiny`, `base`, `small`, `medium`, `large-v2`, `large-v3` |
| `WHISPER_COMPUTE_TYPE` | No | auto | Auto-detects `float16` on GPU, `int8` on CPU |
| `WHISPER_LANGUAGE` | No | auto | ISO 639-1 code, e.g. `en`. Leave blank to auto-detect. |
| `WORK_DIR` | No | `/tmp/transcript_bot` | Temp dir for audio files during transcription |
| `LOG_LEVEL` | No | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

On CPU without a GPU, `tiny` or `base` are fast enough for development. `small` is the default and a reasonable choice for production on a modest server. The large models need a GPU to be practical.

---

## Running locally (macOS)

```bash
uv run transcript-bot
```

Background mode:

```bash
nohup uv run transcript-bot > bot.log 2>&1 &
tail -f bot.log
```

---

## Production (Ubuntu / systemd)

The installer handles setup. After that:

```bash
sudo systemctl status transcript-bot
sudo journalctl -u transcript-bot -f
sudo systemctl restart transcript-bot
```

The service runs as a dedicated `transcript-bot` system user. Audio files are deleted after each transcription. The Whisper model loads once at startup and stays in memory.

---

## iOS Share Sheet

You can share URLs from Safari directly to the bot without switching apps manually.

### Slow (Whisper) shortcut

1. Open the Shortcuts app, tap **+**
2. Add: **Receive Input from Share Sheet** (type: URLs)
3. Add: **Open URLs** with value `tg://msg?to=YOUR_BOT_USERNAME&text=[Shortcut Input]`
   - Replace `YOUR_BOT_USERNAME` with your bot's @username (no @)
4. Add to Share Sheet, name it "Transcript Bot"

### Fast (captions) shortcut — YouTube only

1. New shortcut
2. **Receive Input from Share Sheet** (type: URLs)
3. **Text** action — value: `/fast `
4. **Combine Text** — the text from step 3, then the shortcut input
5. **Open URLs** — `tg://msg?to=YOUR_BOT_USERNAME&text=[Combined Text]`
6. Add to Share Sheet, name it "Transcript Bot Fast"

The shortcut opens Telegram with the message pre-filled. Tap Send once.

---

## Project layout

```
src/transcript_bot/
├── main.py         entry point, startup, model pre-load
├── bot.py          telegram handlers and pipeline logic
├── config.py       .env loading and validation
├── downloader.py   yt-dlp wrapper (audio download + metadata)
├── captions.py     youtube-transcript-api wrapper (fast path)
├── transcriber.py  faster-whisper wrapper
└── utils.py        URL detection, transcript formatting, cleanup
```

---

## Development

```bash
uv sync                    # install deps including dev group
python -m pytest tests/ -v
```

Tests cover URL detection and transcript formatting. The downloader and transcriber aren't unit-tested — they require network access and model files.
