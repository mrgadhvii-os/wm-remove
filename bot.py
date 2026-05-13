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

# ============ WATERMARK REMOVER CLASS WITH RETRY ============
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
    
    async def check_status(self, session: aiohttp.ClientSession, task_id: str, max_wait: int = 60) -> bool:
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
            await asyncio.sleep(random.uniform(2, 3))
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
    
    async def process_single_image_with_retry(self, image_path: str, output_path: str, max_retries: int = 3, progress_callback=None, index=0, total=0) -> bool:
        """Process single image with retry logic"""
        for attempt in range(max_retries):
            try:
                if progress_callback:
                    if attempt > 0:
                        await progress_callback(f"🔄 Retry {attempt}/{max_retries} for image {index}/{total}...")
                    else:
                        await progress_callback(f"🖼️ Processing image {index}/{total}...")
                
                # Create separate session for each image
                async with aiohttp.ClientSession(cookies=self.get_random_cookies()) as session:
                    task_id = await self.create_task(session, image_path)
                    if not task_id:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(random.uniform(2, 4))
                            continue
                        return False
                    
                    if not await self.check_status(session, task_id):
                        if attempt < max_retries - 1:
                            await asyncio.sleep(random.uniform(2, 4))
                            continue
                        return False
                    
                    if await self.download_result(session, task_id, output_path):
                        return True
                    else:
                        if attempt < max_retries - 1:
                            await asyncio.sleep(random.uniform(2, 4))
                            continue
                        return False
                        
            except Exception as e:
                logger.error(f"Error processing {image_path} (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(random.uniform(3, 5))
                    continue
                return False
        
        return False
    
    async def process_batch(self, image_paths: List[str], temp_dir: str, progress_callback=None) -> Tuple[List[str], List[int]]:
        """Process multiple images in parallel with separate sessions and retry"""
        output_paths = []
        failed_pages = []
        
        # Create tasks for all images (each with its own session)
        tasks = []
        for i, img_path in enumerate(image_paths):
            output_path = os.path.join(temp_dir, f"cleaned_{os.path.basename(img_path)}")
            output_paths.append(output_path)
            
            # Create callback wrapper for progress
            async def callback_with_index(msg, idx=i+1, total=len(image_paths)):
                if progress_callback:
                    await progress_callback(f"{msg}")
            
            task = self.process_single_image_with_retry(
                img_path, 
                output_path,
                3,  # max retries
                callback_with_index,
                i+1, 
                len(image_paths)
            )
            tasks.append(task)
        
        # Run all tasks concurrently
        results = await asyncio.gather(*tasks)
        
        # Track failed pages
        successful = []
        for i, success in enumerate(results):
            if success:
                successful.append(output_paths[i])
            else:
                failed_pages.append(i + 1)  # Store page number (1-indexed)
        
        return successful, failed_pages

# ============ PDF PROCESSING FUNCTIONS ============
def get_pdf_info(pdf_path: str) -> Tuple[int, List[float]]:
    """Get PDF page count and page sizes"""
    doc = fitz.open(pdf_path)
    page_count = len(doc)
    page_sizes = []
    
    for page_num in range(page_count):
        page = doc[page_num]
        rect = page.rect
        page_sizes.append((rect.width, rect.height))
    
    doc.close()
    return page_count, page_sizes

def extract_pdf_to_images_with_size(pdf_path: str, temp_dir: str, page_sizes: List[tuple], dpi: int = 150) -> List[str]:
    """Extract PDF pages to images with original dimensions"""
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

def images_to_pdf_preserve_size(image_paths: List[str], output_pdf: str, page_sizes: List[tuple]):
    """Convert images back to PDF preserving original page sizes"""
    doc = fitz.open()
    
    for i, img_path in enumerate(image_paths):
        # Get original page dimensions
        original_width, original_height = page_sizes[i]
        
        # Open image
        img = Image.open(img_path)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as PNG in memory
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG', optimize=True)
        img_bytes.seek(0)
        
        # Create pixmap
        img_pix = fitz.Pixmap(img_bytes)
        
        # Create page with original dimensions
        page = doc.new_page(width=original_width, height=original_height)
        
        # Calculate scaling to fit page while maintaining aspect ratio
        img_width = img_pix.width
        img_height = img_pix.height
        
        # Scale to fit page
        scale_x = original_width / img_width
        scale_y = original_height / img_height
        scale = min(scale_x, scale_y)
        
        scaled_width = img_width * scale
        scaled_height = img_height * scale
        
        # Center the image
        x_offset = (original_width - scaled_width) / 2
        y_offset = (original_height - scaled_height) / 2
        
        # Create rectangle for image placement
        img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_width, y_offset + scaled_height)
        
        # Insert image
        page.insert_image(img_rect, pixmap=img_pix)
        img_pix = None
    
    # Save with compression to keep size minimal
    doc.save(output_pdf, garbage=4, deflate=True, linear=False)
    doc.close()

def images_to_pdf_exact(image_paths: List[str], output_pdf: str, original_pdf_path: str):
    """Convert images back to PDF matching original exactly"""
    # Get original PDF info
    doc_original = fitz.open(original_pdf_path)
    
    doc_new = fitz.open()
    
    for i, img_path in enumerate(image_paths):
        # Get original page
        original_page = doc_original[i]
        original_rect = original_page.rect
        
        # Open image
        img = Image.open(img_path)
        
        # Convert to RGB if needed
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Save as PNG in memory
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        # Create pixmap
        img_pix = fitz.Pixmap(img_bytes)
        
        # Create new page with exact original dimensions
        page = doc_new.new_page(width=original_rect.width, height=original_rect.height)
        
        # Calculate scaling to maintain aspect ratio while filling page
        img_width = img_pix.width
        img_height = img_pix.height
        
        # Scale to exactly fit page
        scale_x = original_rect.width / img_width
        scale_y = original_rect.height / img_height
        
        # Use min scale to ensure image fits without cropping
        scale = min(scale_x, scale_y)
        
        scaled_width = img_width * scale
        scaled_height = img_height * scale
        
        # Center the image
        x_offset = (original_rect.width - scaled_width) / 2
        y_offset = (original_rect.height - scaled_height) / 2
        
        img_rect = fitz.Rect(x_offset, y_offset, x_offset + scaled_width, y_offset + scaled_height)
        
        # Insert image
        page.insert_image(img_rect, pixmap=img_pix)
        img_pix = None
    
    doc_original.close()
    doc_new.save(output_pdf, garbage=4, deflate=True)
    doc_new.close()

def cleanup_temp(temp_dir: str):
    """Clean up temporary directory"""
    try:
        if os.path.exists(temp_dir):
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
            os.rmdir(temp_dir)
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# ============ BOT COMMANDS ============
# Store user processing status
user_tasks = {}

@app.on_message(filters.command(["start"]))
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    await message.reply_text(
        "✨ **Welcome to Watermark Remover Bot!** ✨\n\n"
        "I can remove watermarks from PDF files.\n\n"
        "📌 **How to use:**\n"
        "1. Send me any PDF file\n"
        "2. I'll extract all pages\n"
        "3. Remove watermarks from each page (with retry)\n"
        "4. Send back the cleaned PDF\n\n"
        "⚡ **Features:**\n"
        "• Parallel processing for speed\n"
        "• Auto-retry failed pages (3 attempts)\n"
        "• Preserves original PDF size & quality\n"
        "• No file size limits\n"
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
        "**Features:**\n"
        "• Auto-retry failed pages\n"
        "• Preserves original PDF dimensions\n"
        "• Maintains same file size\n\n"
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
        
        # Get original PDF info
        original_page_count, original_page_sizes = get_pdf_info(pdf_path)
        original_size = os.path.getsize(pdf_path)
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Extract PDF to images
        await progress_msg.edit_text("📄 **Extracting PDF pages...**\n⏳ Converting to images...")
        image_paths = extract_pdf_to_images_with_size(pdf_path, extract_dir, original_page_sizes)
        total_pages = len(image_paths)
        
        await progress_msg.edit_text(
            f"✅ **PDF extracted successfully!**\n"
            f"📄 Total pages: **{total_pages}**\n"
            f"💾 Original size: **{original_size / (1024*1024):.2f} MB**\n\n"
            f"🔄 **Removing watermarks...**\n"
            f"⚡ Processing **{total_pages}** pages in parallel with auto-retry..."
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
                f"🔄 Auto-retry: Enabled (3 attempts)\n"
                f"⚡ Parallel processing: Active"
            )
        
        # Process images in parallel with retry
        cleaned_images, failed_pages = await remover.process_batch(
            image_paths, 
            cleaned_dir, 
            update_progress
        )
        
        # Check for cancellation
        if user_tasks[user_id]['cancel']:
            raise Exception("Task cancelled")
        
        # Show retry results
        retry_msg = ""
        if failed_pages:
            retry_msg = f"\n⚠️ Failed pages: {', '.join(map(str, failed_pages))}"
        
        if not cleaned_images:
            await progress_msg.edit_text(
                f"❌ **Failed to process all images!**\n"
                f"Please try again later.\n{retry_msg}"
            )
            return
        
        # Convert back to PDF preserving original size and dimensions
        await progress_msg.edit_text(
            f"📚 **Creating cleaned PDF...**\n"
            f"✅ Successfully processed: **{len(cleaned_images)}/{total_pages}** pages\n"
            f"🔄 Preserving original PDF dimensions...{retry_msg}"
        )
        
        output_pdf = os.path.join(download_dir, f"{document.file_name}")
        # Use exact PDF preservation
        images_to_pdf_exact(cleaned_images, output_pdf, pdf_path)
        
        # Check output file size
        output_size = os.path.getsize(output_pdf)
        output_size_mb = output_size / (1024 * 1024)
        original_size_mb = original_size / (1024 * 1024)
        size_diff = abs(output_size - original_size)
        size_diff_percent = (size_diff / original_size) * 100
        
        # Send result
        await progress_msg.edit_text(
            f"✅ **Watermark Removed Successfully!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📄 Original: `{document.file_name}`\n"
            f"📊 Pages: **{len(cleaned_images)}/{total_pages}**\n"
            f"💾 Original size: **{original_size_mb:.2f} MB**\n"
            f"💾 New size: **{output_size_mb:.2f} MB**\n"
            f"📊 Size difference: **{size_diff_percent:.1f}%**\n"
            f"{retry_msg}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📤 **Sending cleaned PDF...**",
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Send the cleaned PDF with same filename and caption
        with open(output_pdf, 'rb') as f:
            await client.send_document(
                chat_id=message.chat.id,
                document=f,
                caption=f"✅ **{document.file_name}**\n━━━━━━━━━━━━━━━━━━━━━\n✨ Watermarks removed successfully!\n📊 Pages: {len(cleaned_images)}/{total_pages}",
                file_name=document.file_name  # Same filename as original
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
    print("⚡ Using parallel processing with auto-retry")
    print("🔄 Failed pages will be retried 3 times")
    
    app.run()

if __name__ == "__main__":
    main()
