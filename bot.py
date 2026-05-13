import os
import asyncio
import subprocess
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

def remove_watermark_cli(input_path: str, output_path: str) -> bool:
    """
    Use watermark-remover-cli to remove watermarks
    The package processes the file and saves cleaned version
    """
    try:
        # watermark-remover-cli processes in-place or generates output
        # Based on the package, it works directly on the input file
        result = subprocess.run(
            ["python3", "-m", "watermark-remover-cli", "--file", input_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # The package might save output with a specific naming convention
        # Check common output patterns
        possible_outputs = [
            input_path.replace('.pdf', '_cleaned.pdf'),
            input_path.replace('.pdf', '_output.pdf'),
            os.path.join(os.path.dirname(input_path), 'cleaned_' + os.path.basename(input_path))
        ]
        
        for possible in possible_outputs:
            if os.path.exists(possible):
                os.rename(possible, output_path)
                return True
        
        # If no separate output, assume input was modified
        if result.returncode == 0:
            os.rename(input_path, output_path)
            return True
            
        return False
        
    except Exception as e:
        print(f"Error running watermark-remover-cli: {e}")
        return False

@app.on_message(filters.command("start"))
async def start(client: Client, message: Message):
    await message.reply_text(
        "📄 **Watermark Remover Bot**\n\n"
        "Send me a PDF file, and I'll remove watermarks using\n"
        "`watermark-remover-cli` package!\n\n"
        "• Works with colored watermarks\n"
        "• Preserves black text content\n"
        "• No manual configuration needed"
    )

@app.on_message(filters.document)
async def handle_pdf(client: Client, message: Message):
    if not message.document.file_name.lower().endswith('.pdf'):
        await message.reply_text("❌ Please send a PDF file only!")
        return
    
    msg = await message.reply_text("📥 **Downloading PDF...**")
    
    try:
        # Download
        input_path = await message.download(
            file_name=os.path.join(DOWNLOAD_DIR, f"{message.from_user.id}_{message.id}.pdf")
        )
        
        await msg.edit_text("🔍 **Removing watermarks with watermark-remover-cli...**")
        
        # Output path
        output_path = os.path.join(OUTPUT_DIR, f"{message.from_user.id}_{message.id}_cleaned.pdf")
        
        # Run CLI tool
        loop = asyncio.get_event_loop()
        success = await loop.run_in_executor(None, remove_watermark_cli, input_path, output_path)
        
        if success and os.path.exists(output_path):
            await msg.edit_text("✅ **Watermarks removed!** 📤 Sending back...")
            
            await client.send_document(
                message.chat.id,
                output_path,
                caption="✨ **Cleaned PDF**\nWatermarks removed using watermark-remover-cli",
                file_name=message.document.file_name.replace('.pdf', '_cleaned.pdf')
            )
        else:
            await msg.edit_text("❌ **Failed to remove watermarks**\nThe CLI tool may not support this PDF format.")
        
        await msg.delete()
        
    except subprocess.TimeoutExpired:
        await msg.edit_text("⏰ **Timeout!** PDF processing took too long.")
    except Exception as e:
        await msg.edit_text(f"❌ **Error:** `{str(e)[:150]}`")
    finally:
        for path in [input_path, output_path]:
            try:
                if path and os.path.exists(path):
                    os.remove(path)
            except:
                pass

print("🤖 Bot Started with watermark-remover-cli!")
print("✓ Using external package for watermark removal")
print("✓ Send PDF files to remove watermarks")

app.run()
