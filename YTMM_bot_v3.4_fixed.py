#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===================== CONFIG =====================

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN manquant")

BASE_DIR = Path("./YTMM")
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

TELEGRAM_LIMIT_MB = 50
SUB_LANGS = "fr,en,es,it,pt,ru,zh,ja"

RESOLUTIONS = {
    "360p": "360",
    "480p": "480",
    "720p": "720",
    "1080p": "1080",
    "2K": "1440",
    "4K": "2160",
}

SESSIONS = {}
CANCEL_FLAGS = {}

# ===================== LOG =====================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("YTMM")

# ===================== UTILS =====================

def run(cmd: list[str], timeout=600):
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout
        )
        return p.returncode == 0, p.stdout + p.stderr
    except Exception as e:
        return False, str(e)

def validate_youtube_url(url: str) -> bool:
    return bool(re.match(
        r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/",
        url
    ))

def yt_info(url: str) -> Optional[dict]:
    ok, out = run(["yt-dlp", "--dump-json", "--no-playlist", url], timeout=60)
    if not ok:
        return None
    return json.loads(out)

def estimate_size_mb(info: dict, height: str) -> int:
    duration = info.get("duration", 0)
    bitrate = {
        "360": 1,
        "480": 2,
        "720": 4,
        "1080": 7,
        "1440": 12,
        "2160": 20,
    }.get(height, 5)
    return int(duration * bitrate / 8)

def build_cmd(url: str, height: str, out: Path):
    return [
        "yt-dlp",
        "-f",
        f"bestvideo[height<={height}][vcodec!=?vp9]+bestaudio/best",
        "--merge-output-format", "mp4",
        "--recode-video", "mp4",
        "--embed-subs",
        "--sub-langs", SUB_LANGS,
        "--embed-metadata",
        "--no-playlist",
        "-o", str(out / "%(title)s.%(ext)s"),
        url
    ]

def clean_files():
    now = time.time()
    for f in DOWNLOAD_DIR.glob("*"):
        if now - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)

# ===================== COMMANDS =====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎥 **YTMM Downloader v3.4**\n\n"
        "• Envoie un lien YouTube\n"
        "• Choisis la résolution\n"
        "• Sous-titres intégrés\n"
        "• MEGA si > 50 Mo\n\n"
        "🔗 Envoie le lien maintenant",
        parse_mode="Markdown"
    )

async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    user_id = update.effective_user.id

    if not validate_youtube_url(url):
        await update.message.reply_text("❌ Lien YouTube invalide")
        return

    msg = await update.message.reply_text("🔍 Analyse de la vidéo…")
    info = yt_info(url)

    if not info:
        await msg.edit_text("❌ Impossible d’analyser la vidéo")
        return

    SESSIONS[user_id] = {"url": url, "info": info}
    CANCEL_FLAGS[user_id] = False

    kb = [
        [InlineKeyboardButton(k, callback_data=f"res:{k}") for k in ("360p","480p","720p")],
        [InlineKeyboardButton(k, callback_data=f"res:{k}") for k in ("1080p","2K","4K")],
        [InlineKeyboardButton("❌ Annuler", callback_data="cancel")]
    ]

    await msg.edit_text(
        f"🎬 **{info.get('title','Vidéo')}**\n\n"
        "Choisis la résolution :",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

async def choose_res(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    user_id = q.from_user.id

    if q.data == "cancel":
        CANCEL_FLAGS[user_id] = True
        await q.edit_message_text("❌ Annulé")
        return

    res_key = q.data.split(":")[1]
    height = RESOLUTIONS[res_key]

    session = SESSIONS.get(user_id)
    size = estimate_size_mb(session["info"], height)
    session["height"] = height
    session["size"] = size

    await q.edit_message_text(
        f"📦 Taille estimée : **~{size} Mo**\n"
        f"📺 Résolution : **{res_key}**\n\n"
        "⬇️ Téléchargement en cours…",
        parse_mode="Markdown"
    )

    await download_video(q, context, user_id)

async def download_video(q, context, user_id):
    session = SESSIONS[user_id]
    url = session["url"]
    height = session["height"]

    clean_files()
    cmd = build_cmd(url, height, DOWNLOAD_DIR)
    ok, out = run(cmd, timeout=1800)

    if CANCEL_FLAGS.get(user_id):
        await q.edit_message_text("❌ Téléchargement annulé")
        return

    if not ok:
        await q.edit_message_text("❌ Erreur de téléchargement")
        return

    files = sorted(DOWNLOAD_DIR.glob("*.mp4"), key=lambda x: x.stat().st_mtime, reverse=True)
    video = files[0]
    size_mb = video.stat().st_size / (1024*1024)

    if size_mb <= TELEGRAM_LIMIT_MB:
        with open(video, "rb") as f:
            await context.bot.send_video(
                chat_id=q.message.chat_id,
                video=f,
                caption=f"✅ {video.stem}\n📦 {size_mb:.1f} Mo",
                supports_streaming=True
            )
        await q.edit_message_text("✅ Envoyé")
    else:
        await q.edit_message_text(
            f"📦 {size_mb:.1f} Mo\n"
            "⚠️ Trop lourd pour Telegram\n"
            "➡️ Utilise MEGA"
        )

    video.unlink(missing_ok=True)
    SESSIONS.pop(user_id, None)
    CANCEL_FLAGS.pop(user_id, None)

# ===================== MAIN =====================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.bot.set_my_commands([
        BotCommand("start", "Démarrer le bot"),
    ])

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    app.add_handler(CallbackQueryHandler(choose_res))

    print("🤖 YTMM BOT v3.4 FIXED lancé")
    app.run_polling()

if __name__ == "__main__":
    main()
