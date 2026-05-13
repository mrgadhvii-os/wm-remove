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
        email_found = False
        phone_found = False
        
        # Get all text with spans
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
                        
                        # Target specific email - remove only if not already found on this page
                        if target_email in txt and not email_found:
                            rects.append(fitz.Rect(span["bbox"]))
                            email_found = True
                            continue
                        
                        # Target 10-digit phone number - remove only if not already found on this page
                        phone_match = re.search(r'\d{10}', txt.replace(" ", ""))
                        if phone_match and not phone_found:
                            rects.append(fitz.Rect(span["bbox"]))
                            phone_found = True
                            continue
                            
        except Exception as e:
            print(f"Error: {e}")
        
        # Word level detection as backup
        if not email_found or not phone_found:
            try:
                words = page.get_text("words")
                for w in words:
                    word = w[4].strip()
                    if target_email in word and not email_found:
                        rects.append(fitz.Rect(w[:4]))
                        email_found = True
                    if re.search(r'\d{10}', word.replace(" ", "")) and not phone_found:
                        rects.append(fitz.Rect(w[:4]))
                        phone_found = True
            except Exception:
                pass
        
        # Apply redaction WITHOUT any fill - just remove the text
        for rect in rects:
            try:
                # CRITICAL: Use None as fill to remove text without adding white box
                page.add_redact_annot(rect, fill=None, text="")
                total += 1
            except Exception:
                pass
        
        if rects:
            # Apply redactions - this removes the text completely
            page.apply_redactions()
    
    # Save without any extra processing
    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return total

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "📄 **Watermark Remover Bot**\n\n"
        "• Send me PDF files\n"
        "• I'll remove SPECIFICALLY:\n"
        "  - tyagimansi1103@gmail.com\n"
        "  - 10-digit phone numbers\n"
        "• Maximum 2 removals per page\n"
        "• NO white boxes will appear\n\n"
        "Just send the PDF!"
    )

@app.on_message(filters.document)
async def handle_pdf(client: Client, message: Message):
    if not message.document.file_name.lower().endswith('.pdf'):
        await message.reply_text("❌ Please send a PDF file only!")
        return
    
    msg = await message.reply_text("📥 **Processing your PDF...**")
    
    try:
        file_path = await message.download(file_name=os.path.join(DOWNLOAD_DIR, f"{message.from_user.id}_{message.id}.pdf"))
        await msg.edit_text("🔍 **Removing watermarks...**\n• Target: tyagimansi1103@gmail.com\n• Target: 10-digit phone numbers\n• Max 2 per page")
        
        output_path = os.path.join(OUTPUT_DIR, f"{message.from_user.id}_{message.id}_cleaned.pdf")
        loop = asyncio.get_event_loop()
        removed = await loop.run_in_executor(None, remove_watermark, file_path, output_path)
        
        await msg.edit_text(f"✅ **Done!** Removed {removed} watermarks\n📤 Sending cleaned PDF...")
        
        await client.send_document(
            message.chat.id,
            output_path,
            caption=f"✨ **Cleaned PDF**\n• Removed: {removed} watermarks\n• NO white boxes added\n• Only target email and phone number removed",
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

print("🤖 Bot Started - NO WHITE BOXES!")
print("✓ Only removing: tyagimansi1103@gmail.com")
print("✓ Only removing: 10-digit phone numbers")
print("✓ Max 2 watermarks per page")
print("✓ Using fill=None - no white rectangles")

app.run()
