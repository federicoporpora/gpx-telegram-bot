import os
import requests
import logging
import threading
import shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.error import NetworkError
import urllib.request
import sys
from dotenv import load_dotenv
import gpx_utils
import gpx_hr_merger

load_dotenv()

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"The bot is online on Render!")

def run_dummy_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_TELEGRAM_ID = int(os.environ.get("MY_TELEGRAM_ID", 0))

def track_user(user_id: int):
    file_path = "users.txt"
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write(f"{user_id}\n")
        return
    with open(file_path, "r") as f:
        users = f.read().splitlines()
    if str(user_id) not in users:
        with open(file_path, "a") as f:
            f.write(f"{user_id}\n")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    track_user(update.effective_user.id)
    context.user_data['files'] = []
    
    keyboard = [
        [
            InlineKeyboardButton("🔗 Merge GPX/HR", callback_data='action_merge_hr'),
            InlineKeyboardButton("✂️ Crop File", callback_data='action_crop')
        ],
        [
            InlineKeyboardButton("⏱️ Fix Time", callback_data='action_fix_time'),
            InlineKeyboardButton("🔗 Merge Tracks", callback_data='action_merge_seq')
        ],
        [
            InlineKeyboardButton("⛰️ Fix Elevation", callback_data='action_fix_elev'),
            InlineKeyboardButton("🗺️ Generate Map", callback_data='action_map')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        "Hello! I'm ready. 🏃‍♂️ Choose a function from the menu:\n"
        "💡 Use /stop in case of errors."
    )
    
    if update.message:
        await update.message.reply_text(msg, reply_markup=reply_markup)
    elif update.callback_query:
        await update.callback_query.message.edit_text(msg, reply_markup=reply_markup)

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'files' in context.user_data:
        for f in context.user_data['files']:
            if os.path.exists(f): os.remove(f)
    context.user_data['files'] = []
    context.user_data['action'] = None
    await update.message.reply_text("🛑 Memory cleared!")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == 'back_to_start':
        await start(update, context)
        return
        
    if data.startswith('action_'):
        context.user_data['action'] = data
        context.user_data['files'] = []
        
        back_keyboard = [[InlineKeyboardButton("🔙 Back", callback_data='back_to_start')]]
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        
        if data == 'action_merge_hr':
            msg = "🔗 **Merge GPX and HR**\nSend the GPS track file first (e.g., from watch or app)."
        elif data == 'action_crop':
            msg = "✂️ **Crop GPX**\nSend the GPX file to crop."
        elif data == 'action_fix_time':
            msg = "⏱️ **Fix Time/Pace**\nSend the GPX file to fix time."
        elif data == 'action_merge_seq':
            msg = "🔗 **Merge Tracks (Sequential)**\nSend the GPX files in chronological order. When done, press 'Done'."
        elif data == 'action_fix_elev':
            msg = "⛰️ **Fix Elevation**\nSend the GPX file to recalculate elevation."
        elif data == 'action_map':
            msg = "🗺️ **Generate Map**\nSend the GPX file to generate a map."
            
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        
    elif data == 'execute_merge_seq':
        await process_merge_seq(update.callback_query.message, context)
        
    elif data.startswith('mapstyle_'):
        style = data.split('_')[1]
        context.user_data['map_style'] = style
        keyboard = [
            [
                InlineKeyboardButton("🟠 Orange", callback_data='mapcolor_#FC4C02'),
                InlineKeyboardButton("🔴 Red", callback_data='mapcolor_#FF0000')
            ],
            [
                InlineKeyboardButton("🔵 Blue", callback_data='mapcolor_#0000FF'),
                InlineKeyboardButton("🟢 Green", callback_data='mapcolor_#00FF00')
            ],
            [
                InlineKeyboardButton("⚫ Black", callback_data='mapcolor_#000000'),
                InlineKeyboardButton("⚪ White", callback_data='mapcolor_#FFFFFF')
            ]
        ]
        await query.edit_message_text("🎨 Choose the track color:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith('mapcolor_'):
        color = data.split('_')[1]
        context.user_data['map_color'] = color
        await process_map(update.callback_query.message, context)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')
    if not action:
        await update.message.reply_text("⚠️ Select an action from /start first.")
        return
        
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    unique_file_name = f"{update.message.message_id}_{file_name}"
    await file.download_to_drive(unique_file_name)
    
    if 'files' not in context.user_data:
        context.user_data['files'] = []
    context.user_data['files'].append(unique_file_name)
    
    files = context.user_data['files']
    
    if action == 'action_merge_hr':
        if len(files) == 1:
            await update.message.reply_text(f"✅ Received GPS: {file_name}\nNow send me the heart rate (HR) file.")
        elif len(files) == 2:
            await update.message.reply_text("✅ Received both! Now send me the total distance in km (e.g., 10.5).")
            
    elif action == 'action_crop':
        if len(files) == 1:
            await update.message.reply_text("✅ Received! Send me the km to crop at the start and end separated by a space.\nEx: `1.5 0.5` to crop 1.5km from the start and 0.5km from the end.\nEx: `0 2.0` to remove 2km at the end.", parse_mode='Markdown')
            
    elif action == 'action_fix_time':
        if len(files) == 1:
            await update.message.reply_text("✅ Received! Send me the total minutes the activity should last.\nEx: `45.5` for 45 minutes and 30 seconds.", parse_mode='Markdown')
            
    elif action == 'action_merge_seq':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Done (Merge Tracks)", callback_data='execute_merge_seq')]])
        await update.message.reply_text(f"✅ Received file {len(files)}: {file_name}. Send the next one or press Done.", reply_markup=markup)
        
    elif action == 'action_fix_elev':
        if len(files) == 1:
            await process_fix_elev(update.message, context)
            
    elif action == 'action_map':
        if len(files) == 1:
            keyboard = [
                [
                    InlineKeyboardButton("🌑 Dark", callback_data='mapstyle_dark'),
                    InlineKeyboardButton("☀️ Light", callback_data='mapstyle_light')
                ],
                [
                    InlineKeyboardButton("⛰️ Topographic", callback_data='mapstyle_topo'),
                    InlineKeyboardButton("🛰️ Satellite", callback_data='mapstyle_satellite')
                ],
                [
                    InlineKeyboardButton("🔲 Transparent (PNG)", callback_data='mapstyle_transparent')
                ]
            ]
            await update.message.reply_text("✅ File received! Choose the map style:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')
    files = context.user_data.get('files', [])
    
    if not action or not files:
        await update.message.reply_text("⚠️ Select an action and send a file first.")
        return
        
    text = update.message.text.replace(',', '.')
    
    if action == 'action_merge_hr':
        if len(files) < 2: return
        try:
            dist_km = float(text)
            await process_merge_hr(update.message, context, dist_km)
        except ValueError:
            await update.message.reply_text("⚠️ Invalid number.")
            
    elif action == 'action_crop':
        try:
            parts = text.split()
            start_km = float(parts[0])
            end_km = float(parts[1]) if len(parts) > 1 else 0.0
            await process_crop(update.message, context, start_km, end_km)
        except ValueError:
            await update.message.reply_text("⚠️ Invalid format. Example: `1.5 0.5`", parse_mode='Markdown')
            
    elif action == 'action_fix_time':
        try:
            mins = float(text)
            await process_fix_time(update.message, context, mins)
        except ValueError:
            await update.message.reply_text("⚠️ Invalid number. Example: `45.5`", parse_mode='Markdown')

# --- PROCESSING FUNCTIONS ---

async def cleanup(context):
    for f in context.user_data.get('files', []):
        if os.path.exists(f): os.remove(f)
    context.user_data['files'] = []
    context.user_data['action'] = None
    if os.path.exists("output_fixed.tcx"): os.remove("output_fixed.tcx")
    if os.path.exists("output.gpx"): os.remove("output.gpx")
    if os.path.exists("map.png"): os.remove("map.png")

async def process_merge_hr(message, context, dist_km):
    await message.reply_text("⚙️ Processing in progress...")
    f1, f2 = context.user_data['files'][0], context.user_data['files'][1]
    
    try:
        if len(gpx_hr_merger.load_hr_data(f1)) > 0:
            file_hr, file_gps = f1, f2
        else:
            file_hr, file_gps = f2, f1
            
        shutil.copy(file_gps, "GPS.gpx")
        shutil.copy(file_hr, "HR.gpx")
        
        old_argv = sys.argv
        sys.argv = ['dummy.py', str(dist_km)]
        gpx_hr_merger.main()
        sys.argv = old_argv
        
        with open("output_fixed.tcx", "rb") as doc:
            await message.reply_document(doc, filename="Merged_Activity.tcx")
    except Exception as e:
        await message.reply_text(f"❌ Processing error: {e}")
    finally:
        if os.path.exists("GPS.gpx"): os.remove("GPS.gpx")
        if os.path.exists("HR.gpx"): os.remove("HR.gpx")
        await cleanup(context)

async def process_crop(message, context, start_km, end_km):
    await message.reply_text("⚙️ Cropping in progress...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.crop_gpx(f, start_km, end_km, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Cropped.gpx")
    else:
        await message.reply_text("❌ Cropping error. Make sure the km are valid.")
    await cleanup(context)

async def process_fix_time(message, context, target_mins):
    await message.reply_text("⚙️ Recalculating timestamps in progress...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.fix_time(f, target_mins, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Recalculated_Time.gpx")
    else:
        await message.reply_text("❌ Error during recalculation.")
    await cleanup(context)

async def process_merge_seq(message, context):
    await message.reply_text("⚙️ Merging tracks in progress...")
    files = context.user_data['files']
    out = "output.gpx"
    if gpx_utils.merge_sequential(files, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Merged_Track.gpx")
    else:
        await message.reply_text("❌ Error during merging.")
    await cleanup(context)

async def process_fix_elev(message, context):
    await message.reply_text("⚙️ Downloading topographic elevations in progress (might take a minute)...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.fix_elevation(f, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Recalculated_Elevation.gpx")
    else:
        await message.reply_text("❌ Error during elevation recalculation.")
    await cleanup(context)

async def process_map(message, context):
    await message.reply_text("🎨 Generating map in progress...")
    f = context.user_data['files'][0]
    style = context.user_data.get('map_style', 'dark')
    color = context.user_data.get('map_color', '#FC4C02')
    out = "map.png"
    if gpx_utils.generate_map(f, out, style, color):
        with open(out, "rb") as photo:
            if style == 'transparent':
                await message.reply_document(photo, filename="transparent_map.png")
            else:
                await message.reply_photo(photo)
    else:
        await message.reply_text("❌ Error. No coordinates found or rendering error.")
    await cleanup(context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError):
        print("⚠️ Network problem.")
    else:
        print(f"❌ Unexpected error: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot started! (Stand-alone mode)")
    app.run_polling()

if __name__ == "__main__":
    main()