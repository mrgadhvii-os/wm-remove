"""
bot.py — Telegram Watermark Remover Bot
Send PDFs → /pdf → get clean PDFs back
"""

import os
import re
import logging
import asyncio
from collections import defaultdict

import fitz
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# ── Config ────────────────────────────────────────────────────────────────────

BOT_TOKEN = "8445635159:AAHS0zXgHrlffS96oDyjjg0m-y7gF7sfosY"
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR   = "outputs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR,   exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger(__name__)

# user_id → list of {file_id, file_name, caption}
user_queue: dict = defaultdict(list)


# ── Watermark removal ─────────────────────────────────────────────────────────

def remove_watermark(input_path: str, output_path: str) -> int:
    doc = fitz.open(input_path)
    total = 0

    for page in doc:
        rects = []

        # Span level — exact phone / email match
        try:
            rawdict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in rawdict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "").strip()
                        if not txt:
                            continue
                        is_phone = bool(re.fullmatch(r'[\d\s\-\+]{7,15}', txt))
                        is_email = bool(re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', txt))
                        has_phone = bool(re.search(r'\d{10}', txt.replace(" ", "")))
                        if is_phone or is_email or has_phone:
                            rects.append(fitz.Rect(span["bbox"]) + (-2, -2, 2, 2))
        except Exception:
            pass

        # Word level — exact phone / email
        try:
            for w in page.get_text("words"):
                word = w[4].strip()
                if re.fullmatch(r'\d{10}', word.replace(" ", "")):
                    rects.append(fitz.Rect(w[:4]) + (-2, -2, 2, 2))
                if re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', word):
                    rects.append(fitz.Rect(w[:4]) + (-2, -2, 2, 2))
        except Exception:
            pass

        # Deduplicate and apply
        seen = set()
        for rect in rects:
            key = (round(rect.x0, 1), round(rect.y0, 1),
                   round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            try:
                page.add_redact_annot(rect, fill=None)
                total += 1
            except Exception:
                pass

        if seen:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE
            )

    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total


# ── Handlers ──────────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Watermark Remover Bot\n\n"
        "1. Send or forward PDFs (one by one or multiple)\n"
        "2. /pdf — process all queued PDFs\n"
        "3. /list — see queued files\n"
        "4. /clear — reset queue"
    )


async def handle_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    doc = update.message.document

    if not doc or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Send a PDF file.")
        return

    user_queue[user_id].append({
        "file_id":   doc.file_id,
        "file_name": doc.file_name,
        "caption":   update.message.caption or "",
    })

    count = len(user_queue[user_id])
    await update.message.reply_text(
        f"Queued: {doc.file_name} ({count} total)"
    )


async def list_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    queue = user_queue[user_id]

    if not queue:
        await update.message.reply_text("Queue is empty.")
        return

    lines = [f"{i+1}. {f['file_name']}" for i, f in enumerate(queue)]
    await update.message.reply_text("Queued:\n" + "\n".join(lines))


async def clear_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_queue[user_id].clear()
    await update.message.reply_text("Queue cleared.")


async def process_queue(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    queue = user_queue[user_id]

    if not queue:
        await update.message.reply_text("Queue is empty. Send some PDFs first.")
        return

    total_files = len(queue)
    status = await update.message.reply_text(f"Processing {total_files} PDF(s)...")

    success = 0
    failed  = 0

    for i, item in enumerate(queue, 1):
        file_name = item["file_name"]
        caption   = item["caption"]

        await status.edit_text(f"[{i}/{total_files}] {file_name}")

        input_path  = os.path.join(DOWNLOAD_DIR, f"{user_id}_{i}_{file_name}")
        output_path = os.path.join(OUTPUT_DIR,   f"{user_id}_{i}_{file_name}")

        try:
            # Download from Telegram
            tg_file = await ctx.bot.get_file(item["file_id"])
            await tg_file.download_to_drive(input_path)

            # Remove watermark in thread (blocking operation)
            loop = asyncio.get_event_loop()
            removed = await loop.run_in_executor(
                None, remove_watermark, input_path, output_path
            )

            log.info(f"[{user_id}] {file_name} — {removed} redactions applied")

            # Send back — same filename, same caption
            with open(output_path, "rb") as f:
                await ctx.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=file_name,
                    caption=caption if caption else None,
                )

            success += 1

        except Exception as e:
            log.error(f"[{user_id}] {file_name} error: {e}")
            await update.message.reply_text(f"Failed: {file_name}\n{e}")
            failed += 1

        finally:
            for path in (input_path, output_path):
                try:
                    os.remove(path)
                except Exception:
                    pass

    # Clear queue after processing
    user_queue[user_id].clear()

    await status.edit_text(
        f"Done.\nSuccess: {success}  Failed: {failed}"
    )


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  start))
    app.add_handler(CommandHandler("pdf",   process_queue))
    app.add_handler(CommandHandler("list",  list_queue))
    app.add_handler(CommandHandler("clear", clear_queue))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))

    log.info("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
