# Astra UserBot — repaired build

This build fixes the startup/configuration and subprocess/network lifecycle issues found during static review.

## Install

1. Copy `.env.example` to `.env` and fill in your existing Telegram/Groq values locally.
2. Create the environment with the Python version installed on your host:

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

3. Keep your existing `data/astra_session.session` and `data/databases/` when upgrading an existing installation. The repair package intentionally does not include private runtime data.
4. For systemd, install the unit as `astra.service`, make sure the project is at `/opt/astra`, and run:

```bash
systemctl daemon-reload
systemctl enable --now astra.service
journalctl -u astra.service -f
```

The service reads `/opt/astra/.env` and uses `/opt/astra/venv/bin/python` so it does not accidentally run against the system Python.

## Important

The existing Telegram session is not regenerated. If Telegram reports that the session is unauthorized or invalid, authenticate again using your normal Telethon login procedure.

External binaries used by optional plugins are still required: `ffmpeg`, `tesseract`, `rclone`, `aria2c`, `yt-dlp`, `edge-tts`, and a compatible `speedtest` CLI. Missing optional binaries disable only their corresponding plugin.
