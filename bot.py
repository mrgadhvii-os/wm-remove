import os
import re
import time
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

import fitz
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

# ── Config ─────────────────────────────────────────────────────────────
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]

DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "outputs"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

MAX_FILE_SIZE = 100 * 1024 * 1024
executor = ThreadPoolExecutor(max_workers=4)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
log = logging.getLogger("wm-bot")

# ── Patterns ───────────────────────────────────────────────────────────
PHONE_RE = re.compile(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
EMAIL_RE = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}')
URL_RE = re.compile(r'((https?://)|(www\.))?[a-zA-Z0-9-]+\.[a-zA-Z]{2,}([/\w\-.?=&%+]*)?')

def is_watermark_text(text: str) -> bool:
    if not text:
        return False
    t = " ".join(text.strip().split())
    if len(t) < 3:
        return False

    if EMAIL_RE.search(t) or PHONE_RE.search(t) or URL_RE.search(t):
        return True

    low = t.lower()
    suspicious_words = [
        "telegram", "contact", "email", "gmail", "yahoo", "outlook",
        "phone", "mobile", "whatsapp", "call", "t.me", ".com", ".in"
    ]
    if any(w in low for w in suspicious_words):
        return True

    if len(t) <= 25 and (any(ch.isdigit() for ch in t) or "@" in t or "." in t):
        return True

    uniq_ratio = len(set(t)) / max(len(t), 1)
    if len(t) > 6 and uniq_ratio < 0.35:
        return True

    return False

def estimate_opacity(span: dict) -> float:
    color = span.get("color", 0)
    if isinstance(color, int):
        r = (color >> 16) & 255
        g = (color >> 8) & 255
        b = color & 255
        brightness = (r + g + b) / (3 * 255)
        if brightness > 0.82:
            return max(0.05, 1.0 - brightness)
        if brightness < 0.12:
            return 0.95
    return 0.75

def merge_rects(rects, gap=4):
    if not rects:
        return []

    rects = sorted(rects, key=lambda r: (round(r.y0, 1), round(r.x0, 1)))
    merged = [rects[0]]

    for r in rects[1:]:
        last = merged[-1]
        expand_last = fitz.Rect(last.x0 - gap, last.y0 - gap, last.x1 + gap, last.y1 + gap)
        if expand_last.intersects(r):
            merged[-1] = last | r
        else:
            merged.append(r)

    return merged

def safe_span_text(span: dict) -> str:
    txt = span.get("text")
    if isinstance(txt, str):
        return txt

    chars = span.get("chars", [])
    if chars:
        return "".join(ch.get("c", "") for ch in chars)
    return ""

def open_pdf_safely(path: str):
    try:
        doc = fitz.open(path)
    except Exception as e:
        raise RuntimeError(f"Cannot open PDF: {e}")

    if getattr(doc, "needs_pass", False):
        doc.close()
        raise RuntimeError("PDF is encrypted/password-protected")

    try:
        page_count = doc.page_count
    except Exception:
        try:
            page_count = len(doc)
        except Exception as e:
            doc.close()
            raise RuntimeError(f"Cannot read page count: {e}")

    if page_count <= 0:
        try:
            for _ in doc:
                page_count += 1
        except Exception:
            pass

    if page_count <= 0:
        doc.close()
        raise RuntimeError("PDF opened but page count is 0 (damaged or unsupported PDF structure)")

    return doc

def process_page(page, stats: dict):
    rects = []

    try:
        text_dict = page.get_text("dict", flags=fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES)
    except Exception as e:
        log.warning("Page %s text extraction failed: %s", page.number, e)
        return 0

    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:
            continue

        for line in block.get("lines", []):
            line_dir = line.get("dir", (1.0, 0.0))
            rotated = abs(line_dir[0]) < 0.95 or abs(line_dir[1]) > 0.2

            for span in line.get("spans", []):
                text = safe_span_text(span).strip()
                if not text:
                    continue

                bbox = span.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue

                opacity = estimate_opacity(span)
                font_size = span.get("size", 0)

                suspicious = False

                if is_watermark_text(text):
                    suspicious = True
                elif rotated and len(text) >= 4 and (any(c.isdigit() for c in text) or "." in text or "@" in text):
                    suspicious = True
                elif opacity < 0.22 and len(text) <= 40:
                    suspicious = True
                elif font_size >= 6 and font_size <= 18 and len(text) <= 30 and ("@" in text or any(ch.isdigit() for ch in text)):
                    suspicious = True

                if suspicious:
                    r = fitz.Rect(bbox)
                    r = fitz.Rect(r.x0 - 1.5, r.y0 - 1.5, r.x1 + 1.5, r.y1 + 1.5)
                    rects.append(r)
                    stats["watermark_spans"] += 1

    rects = merge_rects(rects, gap=3)
    applied = 0

    for r in rects:
        try:
            page.add_redact_annot(
                r,
                text="",
                fill=(1, 1, 1),
                cross_out=False
            )
            applied += 1
        except Exception as e:
            log.warning("Page %s add_redact_annot failed: %s", page.number, e)

    if applied:
        try:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                text=fitz.PDF_REDACT_TEXT_REMOVE
            )
        except TypeError:
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=fitz.PDF_REDACT_LINE_ART_NONE
            )
        except Exception as e:
            log.warning("Page %s apply_redactions failed: %s", page.number, e)
            try:
                annots = list(page.annots() or [])
                for a in annots:
                    page.delete_annot(a)
            except Exception:
                pass
            return 0

    return applied

def save_pdf_safely(doc, output_path: str):
    save_attempts = [
        dict(garbage=1, deflate=True, clean=False),
        dict(garbage=0, deflate=True, clean=False),
        dict(garbage=0, deflate=False, clean=False),
    ]

    last_error = None
    for opts in save_attempts:
        try:
            doc.save(output_path, **opts)
            return
        except Exception as e:
            last_error = e

    raise RuntimeError(f"Cannot save output PDF: {last_error}")

def remove_watermarks_smart(input_path: str, output_path: str) -> dict:
    stats = {
        "pages_processed": 0,
        "watermarks_removed": 0,
        "watermark_spans": 0,
        "input_pages": 0,
    }

    doc = open_pdf_safely(input_path)
    try:
        stats["input_pages"] = doc.page_count

        for page in doc:
            stats["pages_processed"] += 1
            removed = process_page(page, stats)
            stats["watermarks_removed"] += removed

        if doc.page_count <= 0:
            raise RuntimeError("Processed PDF became empty unexpectedly")

        save_pdf_safely(doc, output_path)
    finally:
        doc.close()

    if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
        raise RuntimeError("Output PDF was not created correctly")

    try:
        test_doc = fitz.open(output_path)
        out_pages = test_doc.page_count
        test_doc.close()
        if out_pages <= 0:
            raise RuntimeError("Saved output PDF has 0 pages")
    except Exception as e:
        raise RuntimeError(f"Output validation failed: {e}")

    return stats

# ── Bot ─────────────────────────────────────────────────────────────────
app = Client(
    "watermark_remover_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=8
)

async def safe_edit(msg: Message, text: str, parse_mode=None):
    try:
        await msg.edit_text(text, parse_mode=parse_mode)
    except Exception:
        pass

async def progress_callback(current, total, message, status_text):
    if total <= 0:
        return
    percent = int(current * 100 / total)
    try:
        await message.edit_text(
            f"{status_text}: {percent}%\n"
            f"📦 {current // (1024*1024)}MB / {total // (1024*1024)}MB"
        )
    except Exception:
        pass

@app.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    await message.reply_text(
        "🤖 **PDF Watermark Remover Bot**\n\n"
        "Send a PDF file.\n"
        "I will detect and remove suspicious text watermarks like emails, phones, URLs, and repeated contact marks.\n\n"
        "✅ Large PDF support\n"
        "✅ Safer PDF open/save handling\n"
        "✅ Better broken-file protection",
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    await start_command(client, message)

@app.on_message(filters.document)
async def handle_pdf(client: Client, message: Message):
    doc = message.document

    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await message.reply_text("❌ Please send a PDF file only.")
        return

    if doc.file_size and doc.file_size > MAX_FILE_SIZE:
        await message.reply_text(
            f"❌ File too large.\nMax: 100MB\nYour file: {doc.file_size // (1024 * 1024)}MB"
        )
        return

    status = await message.reply_text("📥 Downloading PDF...")

    uid = message.from_user.id if message.from_user else 0
    ts = int(time.time())
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", doc.file_name)

    in_path = os.path.join(DOWNLOAD_DIR, f"{uid}_{ts}_{safe_name}")
    out_path = os.path.join(OUTPUT_DIR, f"{uid}_{ts}_cleaned_{safe_name}")

    try:
        await client.download_media(
            message,
            file_name=in_path,
            progress=lambda c, t: asyncio.create_task(progress_callback(c, t, status, "📥 Downloading"))
        )

        if not os.path.exists(in_path) or os.path.getsize(in_path) == 0:
            raise RuntimeError("Downloaded file is empty")

        await safe_edit(status, "🔍 Validating PDF...")

        try:
            test_doc = fitz.open(in_path)
            pages = test_doc.page_count
            needs_pass = getattr(test_doc, "needs_pass", False)
            test_doc.close()
        except Exception as e:
            raise RuntimeError(f"Downloaded file is not a readable PDF: {e}")

        if needs_pass:
            raise RuntimeError("Password-protected PDF is not supported")

        if pages <= 0:
            raise RuntimeError("This PDF reports 0 pages to the parser. It may be damaged, scanned in a broken wrapper, or unsupported.")

        await safe_edit(status, "🛠 Removing watermark text...")

        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(
            executor,
            remove_watermarks_smart,
            in_path,
            out_path
        )

        send_path = out_path if os.path.exists(out_path) else in_path

        caption = (
            f"✅ **Done**\n\n"
            f"📄 File: `{doc.file_name}`\n"
            f"📑 Pages: {stats['pages_processed']}\n"
            f"🧹 Removed regions: {stats['watermarks_removed']}\n"
            f"🔎 Matched spans: {stats['watermark_spans']}"
        )

        await safe_edit(status, caption, parse_mode=ParseMode.MARKDOWN)

        await message.reply_document(
            send_path,
            caption="🔓 Processed PDF",
            parse_mode=ParseMode.MARKDOWN,
            progress=lambda c, t: asyncio.create_task(progress_callback(c, t, status, "📤 Uploading"))
        )

        try:
            await status.delete()
        except Exception:
            pass

    except Exception as e:
        log.exception("Processing failed")
        err = str(e)[:800]
        await safe_edit(
            status,
            f"❌ **Error processing PDF**\n\n`{err}`",
            parse_mode=ParseMode.MARKDOWN
        )
    finally:
        for path in (in_path, out_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

@app.on_message(filters.command("stats"))
async def stats_command(client: Client, message: Message):
    def dir_size_mb(folder):
        total = 0
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                p = os.path.join(folder, name)
                if os.path.isfile(p):
                    total += os.path.getsize(p)
        return total // (1024 * 1024)

    await message.reply_text(
        f"📊 **Bot Stats**\n\n"
        f"Downloads: {dir_size_mb(DOWNLOAD_DIR)}MB\n"
        f"Outputs: {dir_size_mb(OUTPUT_DIR)}MB\n"
        f"Workers: 4\n"
        f"Max file size: 100MB",
        parse_mode=ParseMode.MARKDOWN
    )

def main():
    log.info("Starting watermark remover bot...")
    app.run()

if __name__ == "__main__":
    main()
