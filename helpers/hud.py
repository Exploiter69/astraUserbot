from core.constants import MAX_MESSAGE_LENGTH


def render(title: str, rows: list[str], footer: str | None = None) -> str:
    """Render Astra's compact terminal-style UI with stable Telegram-safe length."""
    title = str(title).strip().upper()
    lines = [f"╭─╴⚡ ASTRA  //  {title}"]
    for row in rows:
        if row == "---":
            lines.append("├────────────────────────────────")
            continue
        for sub_line in str(row).splitlines() or [""]:
            lines.append(f"│  {sub_line}")
    lines.append(f"╰─╴{footer}" if footer else "╰────────────────────────────────")
    output = "\n".join(lines)
    if len(output) > MAX_MESSAGE_LENGTH:
        marker = "\n│  … [output truncated]\n╰────────────────────────────────"
        output = output[: MAX_MESSAGE_LENGTH - len(marker)] + marker
    return output
