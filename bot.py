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
        self.wfile.write(b"Il bot e' online su Render!")

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
            InlineKeyboardButton("🔗 Unisci GPX/HR", callback_data='action_merge_hr'),
            InlineKeyboardButton("✂️ Taglia File", callback_data='action_crop')
        ],
        [
            InlineKeyboardButton("⏱️ Fix Tempo", callback_data='action_fix_time'),
            InlineKeyboardButton("🔗 Unisci Tracce", callback_data='action_merge_seq')
        ],
        [
            InlineKeyboardButton("⛰️ Fix Altitudine", callback_data='action_fix_elev'),
            InlineKeyboardButton("🗺️ Genera Mappa", callback_data='action_map')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg = (
        "🇮🇹 Ciao! Sono pronto. 🏃‍♂️ Scegli una funzione dal menu:\n"
        "💡 Usa /stop in caso di errori.\n\n"
        "🇬🇧 Hello! I'm ready. 🏃‍♂️ Choose a function from the menu:\n"
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
    await update.message.reply_text("🇮🇹 🛑 Memoria svuotata!\n🇬🇧 🛑 Memory cleared!")

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
        
        back_keyboard = [[InlineKeyboardButton("🔙 Indietro / Back", callback_data='back_to_start')]]
        reply_markup = InlineKeyboardMarkup(back_keyboard)
        
        if data == 'action_merge_hr':
            msg = "🇮🇹 🔗 **Unisci GPX e Cardio**\nInvia per primo il file della traccia GPS (es. da orologio o app).\n\n🇬🇧 🔗 **Merge GPX and HR**\nSend the GPS track file first."
        elif data == 'action_crop':
            msg = "🇮🇹 ✂️ **Taglia GPX**\nInvia il file GPX da tagliare.\n\n🇬🇧 Send the GPX file to crop."
        elif data == 'action_fix_time':
            msg = "🇮🇹 ⏱️ **Fix Tempo/Ritmo**\nInvia il file GPX a cui correggere il tempo.\n\n🇬🇧 Send the GPX file to fix time."
        elif data == 'action_merge_seq':
            msg = "🇮🇹 🔗 **Unisci Tracce (Sequenziale)**\nInvia i file GPX in ordine cronologico. Al termine premi 'Fatto'.\n\n🇬🇧 Send GPX files in order to merge."
        elif data == 'action_fix_elev':
            msg = "🇮🇹 ⛰️ **Fix Altitudine**\nInvia il file GPX di cui ricalcolare l'altitudine.\n\n🇬🇧 Send the GPX file to fix elevation."
        elif data == 'action_map':
            msg = "🇮🇹 🗺️ **Genera Mappa**\nInvia il file GPX di cui generare la mappa.\n\n🇬🇧 Send the GPX file to generate map."
            
        await query.edit_message_text(msg, reply_markup=reply_markup, parse_mode='Markdown')
        
    elif data == 'execute_merge_seq':
        await process_merge_seq(update.callback_query.message, context)
        
    elif data.startswith('mapstyle_'):
        style = data.split('_')[1]
        context.user_data['map_style'] = style
        keyboard = [
            [
                InlineKeyboardButton("🟠 Arancione", callback_data='mapcolor_#FC4C02'),
                InlineKeyboardButton("🔴 Rosso", callback_data='mapcolor_#FF0000')
            ],
            [
                InlineKeyboardButton("🔵 Blu", callback_data='mapcolor_#0000FF'),
                InlineKeyboardButton("🟢 Verde", callback_data='mapcolor_#00FF00')
            ],
            [
                InlineKeyboardButton("⚫ Nero", callback_data='mapcolor_#000000'),
                InlineKeyboardButton("⚪ Bianco", callback_data='mapcolor_#FFFFFF')
            ]
        ]
        await query.edit_message_text("🎨 Scegli il colore della traccia:", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data.startswith('mapcolor_'):
        color = data.split('_')[1]
        context.user_data['map_color'] = color
        await process_map(update.callback_query.message, context)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')
    if not action:
        await update.message.reply_text("🇮🇹 ⚠️ Seleziona prima un'azione dal comando /start.\n🇬🇧 ⚠️ Select an action from /start first.")
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
            await update.message.reply_text(f"✅ Ricevuto GPS: {file_name}\nOra inviami il file con i battiti cardiaci (HR).")
        elif len(files) == 2:
            await update.message.reply_text("✅ Ricevuti entrambi! Ora scrivimi la distanza totale in km (es: 10.5).")
            
    elif action == 'action_crop':
        if len(files) == 1:
            await update.message.reply_text("✅ Ricevuto! Scrivimi i km da tagliare all'inizio e alla fine separati da spazio.\nEs: `1.5 0.5` per tagliare 1.5km inizio e 0.5km fine.\nEs: `0 2.0` per togliere 2km alla fine.", parse_mode='Markdown')
            
    elif action == 'action_fix_time':
        if len(files) == 1:
            await update.message.reply_text("✅ Ricevuto! Scrivimi i minuti totali che deve durare l'attività.\nEs: `45.5` per 45 minuti e 30 secondi.", parse_mode='Markdown')
            
    elif action == 'action_merge_seq':
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Fatto (Unisci Tracce)", callback_data='execute_merge_seq')]])
        await update.message.reply_text(f"✅ Ricevuto file {len(files)}: {file_name}. Invia il prossimo oppure premi Fatto.", reply_markup=markup)
        
    elif action == 'action_fix_elev':
        if len(files) == 1:
            await process_fix_elev(update.message, context)
            
    elif action == 'action_map':
        if len(files) == 1:
            keyboard = [
                [
                    InlineKeyboardButton("🌑 Scura", callback_data='mapstyle_dark'),
                    InlineKeyboardButton("☀️ Chiara", callback_data='mapstyle_light')
                ],
                [
                    InlineKeyboardButton("⛰️ Topografica", callback_data='mapstyle_topo'),
                    InlineKeyboardButton("🛰️ Satellite", callback_data='mapstyle_satellite')
                ],
                [
                    InlineKeyboardButton("🔲 Trasparente (PNG)", callback_data='mapstyle_transparent')
                ]
            ]
            await update.message.reply_text("✅ File ricevuto! Scegli lo stile della mappa:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = context.user_data.get('action')
    files = context.user_data.get('files', [])
    
    if not action or not files:
        await update.message.reply_text("🇮🇹 ⚠️ Seleziona un'azione e inviami il file prima.\n🇬🇧 ⚠️ Select an action and send a file first.")
        return
        
    text = update.message.text.replace(',', '.')
    
    if action == 'action_merge_hr':
        if len(files) < 2: return
        try:
            dist_km = float(text)
            await process_merge_hr(update.message, context, dist_km)
        except ValueError:
            await update.message.reply_text("⚠️ Numero non valido.")
            
    elif action == 'action_crop':
        try:
            parts = text.split()
            start_km = float(parts[0])
            end_km = float(parts[1]) if len(parts) > 1 else 0.0
            await process_crop(update.message, context, start_km, end_km)
        except ValueError:
            await update.message.reply_text("⚠️ Formato non valido. Esempio: `1.5 0.5`", parse_mode='Markdown')
            
    elif action == 'action_fix_time':
        try:
            mins = float(text)
            await process_fix_time(update.message, context, mins)
        except ValueError:
            await update.message.reply_text("⚠️ Numero non valido. Esempio: `45.5`", parse_mode='Markdown')

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
    await message.reply_text("⚙️ Elaborazione in corso...")
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
            await message.reply_document(doc, filename="Attivita_Unita.tcx")
    except Exception as e:
        await message.reply_text(f"❌ Errore elaborazione: {e}")
    finally:
        if os.path.exists("GPS.gpx"): os.remove("GPS.gpx")
        if os.path.exists("HR.gpx"): os.remove("HR.gpx")
        await cleanup(context)

async def process_crop(message, context, start_km, end_km):
    await message.reply_text("⚙️ Taglio in corso...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.crop_gpx(f, start_km, end_km, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Tagliato.gpx")
    else:
        await message.reply_text("❌ Errore durante il taglio. Assicurati che i km siano validi.")
    await cleanup(context)

async def process_fix_time(message, context, target_mins):
    await message.reply_text("⚙️ Ricalcolo timestamp in corso...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.fix_time(f, target_mins, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Tempo_Ricalcolato.gpx")
    else:
        await message.reply_text("❌ Errore durante il ricalcolo.")
    await cleanup(context)

async def process_merge_seq(message, context):
    await message.reply_text("⚙️ Saldatura tracce in corso...")
    files = context.user_data['files']
    out = "output.gpx"
    if gpx_utils.merge_sequential(files, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Traccia_Saldata.gpx")
    else:
        await message.reply_text("❌ Errore durante la saldatura.")
    await cleanup(context)

async def process_fix_elev(message, context):
    await message.reply_text("⚙️ Scaricamento quote topografiche in corso (potrebbe volerci un minuto)...")
    f = context.user_data['files'][0]
    out = "output.gpx"
    if gpx_utils.fix_elevation(f, out):
        with open(out, "rb") as doc:
            await message.reply_document(doc, filename="Altitudine_Ricalcolata.gpx")
    else:
        await message.reply_text("❌ Errore durante il ricalcolo altitudine.")
    await cleanup(context)

async def process_map(message, context):
    await message.reply_text("🎨 Generazione mappa in corso...")
    f = context.user_data['files'][0]
    style = context.user_data.get('map_style', 'dark')
    color = context.user_data.get('map_color', '#FC4C02')
    out = "map.png"
    if gpx_utils.generate_map(f, out, style, color):
        with open(out, "rb") as photo:
            if style == 'transparent':
                await message.reply_document(photo, filename="mappa_trasparente.png")
            else:
                await message.reply_photo(photo)
    else:
        await message.reply_text("❌ Errore. Nessuna coordinata trovata o errore di rendering.")
    await cleanup(context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, NetworkError):
        print("⚠️ Problema di rete.")
    else:
        print(f"❌ Errore imprevisto: {context.error}")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot avviato! (Stand-alone mode)")
    app.run_polling()

if __name__ == "__main__":
    main()