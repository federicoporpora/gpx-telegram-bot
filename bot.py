import os
import requests
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError
from gpx_hr_merger import process_activity, load_hr_data

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.ERROR)
logging.getLogger("telegram").setLevel(logging.ERROR)
logging.getLogger("httpcore").setLevel(logging.ERROR)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_TELEGRAM_ID = YOUR_TELEGRAM_ID
STRAVA_CLIENT_ID = YOUR_STRAVA_CLIENT_ID
STRAVA_CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")

def upload_to_strava(file_path: str) -> tuple[bool, str]:
    auth_url = "https://www.strava.com/api/v3/oauth/token"
    auth_data = {
        'client_id': STRAVA_CLIENT_ID,
        'client_secret': STRAVA_CLIENT_SECRET,
        'refresh_token': STRAVA_REFRESH_TOKEN,
        'grant_type': 'refresh_token'
    }
    res = requests.post(auth_url, data=auth_data)
    
    if res.status_code != 200:
        return False, f"🇮🇹 Errore autorizzazione: {res.text}\n🇬🇧 Authorization error: {res.text}"
        
    access_token = res.json().get('access_token')
    
    upload_url = "https://www.strava.com/api/v3/uploads"
    headers = {'Authorization': f'Bearer {access_token}'}
    data = {'data_type': 'tcx'}
    
    with open(file_path, 'rb') as f:
        files = {'file': (file_path, f, 'application/xml')}
        upload_res = requests.post(upload_url, headers=headers, data=data, files=files)
        
    if upload_res.status_code == 201:
        return True, "🇮🇹 Attività caricata con successo sul tuo account Strava!\n🇬🇧 Activity successfully uploaded to your Strava account!"
    else:
        return False, f"🇮🇹 Errore durante l'upload: {upload_res.text}\n🇬🇧 Upload error: {upload_res.text}"

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Gestisce gli errori in modo pulito senza intasare la console."""
    if isinstance(context.error, NetworkError):
        print("⚠️ Problema di rete (Proxy 503 di PythonAnywhere). Il bot sta riprovando in automatico...")
    else:
        print(f"❌ Errore imprevisto: {context.error}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['files'] = []
    await update.message.reply_text(
        "🇮🇹 Ciao! Sono pronto. 🏃‍♂️\n"
        "1️⃣ Inviami i due file GPX (in qualsiasi ordine e con qualsiasi nome).\n"
        "2️⃣ Scrivimi la distanza in km.\n"
        "💡 Usa /stop in caso di errori.\n\n"
        "🇬🇧 Hello! I'm ready. 🏃‍♂️\n"
        "1️⃣ Send me the two GPX files (in any order and with any name).\n"
        "2️⃣ Write me the distance in km.\n"
        "💡 Use /stop in case of errors."
    )

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'files' in context.user_data:
        for f in context.user_data['files']:
            if os.path.exists(f): os.remove(f)
    context.user_data['files'] = []
    await update.message.reply_text(
        "🇮🇹 🛑 Memoria svuotata! Quando vuoi, inviami di nuovo i file.\n\n"
        "🇬🇧 🛑 Memory cleared! Whenever you want, send me the files again."
    )

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await update.message.document.get_file()
    file_name = update.message.document.file_name
    
    if 'files' not in context.user_data: context.user_data['files'] = []
    if len(context.user_data['files']) >= 2:
        await update.message.reply_text("🇮🇹 ⚠️ Hai già inviato due file.\n🇬🇧 ⚠️ You have already sent two files.")
        return
    
    await file.download_to_drive(file_name)
    context.user_data['files'].append(file_name)
    
    if len(context.user_data['files']) == 1:
        await update.message.reply_text(f"🇮🇹 ✅ Ricevuto 1/2: {file_name}.\n🇬🇧 ✅ Received 1/2: {file_name}.")
    elif len(context.user_data['files']) == 2:
        await update.message.reply_text("🇮🇹 ✅ Ricevuti entrambi! Ora scrivimi la distanza.\n🇬🇧 ✅ Both received! Now write the distance.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if 'files' not in context.user_data or len(context.user_data['files']) < 2:
        await update.message.reply_text("🇮🇹 ⚠️ Inviami prima i file GPX!\n🇬🇧 ⚠️ Send the GPX files first!")
        return
        
    try:
        dist_km = float(update.message.text.replace(',', '.'))
    except ValueError:
        await update.message.reply_text("🇮🇹 ⚠️ Numero non valido.\n🇬🇧 ⚠️ Invalid number.")
        return

    await update.message.reply_text("🇮🇹 ⚙️ Elaborazione in corso...\n🇬🇧 ⚙️ Processing...")
    
    file1, file2 = context.user_data['files'][0], context.user_data['files'][1]
    
    if len(load_hr_data(file1)) > 0:
        file_hr, file_gps = file1, file2
    else:
        file_hr, file_gps = file2, file1
        
    success = process_activity(file_gps, file_hr, dist_km, "output_fixed.tcx")
    
    if success:
        user_id = update.message.from_user.id
        if user_id == MY_TELEGRAM_ID:
            await update.message.reply_text("🇮🇹 🚀 Ciao Boss! Carico su Strava...\n🇬🇧 🚀 Hello Boss! Uploading...")
            strava_ok, msg = upload_to_strava("output_fixed.tcx")
            
            if strava_ok:
                await update.message.reply_text(f"✅ {msg}")
            else:
                await update.message.reply_text(f"⚠️ {msg}")
                with open("output_fixed.tcx", "rb") as doc:
                    await update.message.reply_document(doc, filename="Attivita_Unita.tcx")
        else:
            with open("output_fixed.tcx", "rb") as doc:
                await update.message.reply_document(doc, filename="Attivita_Unita.tcx")
    else:
        await update.message.reply_text("🇮🇹 ❌ Errore elaborazione.\n🇬🇧 ❌ Processing error.")
        
    for f in [file1, file2, "output_fixed.tcx"]:
        if os.path.exists(f): os.remove(f)
    context.user_data['files'] = []

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Aggiunta del gestore degli errori
    app.add_error_handler(error_handler)
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("Bot avviato! Premi Ctrl+C per fermarlo. La console rimarrà pulita in caso di cali di rete.")
    app.run_polling()

if __name__ == "__main__":
    main()