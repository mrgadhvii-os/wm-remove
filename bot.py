import os
import re
import asyncio
import logging
from pathlib import Path
from typing import Tuple, List
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ParseMode
import fitz

# Bot Configuration
BOT_TOKEN = "8445635159:AAHS0zXgHrlffS96oDyjjg0m-y7gF7sfosY"
API_ID = 27567486
API_HASH = "b1760d4b5ef697bb8da4e7ac4e261c49"

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize Pyrogram Client
app = Client(
    "pdf_cleaner_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ============ WATERMARK MARKERS ============
MARKERS = (
    "9917753800 - tyagimansi1103@gmail.com",
    "9917753800",
    "tyagimansi1103@gmail.com",
)

# Rotated watermark paint block in page stream
MAIN_WATERMARK_RE = re.compile(
    rb"/GS\d+\s+gs\s*"
    rb"BT\s+/F2\s+22\.00\s+Tf\s+ET\s*"
    rb"q\s+0\.70711\s+0\.70711\s+-0\.70711\s+0\.70711\s+[\d.]+\s+[\d.]+\s+cm\s+"
    rb"1\s+0\s+0\s+1\s+[-\d.]+\s+[-\d.]+\s+cm\s*"
    rb"q\s+0\.800\s+0\.792\s+0\.776\s+rg\s+BT\s+[\d.]+\s+[\d.]+\s+Td\s*"
    rb"\(9917753800\s*-\s*tyagimansi1103@gmail\.com\)\s*Tj\s+ET\s+Q\s*"
    rb"Q\s*",
)


def strip_watermark_from_stream(stream: bytes) -> Tuple[bytes, int]:
    """Remove watermark from PDF stream"""
    new_stream, count = MAIN_WATERMARK_RE.subn(b"", stream)
    return new_stream, count


def remove_watermarks(input_path: Path, output_path: Path) -> Tuple[int, int, int]:
    """
    Remove watermarks from PDF
    Returns: (total_pages, pages_touched, blocks_removed)
    """
    doc = fitz.open(input_path)
    total_pages = len(doc)
    pages_touched = 0
    blocks_removed = 0

    for page in doc:
        page_removed = 0
        for xref in page.get_contents():
            stream = doc.xref_stream(xref)
            new_stream, count = strip_watermark_from_stream(stream)
            if count:
                doc.update_stream(xref, new_stream)
                page_removed += count
        if page_removed:
            pages_touched += 1
            blocks_removed += page_removed

    doc.save(output_path, garbage=4, deflate=True)
    doc.close()
    return total_pages, pages_touched, blocks_removed


def verify_clean(path: Path) -> List[int]:
    """Verify if any watermark text remains"""
    doc = fitz.open(path)
    dirty_pages: List[int] = []
    for i, page in enumerate(doc):
        text = page.get_text()
        if any(marker in text for marker in MARKERS):
            dirty_pages.append(i + 1)  # 1-indexed page numbers
    doc.close()
    return dirty_pages


def get_pdf_info(pdf_path: Path) -> Tuple[int, float]:
    """Get PDF page count and file size in MB"""
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    doc.close()
    file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
    return page_count, file_size_mb


def cleanup_temp(file_path: Path):
    """Clean up temporary file"""
    try:
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.error(f"Cleanup error: {e}")


# Store user processing status
user_tasks = {}


@app.on_message(filters.command(["start"]))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    await message.reply_text(
        "✨ **PDF Watermark Remover Bot** ✨\n\n"
        "I can remove watermarks from PDF files.\n\n"
        "📌 **How to use:**\n"
        "• Send me any PDF file with watermarks\n"
        "• I'll remove the watermarks automatically\n"
        "• Get back a clean PDF with same name\n\n"
        "⚡ **Features:**\n"
        "• Preserves original PDF quality\n"
        "• No content loss (no white boxes)\n"
        "• Shows removal statistics\n\n"
        "📤 **Just send me a PDF file to start!**",
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command(["help"]))
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    await message.reply_text(
        "📖 **Help Guide**\n\n"
        "**How to use:**\n"
        "• Send any PDF document containing watermarks\n"
        "• Wait for processing\n"
        "• Get watermark-free PDF\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/cancel - Cancel current task\n\n"
        "**Output Format:**\n"
        "`Pages: X | Cleaned: Y | Stream blocks removed: Z`\n"
        "`OK: watermark gone, content untouched`\n\n"
        "**Note:** Processing time depends on file size.",
        parse_mode=ParseMode.MARKDOWN
    )


@app.on_message(filters.command(["cancel"]))
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    if user_id in user_tasks:
        user_tasks[user_id]['cancel'] = True
        await message.reply_text("❌ Cancelled current task!")
    else:
        await message.reply_text("ℹ️ No active task to cancel.")


@app.on_message(filters.document)
async def handle_pdf(client: Client, message: Message):
    """Handle incoming PDF files"""
    user_id = message.from_user.id
    
    # Check if document is PDF
    document = message.document
    if not document.file_name.lower().endswith('.pdf'):
        await message.reply_text("❌ Please send a **PDF file** only!", parse_mode=ParseMode.MARKDOWN)
        return
    
    # Check if user already has a task
    if user_id in user_tasks:
        await message.reply_text("⚠️ You already have a task running!\nUse /cancel to stop it.")
        return
    
    # Create temp directory for this user
    temp_dir = Path(f"temp/{user_id}")
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Store task info
    user_tasks[user_id] = {
        'cancel': False,
        'temp_dir': temp_dir
    }
    
    # Send initial message
    progress_msg = await message.reply_text(
        "📥 **Downloading your PDF...**",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Download PDF
        input_pdf = temp_dir / document.file_name
        await progress_msg.edit_text("📥 **Downloading PDF...**\n⏳ Please wait...")
        await client.download_media(message, file_name=str(input_pdf))
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Get original PDF info
        original_page_count, original_size_mb = get_pdf_info(input_pdf)
        
        await progress_msg.edit_text(
            f"📄 **PDF Loaded Successfully!**\n"
            f"📊 Pages: **{original_page_count}**\n"
            f"💾 Size: **{original_size_mb:.2f} MB**\n\n"
            f"🔄 **Removing watermarks...**\n"
            f"⏳ Please wait..."
        )
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Remove watermarks
        output_pdf = temp_dir / f"cleaned_{document.file_name}"
        total_pages, pages_touched, blocks_removed = remove_watermarks(input_pdf, output_pdf)
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Verify the result
        leftover_pages = verify_clean(output_pdf)
        
        # Get output file size
        output_size_mb = output_pdf.stat().st_size / (1024 * 1024)
        
        # Prepare result message
        result_text = (
            f"✅ **Watermark Removal Complete!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 **File:** `{document.file_name}`\n"
            f"📊 **Pages:** `{total_pages}` | **Cleaned:** `{pages_touched}` | **Blocks removed:** `{blocks_removed}`\n"
            f"💾 **Size:** `{original_size_mb:.2f} MB` → `{output_size_mb:.2f} MB`\n"
        )
        
        if leftover_pages:
            result_text += f"⚠️ **Warning:** Watermark still on pages: `{leftover_pages}`\n"
        else:
            result_text += f"✅ **OK:** `watermark gone, content untouched (no white boxes)`\n"
        
        result_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        result_text += f"📤 **Sending cleaned PDF...**"
        
        await progress_msg.edit_text(result_text, parse_mode=ParseMode.MARKDOWN)
        
        # Send the cleaned PDF with same filename
        with open(output_pdf, 'rb') as f:
            caption_text = (
                f"✅ **{document.file_name}**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 **Pages:** `{total_pages}` | **Cleaned:** `{pages_touched}` | **Blocks removed:** `{blocks_removed}`\n"
            )
            if leftover_pages:
                caption_text += f"⚠️ **Warning:** Watermark still on pages: `{leftover_pages}`\n"
            else:
                caption_text += f"✅ **OK:** `watermark gone, content untouched`\n"
            
            await client.send_document(
                chat_id=message.chat.id,
                document=f,
                caption=caption_text,
                file_name=document.file_name  # Same filename as original
            )
        
        await progress_msg.delete()
        
        # Send final confirmation
        final_text = (
            f"🎉 **Done!** Watermark-free PDF sent above.\n\n"
            f"📊 **Statistics:**\n"
            f"• Total pages: `{total_pages}`\n"
            f"• Pages cleaned: `{pages_touched}`\n"
            f"• Blocks removed: `{blocks_removed}`\n"
        )
        if not leftover_pages:
            final_text += f"• Status: `watermark completely removed`\n\n"
        final_text += f"📤 Send another PDF to continue!"
        
        await message.reply_text(final_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Error processing PDF for user {user_id}: {e}")
        if "cancelled" in str(e).lower():
            await progress_msg.edit_text("❌ **Task cancelled!**\nSend /start to begin again.")
        else:
            await progress_msg.edit_text(
                f"❌ **Error processing PDF!**\n"
                f"Reason: `{str(e)[:100]}`\n\n"
                f"Please try again later."
            )
    
    finally:
        # Cleanup temporary directory
        if 'temp_dir' in user_tasks.get(user_id, {}):
            cleanup_temp(user_tasks[user_id]['temp_dir'])
            try:
                user_tasks[user_id]['temp_dir'].rmdir()
            except:
                pass
        
        # Remove user from active tasks
        if user_id in user_tasks:
            del user_tasks[user_id]


@app.on_message(filters.photo)
async def handle_photo(client: Client, message: Message):
    """Handle photo messages"""
    await message.reply_text(
        "📸 **Photo received!**\n\n"
        "But I only process **PDF files**.\n"
        "Please send me a **PDF document** instead.",
        parse_mode=ParseMode.MARKDOWN
    )


# ============ MAIN ============
def main():
    """Start the bot"""
    print("🤖 Starting PDF Watermark Remover Bot...")
    print("✅ Bot is running!")
    print("📌 Send any PDF to remove watermarks")
    print("🔧 Using direct PDF stream manipulation")
    print("✨ Preserves original content quality")
    
    # Create temp directory
    Path("temp").mkdir(exist_ok=True)
    
    app.run()


if __name__ == "__main__":
    main()
