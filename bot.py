"""
bot.py — Telegram Watermark Remover Bot
Removes ONLY rotated + semi-transparent email/phone watermarks.
Normal PDF content is never touched.
"""

import os
import re
import logging
import asyncio
import fitz
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ── Config ────────────────────────────────────────────────────────────────────
BOT_TOKEN    = "8445635159:AAHS0zXgHrlffS96oDyjjg0m-y7gF7sfosY"
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR   = "outputs"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR,   exist_ok=True)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

# ── Watermark detection logic ─────────────────────────────────────────────────
PHONE_RE = re.compile(r'\d{10}')
EMAIL_RE  = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}')

def _is_wm_text(txt: str) -> bool:
    """True if text looks like a phone number or email."""
    clean = txt.replace(" ", "").replace("-", "")
    return bool(PHONE_RE.search(clean)) or bool(EMAIL_RE.search(txt))

def _is_rotated(span: dict) -> bool:
    """
    span['flags'] bit 0 = italic (not useful here).
    Real rotation is in the span's 'origin' vs bbox, or better: use the
    transformation matrix stored in the span dict under key 'transform'.
    A non-rotated span has transform[1] ≈ 0 and transform[2] ≈ 0.
    A rotated span has non-zero off-diagonal elements.
    """
    t = span.get("transform")          # (a, b, c, d, e, f)  — affine matrix
    if not t or len(t) < 4:
        return False
    # b and c are sin/cos components; non-zero → rotated
    return abs(t[1]) > 0.1 or abs(t[2]) > 0.1

def _is_transparent(span: dict) -> bool:
    """
    PyMuPDF doesn't expose alpha directly in rawdict spans,
    but watermarks are drawn with low opacity via the page's
    graphics state.  We detect them via their color: very light grey
    (near white) is the typical rendering of a semi-transparent dark text
    baked into a white background.  Adjust threshold as needed.
    """
    color = span.get("color", 0)       # 0 = black (int or float 0–1)
    # color is packed int: 0x00RRGGBB or a float for greyscale
    if isinstance(color, int):
        r = (color >> 16) & 0xFF
        g = (color >>  8) & 0xFF
        b =  color        & 0xFF
        # Light grey / washed-out text  (each channel > 160)
        return r > 160 and g > 160 and b > 160
    # float greyscale: 0 = black, 1 = white; watermark is near-white
    return color > 0.63          # lighter than ~160/255

def remove_watermark(input_path: str, output_path: str) -> int:
    doc   = fitz.open(input_path)
    total = 0

    for page in doc:
        rects = []
        try:
            rawdict = page.get_text(
                "rawdict",
                flags=fitz.TEXT_PRESERVE_WHITESPACE | fitz.TEXT_PRESERVE_LIGATURES
            )
            for block in rawdict.get("blocks", []):
                if block.get("type") != 0:   # 0 = text block
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "").strip()
                        if not txt:
                            continue
                        # ALL THREE conditions must be true:
                        # 1. text matches phone / email pattern
                        # 2. span is rotated
                        # 3. span color is light (semi-transparent effect)
                        if _is_wm_text(txt) and _is_rotated(span) and _is_transparent(span):
                            rects.append(fitz.Rect(span["bbox"]).expand(3))
        except Exception as e:
            log.warning(f"span scan error on page {page.number}: {e}")

        # Deduplicate
        seen = set()
        for rect in rects:
            key = (round(rect.x0), round(rect.y0), round(rect.x1), round(rect.y1))
            if key in seen:
                continue
            seen.add(key)
            try:
                # fill=None → transparent redaction (no white box)
                page.add_redact_annot(rect, fill=None)
                total += 1
            except Exception:
                pass

        if seen:
            page.apply_redactions(
                images   = fitz.PDF_REDACT_IMAGE_NONE,
                graphics = fitz.PDF_REDACT_LINE_ART_NONE
            )

    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total

# ── Telegram handlers ─────────────────────────────────────────────────────────
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Watermark Remover Bot\n\nBas PDF bhejo — main watermark hata ke wapas dunga."
    )

async def handle_pdf(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("Sirf PDF file bhejo.")
        return

    caption  = update.message.caption or None
    status   = await update.message.reply_text(f"Processing: {doc.file_name} …")

    uid      = update.effective_user.id
    in_path  = os.path.join(DOWNLOAD_DIR, f"{uid}_{doc.file_id}.pdf")
    out_path = os.path.join(OUTPUT_DIR,   f"{uid}_{doc.file_id}.pdf")

    try:
        tg_file = await ctx.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(in_path)

        loop    = asyncio.get_event_loop()
        removed = await loop.run_in_executor(None, remove_watermark, in_path, out_path)
        log.info(f"[{uid}] {doc.file_name} — {removed} watermark spans removed")

        with open(out_path, "rb") as f:
            await ctx.bot.send_document(
                chat_id  = update.effective_chat.id,
                document = f,
                filename = doc.file_name,
                caption  = caption,
            )
        await status.delete()

    except Exception as e:
        log.error(f"[{uid}] error: {e}")
        await status.edit_text(f"Error: {e}")
    finally:
        for p in (in_path, out_path):
            try:
                os.remove(p)
            except Exception:
                pass

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  start))
    app.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    log.info("Bot running …")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
