import os, re, asyncio
from collections import defaultdict
import fitz
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode

BOT_TOKEN = "8445635159:AAHS0zXgHrlffS96oDyjjg0m-y7gF7sfosY"
API_ID = 27567486
API_HASH = "b1760d4b5ef697bb8da4e7ac4e261c49"
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "outputs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Client("watermark_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)
user_data = defaultdict(dict)

def remove_watermark(input_path: str, output_path: str) -> int:
    doc = fitz.open(input_path)
    total = 0
    target_email = "tyagimansi1103@gmail.com"
    target_phone_pattern = r'\d{10}'
    
    for page in doc:
        rects = []
        
        # Get text with opacity info
        try:
            rawdict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in rawdict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "").strip()
                        opacity = span.get("opacity", 1.0)
                        
                        if not txt:
                            continue
                        
                        # Target specific email
                        if target_email in txt:
                            rects.append(fitz.Rect(span["bbox"]) + (-2, -2, 2, 2))
                            continue
                        
                        # Target 10-digit phone numbers
                        phone_match = re.search(target_phone_pattern, txt.replace(" ", ""))
                        if phone_match:
                            phone_num = phone_match.group()
                            # Only remove if it's the specific number pattern (will be detected)
                            rects.append(fitz.Rect(span["bbox"]) + (-2, -2, 2, 2))
                            continue
                        
                        # Generic email pattern with opacity check
                        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', txt)
                        if email_match and opacity < 0.5:
                            rects.append(fitz.Rect(span["bbox"]) + (-2, -2, 2, 2))
                            continue
                        
                        # Generic phone pattern with opacity check  
                        phone_any = re.search(r'\d{10}', txt.replace(" ", ""))
                        if phone_any and opacity < 0.5:
                            rects.append(fitz.Rect(span["bbox"]) + (-2, -2, 2, 2))
                            continue
        except Exception:
            pass
        
        # Word level detection for exact matches
        try:
            for w in page.get_text("words"):
                word = w[4].strip()
                if target_email in word:
                    rects.append(fitz.Rect(w[:4]) + (-2, -2, 2, 2))
                if re.search(target_phone_pattern, word.replace(" ", "")):
                    rects.append(fitz.Rect(w[:4]) + (-2, -2, 2, 2))
        except Exception:
            pass
        
        seen = set()
        for rect in rects:
            key = (round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            try:
                page.add_redact_annot(rect, fill=None)
                total += 1
            except Exception:
                pass
        
        if seen:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE)
    
    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text("📄 Send me PDF files, I'll remove watermarks (email/phone) and send them back!")

@app.on_message(filters.document & filters.pdf)
async def handle_pdf(client: Client, message: Message):
    user_id = message.from_user.id
    msg = await message.reply_text("⏳ Downloading PDF...")
    
    try:
        file_path = await message.download(file_name=os.path.join(DOWNLOAD_DIR, f"{user_id}_{message.id}.pdf"))
        
        await msg.edit_text("🔍 Removing watermarks...")
        
        output_path = os.path.join(OUTPUT_DIR, f"{user_id}_{message.id}_clean.pdf")
        
        loop = asyncio.get_event_loop()
        removed = await loop.run_in_executor(None, remove_watermark, file_path, output_path)
        
        await msg.edit_text(f"✅ Removed {removed} watermarks!\n📤 Sending back...")
        
        await client.send_document(
            message.chat.id,
            output_path,
            caption=f"✨ Cleaned PDF | {removed} watermarks removed",
            file_name=message.document.file_name
        )
        
        await msg.delete()
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")
    finally:
        for path in [file_path, output_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass

print("🤖 Bot started...")
app.run()
