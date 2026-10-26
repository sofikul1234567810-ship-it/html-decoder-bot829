# Telegram HTML Decoder Bot (Render-ready)

This is a small, self-contained Telegram bot. It has **no `decoder` package dependency**; all code is in `bot.py`.

## Deploy on Render
1. Upload this ZIP to a GitHub repository and connect that repository to Render.
2. Create a **Background Worker** (not a Web Service).
3. Build Command:
   `pip install -r requirements.txt`
4. Start Command:
   `python bot.py`
5. In Render → Environment, add:
   - Key: `TELEGRAM_BOT_TOKEN`
   - Value: your token from Telegram's `@BotFather`
6. Deploy the worker. Open your bot in Telegram and send `/start`.

## What it does
- Accepts `.html`, `.htm`, `.js`, and `.txt` documents up to 5 MB.
- Decodes common JavaScript `\\uXXXX` / `\\xXX` escapes and HTML entities.
- Returns the processed file and a static inspection report.
- Never executes uploaded code.

## Important limitations
This is a basic static helper, not a universal decryptor. Custom encryption, packed payloads, missing keys, or runtime-only code may remain obfuscated. Inspect any output before running it. Only upload files you own or are authorized to inspect.
