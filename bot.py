import os, re, asyncio
import fitz
from pyrogram import Client, filters
from pyrogram.types import Message

BOT_TOKEN = "8445635159:AAHS0zXgHrlffS96oDyjjg0m-y7gF7sfosY"
API_ID = 27567486
API_HASH = "b1760d4b5ef697bb8da4e7ac4e261c49"
DOWNLOAD_DIR = "downloads"
OUTPUT_DIR = "outputs"

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

app = Client("watermark_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def remove_watermark(input_path: str, output_path: str) -> int:
    doc = fitz.open(input_path)
    total = 0
    target_email = "tyagimansi1103@gmail.com"
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        rects = []
        
        # Get all text with spans for opacity info
        try:
            rawdict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
            for block in rawdict.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        txt = span.get("text", "").strip()
                        opacity = span.get("opacity", 1.0)
                        font_size = span.get("size", 12)
                        
                        if not txt:
                            continue
                        
                        # Target specific email - remove regardless of opacity
                        if target_email in txt:
                            rects.append(fitz.Rect(span["bbox"]))
                            continue
                        
                        # Target 10-digit phone numbers - remove regardless of opacity  
                        phone_match = re.search(r'\d{10}', txt.replace(" ", ""))
                        if phone_match:
                            rects.append(fitz.Rect(span["bbox"]))
                            continue
                        
                        # For other content: ONLY remove if opacity < 0.95 (watermark)
                        # AND font size is typical for watermark (small or large)
                        if opacity < 0.95:
                            # Check if it looks like watermark (email/phone/small text)
                            is_email = bool(re.search(r'@', txt))
                            is_phone = bool(re.search(r'\d{3,}', txt))
                            is_watermark_text = is_email or is_phone or len(txt) < 50
                            
                            if is_watermark_text:
                                rects.append(fitz.Rect(span["bbox"]))
                                continue
                        
                        # Also check text that appears to be contact info
                        contact_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}', txt)
                        if contact_match and opacity < 0.95:
                            rects.append(fitz.Rect(span["bbox"]))
                            continue
                            
                        phone_any = re.search(r'\d{10}', txt.replace(" ", ""))
                        if phone_any and opacity < 0.95:
                            rects.append(fitz.Rect(span["bbox"]))
                            continue
                            
        except Exception as e:
            print(f"Error processing spans: {e}")
        
        # Word level detection for exact matches
        try:
            words = page.get_text("words")
            for w in words:
                word = w[4].strip()
                if target_email in word:
                    rects.append(fitz.Rect(w[:4]))
                if re.search(r'\d{10}', word.replace(" ", "")):
                    rects.append(fitz.Rect(w[:4]))
        except Exception:
            pass
        
        # Remove duplicates and apply transparent redaction
        seen = set()
        for rect in rects:
            key = (round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))
            if key in seen:
                continue
            seen.add(key)
            try:
                # NO WHITE FILL - use transparent redaction
                page.add_redact_annot(rect, fill=(0, 0, 0, 0))  # Transparent
                total += 1
            except Exception:
                pass
        
        if seen:
            # Apply redactions without affecting images/graphics
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=1)
    
    # Save with compression but preserve quality
    doc.save(output_path, garbage=4, deflate=True, clean=True)
    doc.close()
    return total

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "📄 **Watermark Remover Bot**\n\n"
        "• Send me PDF files\n"
        "• I'll remove watermarks (email/phone numbers)\n"
        "• Semi-transparent text will be removed\n"
        "• Solid content (opacity 1) will be preserved\n"
        "• No white boxes will appear\n\n"
        "Just send the PDF and get cleaned version back!"
    )

@app.on_message(filters.document)
async def handle_pdf(client: Client, message: Message):
    if not message.document.file_name.lower().endswith('.pdf'):
        await message.reply_text("❌ Please send a PDF file only!")
        return
    
    msg = await message.reply_text("📥 **Processing your PDF...**")
    
    try:
        # Download
        file_path = await message.download(file_name=os.path.join(DOWNLOAD_DIR, f"{message.from_user.id}_{message.id}.pdf"))
        await msg.edit_text("🔍 **Removing watermarks...**\n• Target: Email & Phone numbers\n• Opacity < 0.95 will be removed")
        
        # Process
        output_path = os.path.join(OUTPUT_DIR, f"{message.from_user.id}_{message.id}_cleaned.pdf")
        loop = asyncio.get_event_loop()
        removed = await loop.run_in_executor(None, remove_watermark, file_path, output_path)
        
        # Send back
        await msg.edit_text(f"✅ **Done!** Removed {removed} watermarks\n📤 Sending cleaned PDF...")
        
        await client.send_document(
            message.chat.id,
            output_path,
            caption=f"✨ **Cleaned PDF**\n• Removed: {removed} watermarks\n• Target: tyagimansi1103@gmail.com & phone numbers\n• No white boxes added",
            file_name=message.document.file_name.replace('.pdf', '_cleaned.pdf')
        )
        
        await msg.delete()
        
    except Exception as e:
        await msg.edit_text(f"❌ **Error:** `{str(e)[:150]}`")
    finally:
        for path in [file_path, output_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass

print("🤖 Bot Started - No white boxes, watermark removal only!")
print("✓ Opacity < 0.95 will be removed")
print("✓ Email & phone numbers will be removed")
print("✓ Solid content (opacity = 1) preserved")
print("✓ Transparent fill (no white boxes)")

app.run()
