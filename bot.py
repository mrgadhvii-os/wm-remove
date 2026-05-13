import os
import re
import asyncio
import aiohttp
import random
import time
import uuid
from typing import Optional, List
from pathlib import Path
import fitz
from PIL import Image
import io
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.enums import ParseMode
import logging

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
    "watermark_remover_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

# ============ WATERMARK REMOVER CLASS ============
class WatermarkRemover:
    def __init__(self):
        self.base_url = "https://phototune.ai"
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36"
        ]
    
    def get_random_headers(self):
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9," + random.choice(["hi,en", "fr,en", "de,en"]),
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": self.base_url,
            "Referer": f"{self.base_url}/process-watermark",
            "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": random.choice(['"Windows"', '"macOS"', '"Linux"']),
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "X-Request-ID": str(uuid.uuid4())
        }
    
    def get_random_cookies(self):
        return {
            "_ga": f"GA1.1.{random.randint(1000000,9999999)}.{int(time.time())}",
            "_clck": f"{random.randint(100000,999999)}%5E2%5Eg{random.randint(10,99)}%5E0%5E{random.randint(1000,9999)}",
            "pt_credits": f"{random.randint(5,20)}|{int(time.time()) + random.randint(86400,604800)}",
            "_ga_YW8BBVTYQX": f"GS2.1.s{int(time.time())}$o1$g1$t{int(time.time())}$j54$l0$h0"
        }
    
    async def create_task(self, session: aiohttp.ClientSession, image_path: str) -> Optional[str]:
        """Create watermark removal task for single image"""
        headers = self.get_random_headers()
        
        with open(image_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field('file', f, filename=os.path.basename(image_path), content_type='image/jpeg')
            data.add_field('type', 'watermark')
            
            async with session.post(f"{self.base_url}/api/tasks", headers=headers, data=data) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result.get("task_id")
        return None
    
    async def check_status(self, session: aiohttp.ClientSession, task_id: str, max_wait: int = 45) -> bool:
        """Check task status until completion"""
        headers = self.get_random_headers()
        waited = 0
        
        while waited < max_wait:
            async with session.get(f"{self.base_url}/api/tasks/{task_id}", headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "completed":
                        return True
                    elif data.get("status") == "failed":
                        return False
            await asyncio.sleep(random.uniform(1.5, 2.5))
            waited += 2
        return False
    
    async def download_result(self, session: aiohttp.ClientSession, task_id: str, output_path: str) -> bool:
        """Download processed image"""
        headers = self.get_random_headers()
        
        async with session.get(f"{self.base_url}/api/tasks/{task_id}/result", headers=headers) as resp:
            if resp.status == 200:
                with open(output_path, "wb") as f:
                    f.write(await resp.read())
                return True
        return False
    
    async def process_single_image(self, image_path: str, output_path: str, progress_callback=None, index=0, total=0) -> bool:
        """Process single image with its own session"""
        try:
            if progress_callback:
                await progress_callback(f"🖼️ Processing image {index}/{total}...")
            
            # Create separate session for each image
            async with aiohttp.ClientSession(cookies=self.get_random_cookies()) as session:
                task_id = await self.create_task(session, image_path)
                if not task_id:
                    return False
                
                if not await self.check_status(session, task_id):
                    return False
                
                return await self.download_result(session, task_id, output_path)
        except Exception as e:
            logger.error(f"Error processing {image_path}: {e}")
            return False
    
    async def process_batch(self, image_paths: List[str], temp_dir: str, progress_callback=None) -> List[str]:
        """Process multiple images in parallel with separate sessions"""
        output_paths = []
        
        # Create tasks for all images (each with its own session)
        tasks = []
        for i, img_path in enumerate(image_paths):
            output_path = os.path.join(temp_dir, f"cleaned_{os.path.basename(img_path)}")
            output_paths.append(output_path)
            
            # Create callback wrapper for progress
            async def callback_with_index(msg, idx=i+1, total=len(image_paths)):
                if progress_callback:
                    await progress_callback(f"🖼️ Processing image {idx}/{total}...")
            
            task = self.process_single_image(
                img_path, 
                output_path, 
                callback_with_index,
                i+1, 
                len(image_paths)
            )
            tasks.append(task)
        
        # Run all tasks concurrently (each with its own session)
        results = await asyncio.gather(*tasks)
        
        return [output_paths[i] for i, success in enumerate(results) if success]

# ============ PDF PROCESSING FUNCTIONS ============
def extract_pdf_to_images(pdf_path: str, temp_dir: str, dpi: int = 150) -> List[str]:
    """Extract PDF pages to images"""
    doc = fitz.open(pdf_path)
    image_paths = []
    zoom = dpi / 72
    mat = fitz.Matrix(zoom, zoom)
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        output_path = os.path.join(temp_dir, f"page_{page_num + 1:04d}.jpg")
        pix.save(output_path)
        image_paths.append(output_path)
    
    doc.close()
    return image_paths

def images_to_pdf(image_paths: List[str], output_pdf: str):
    """Convert images back to PDF"""
    doc = fitz.open()
    
    for img_path in image_paths:
        img = Image.open(img_path)
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        img_pix = fitz.Pixmap(img_bytes)
        img_rect = fitz.Rect(0, 0, img_pix.width, img_pix.height)
        
        page = doc.new_page(width=img_pix.width, height=img_pix.height)
        page.insert_image(img_rect, pixmap=img_pix)
        img_pix = None
    
    doc.save(output_pdf, garbage=4, deflate=True)
    doc.close()

def cleanup_temp(temp_dir: str):
    """Clean up temporary directory"""
    try:
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                os.remove(os.path.join(temp_dir, file))
            os.rmdir(temp_dir)
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# ============ BOT COMMANDS ============
# Store user processing status
user_tasks = {}

async def send_progress_message(message: Message, text: str, edit: bool = True):
    """Send or edit progress message"""
    try:
        if edit and hasattr(message, 'edit_text'):
            await message.edit_text(text)
        else:
            return await message.reply_text(text)
    except:
        return await message.reply_text(text)

@app.on_message(filters.command(["start"]))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    await message.reply_text(
        "✨ **Welcome to Watermark Remover Bot!** ✨\n\n"
        "I can remove watermarks from PDF files.\n\n"
        "📌 **How to use:**\n"
        "1. Send me any PDF file\n"
        "2. I'll extract all pages\n"
        "3. Remove watermarks from each page\n"
        "4. Send back the cleaned PDF\n\n"
        "⚡ **Features:**\n"
        "• Parallel processing for speed\n"
        "• No file size limits\n"
        "• Preserves original quality\n"
        "• Shows real-time progress\n\n"
        "📤 **Just send me a PDF file to start!**",
        parse_mode=ParseMode.MARKDOWN
    )

@app.on_message(filters.command(["help"]))
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    await message.reply_text(
        "📖 **Help Guide**\n\n"
        "**How to use:**\n"
        "• Send any PDF document\n"
        "• Wait for processing\n"
        "• Get watermark-free PDF\n\n"
        "**Commands:**\n"
        "/start - Start the bot\n"
        "/help - Show this help\n"
        "/cancel - Cancel current task\n\n"
        "**Note:** Processing time depends on number of pages.",
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
    
    # Create unique directories for this user
    timestamp = int(time.time())
    download_dir = f"downloads/{user_id}_{timestamp}"
    extract_dir = f"temp_extract/{user_id}_{timestamp}"
    cleaned_dir = f"temp_cleaned/{user_id}_{timestamp}"
    
    os.makedirs(download_dir, exist_ok=True)
    os.makedirs(extract_dir, exist_ok=True)
    os.makedirs(cleaned_dir, exist_ok=True)
    
    # Store task info
    user_tasks[user_id] = {
        'cancel': False,
        'download_dir': download_dir,
        'extract_dir': extract_dir,
        'cleaned_dir': cleaned_dir
    }
    
    # Send initial message
    progress_msg = await message.reply_text(
        "📥 **Downloading your PDF...**",
        parse_mode=ParseMode.MARKDOWN
    )
    
    try:
        # Download PDF
        pdf_path = os.path.join(download_dir, document.file_name)
        await progress_msg.edit_text("📥 **Downloading PDF...**\n⏳ Please wait...")
        await client.download_media(message, file_name=pdf_path)
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Extract PDF to images
        await progress_msg.edit_text("📄 **Extracting PDF pages...**\n⏳ Converting to images...")
        image_paths = extract_pdf_to_images(pdf_path, extract_dir)
        total_pages = len(image_paths)
        
        await progress_msg.edit_text(
            f"✅ **PDF extracted successfully!**\n"
            f"📄 Total pages: **{total_pages}**\n\n"
            f"🔄 **Removing watermarks...**\n"
            f"⚡ Processing **{total_pages}** pages in parallel..."
        )
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Create watermark remover
        remover = WatermarkRemover()
        
        # Progress tracking
        async def update_progress(text):
            if user_tasks[user_id]['cancel']:
                raise Exception("Task cancelled")
            await progress_msg.edit_text(
                f"🔄 **Removing Watermarks**\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{text}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Total pages: {total_pages}\n"
                f"⚡ Parallel processing enabled"
            )
        
        # Process images in parallel
        cleaned_images = await remover.process_batch(
            image_paths, 
            cleaned_dir, 
            update_progress
        )
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        if not cleaned_images:
            await progress_msg.edit_text("❌ **Failed to process images!**\nPlease try again later.")
            return
        
        # Convert back to PDF
        await progress_msg.edit_text(
            f"📚 **Creating cleaned PDF...**\n"
            f"✅ Successfully processed: **{len(cleaned_images)}/{total_pages}** pages"
        )
        
        output_pdf = os.path.join(download_dir, f"cleaned_{document.file_name}")
        images_to_pdf(cleaned_images, output_pdf)
        
        # Check file size
        file_size = os.path.getsize(output_pdf)
        file_size_mb = file_size / (1024 * 1024)
        
        # Send result
        await progress_msg.edit_text(
            f"✅ **Watermark Removed Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 Original: `{document.file_name}`\n"
            f"📊 Pages processed: **{len(cleaned_images)}/{total_pages}**\n"
            f"💾 File size: **{file_size_mb:.2f} MB**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 **Sending cleaned PDF...**",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send the cleaned PDF with same filename and caption
        with open(output_pdf, 'rb') as f:
            await client.send_document(
                chat_id=message.chat.id,
                document=f,
                caption=f"✅ **{document.file_name}**\n━━━━━━━━━━━━━━━━━━━━━\n✨ Watermarks removed successfully!",
                file_name=f"{document.file_name}"
            )
        
        await progress_msg.delete()
        await message.reply_text(
            "🎉 **Done!** Your watermark-free PDF has been sent above.\n\n"
            "📤 Send another PDF to continue!",
            parse_mode=ParseMode.MARKDOWN
        )
        
    except Exception as e:
        logger.error(f"Error processing PDF for user {user_id}: {e}")
        if "cancelled" in str(e).lower():
            await progress_msg.edit_text("❌ **Task cancelled!**\nSend /start to begin again.")
        else:
            await progress_msg.edit_text(
                f"❌ **Error processing PDF!**\n"
                f"Reason: {str(e)[:100]}\n\n"
                f"Please try again later."
            )
    
    finally:
        # Cleanup temporary directories
        cleanup_temp(download_dir)
        cleanup_temp(extract_dir)
        cleanup_temp(cleaned_dir)
        
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
    print("🤖 Starting Watermark Remover Bot...")
    print("✅ Bot is running!")
    print("📌 Send any PDF to remove watermarks")
    print("⚡ Using parallel processing for speed")
    
    app.run()

if __name__ == "__main__":
    main()
