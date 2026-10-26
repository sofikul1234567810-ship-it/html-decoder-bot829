"""Simple static HTML/JavaScript inspection bot for Telegram.
Does not execute uploaded code or promise to decrypt custom obfuscation.
"""
import os
import re
import base64
import html
import logging
from pathlib import Path
from telegram import Update, Document
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger(__name__)
MAX_BYTES = 5 * 1024 * 1024
ALLOWED_EXTS = {".html", ".htm", ".js", ".txt"}


def safe_name(name: str) -> str:
    name = Path(name or "upload.txt").name
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return (name or "upload.txt")[:100]


def decode_common_escapes(source: str) -> tuple[str, list[str]]:
    notes = []
    result = source
    # Decode JS Unicode escape sequences such as \\u0041 and \\x41.
    unicode_pattern = re.compile(r"\\u([0-9a-fA-F]{4})")
    hex_pattern = re.compile(r"\\x([0-9a-fA-F]{2})")
    new_result = unicode_pattern.sub(lambda m: chr(int(m.group(1), 16)), result)
    if new_result != result:
        notes.append("Decoded JavaScript \\uXXXX escape sequences where found.")
        result = new_result
    new_result = hex_pattern.sub(lambda m: chr(int(m.group(1), 16)), result)
    if new_result != result:
        notes.append("Decoded JavaScript \\xXX escape sequences where found.")
        result = new_result
    # Decode HTML entities without executing anything.
    unescaped = html.unescape(result)
    if unescaped != result:
        notes.append("Decoded HTML entities.")
        result = unescaped
    return result, notes


def inspect_source(source: str, filename: str) -> tuple[str, str]:
    decoded, notes = decode_common_escapes(source)
    flags = []
    patterns = {
        "eval()": r"\beval\s*\(",
        "Function constructor": r"\bnew\s+Function\s*\(|\bFunction\s*\(",
        "Base64 decode hint": r"atob\s*\(",
        "string timer": r"\bset(?:Timeout|Interval)\s*\(\s*['\"]",
        "debugger statement": r"\bdebugger\s*;?",
        "WebAssembly hint": r"\bWebAssembly\b",
    }
    for label, pattern in patterns.items():
        if re.search(pattern, decoded, re.IGNORECASE):
            flags.append(label)

    # Conservative Base64 reporting only: do not replace code with guessed decoding.
    b64_candidates = re.findall(r"['\"]([A-Za-z0-9+/]{24,}={0,2})['\"]", decoded)
    valid_b64 = 0
    for candidate in b64_candidates[:200]:
        try:
            raw = base64.b64decode(candidate, validate=True)
            text = raw.decode("utf-8")
            if text and sum(ch.isprintable() or ch in "\r\n\t" for ch in text) / len(text) > 0.9:
                valid_b64 += 1
        except Exception:
            pass
    if valid_b64:
        notes.append(f"Found {valid_b64} quoted Base64-looking string(s) that may decode as readable UTF-8; left unchanged to avoid corrupting code.")

    # Keep formatting conservative: don't attempt risky automatic beautification.
    report = [
        "HTML/JavaScript static inspection report",
        f"File: {safe_name(filename)}",
        f"Original size: {len(source.encode('utf-8', errors='replace'))} bytes",
        f"Output size: {len(decoded.encode('utf-8', errors='replace'))} bytes",
        "",
        "Transformations:",
    ]
    report.extend([f"- {n}" for n in notes] or ["- No common escape/entity transformations detected."])
    report += ["", "Potential obfuscation/runtime indicators:"]
    report.extend([f"- {x}" for x in flags] or ["- No common indicators detected by the basic scanner."])
    report += [
        "",
        "Limitations:",
        "- This bot does not execute uploaded files.",
        "- It is not a universal decryptor; custom encryption, packed code, missing keys, or runtime-only logic may remain obfuscated.",
        "- Review the output before running it. Upload only files you own or are authorized to inspect.",
    ]
    return decoded, "\n".join(report)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Hi! Send me an .html, .htm, .js, or .txt file (max 5 MB). I will do basic static decoding/inspection.\n\n"
        "Note: this is not a universal decryptor and it never executes uploaded code."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Send a supported file as a Telegram document. Supported: .html, .htm, .js, .txt. Max 5 MB.\n"
        "I decode common JS escape sequences and HTML entities, then return a report. Custom obfuscation may not be reversible."
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    doc: Document = message.document
    if not doc:
        return
    filename = safe_name(doc.file_name or "upload.txt")
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTS:
        await message.reply_text("Please send an .html, .htm, .js, or .txt file.")
        return
    if doc.file_size and doc.file_size > MAX_BYTES:
        await message.reply_text("File is too large. Maximum size is 5 MB.")
        return
    try:
        tg_file = await context.bot.get_file(doc.file_id)
        payload = await tg_file.download_as_bytearray()
        if len(payload) > MAX_BYTES:
            await message.reply_text("File is too large. Maximum size is 5 MB.")
            return
        source = bytes(payload).decode("utf-8", errors="replace")
        output, report = inspect_source(source, filename)
        stem = Path(filename).stem or "decoded"
        output_path = Path(f"{stem}_basic_decoded{suffix}")
        report_path = Path(f"{stem}_report.txt")
        output_path.write_text(output, encoding="utf-8")
        report_path.write_text(report, encoding="utf-8")
        try:
            with output_path.open("rb") as f:
                await message.reply_document(document=f, filename=output_path.name, caption="Basic static output (not guaranteed fully decoded).")
            with report_path.open("rb") as f:
                await message.reply_document(document=f, filename=report_path.name, caption="Inspection report")
        finally:
            output_path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
    except Exception:
        LOG.exception("Failed to process document")
        await message.reply_text("I couldn't process that file. Please try a valid UTF-8 HTML/JS/TXT file under 5 MB.")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN environment variable. Add it in Render → Environment.")
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    LOG.info("Bot starting with long polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
