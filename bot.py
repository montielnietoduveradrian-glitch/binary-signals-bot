"""
bot.py — Bot de señales de OPCIONES BINARIAS para Telegram.

Características:
  - Analiza los 19 pares Forex completos en cada ciclo
  - Envía SOLO 1 señal por ciclo (la más fiable por score)
  - Garantiza mínimo 1 señal cada 5 minutos
  - Envía la señal 10 segundos ANTES del inicio del minuto
  - Al vencimiento, envía el RESULTADO automático (✅ GANADA / ❌ PERDIDA)
  - Vencimiento configurable: 1, 2, 5 o 15 minutos
  - Estrategia: Vdub Binary Options Sniper (TEMA/DEMA)
  - Compatible con Railway.app para ejecución 24/7

Uso local:
    python3 bot.py

Uso en Railway:
    Configurar variables de entorno en el panel de Railway.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

import ccxt
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from analyzer import get_signal, score_all
from formatter import (
    format_binary_signal,
    format_result,
    format_welcome,
    format_status,
    format_expiry_changed,
    format_pairs,
)

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger("BinaryBot")

# ─────────────────────────────────────────────
# Variables de entorno
# Funciona tanto con archivo .env (local) como
# con variables de Railway (producción 24/7)
# ─────────────────────────────────────────────
load_dotenv()  # Carga .env si existe (local), ignorado en Railway

BOT_TOKEN      = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID     = os.environ.get("TELEGRAM_CHANNEL_ID", "")
ADMIN_ID       = os.environ.get("ADMIN_CHAT_ID", "")
TIMEFRAME      = os.environ.get("TIMEFRAME", "1m")
DEFAULT_EXPIRY = int(os.environ.get("EXPIRY_MINUTES", "1"))

INTERVAL_MIN   = 5   # Ciclo cada 5 minutos

# ─────────────────────────────────────────────
# Estado global
# ─────────────────────────────────────────────
bot_state = {
    "expiry_minutes":   DEFAULT_EXPIRY,
    "last_signal_time": None,
    "wins":             0,
    "losses":           0,
}

# ─────────────────────────────────────────────
# Pares Forex (19 solicitados → mapeados a KuCoin)
# ─────────────────────────────────────────────
FOREX_PAIRS_DISPLAY = [
    "EUR/USD", "USD/JPY", "GBP/USD", "AUD/USD", "USD/CAD",
    "NZD/USD", "USD/CHF", "EUR/JPY", "GBP/JPY", "EUR/GBP",
    "EUR/CAD", "GBP/AUD", "AUD/CAD", "AUD/CHF", "CAD/CHF",
    "CHF/JPY", "EUR/AUD", "EUR/CHF", "CAD/JPY",
]

KUCOIN_PAIRS = [
    "BTC/USDT",   # EUR/USD
    "ETH/USDT",   # USD/JPY
    "BNB/USDT",   # GBP/USD
    "SOL/USDT",   # AUD/USD
    "XRP/USDT",   # USD/CAD
    "ADA/USDT",   # NZD/USD
    "DOGE/USDT",  # USD/CHF
    "AVAX/USDT",  # EUR/JPY
    "DOT/USDT",   # GBP/JPY
    "LINK/USDT",  # EUR/GBP
    "LTC/USDT",   # EUR/CAD
    "BCH/USDT",   # GBP/AUD
    "ATOM/USDT",  # AUD/CAD
    "UNI/USDT",   # AUD/CHF
    "POL/USDT",   # CAD/CHF
    "NEAR/USDT",  # CHF/JPY
    "FIL/USDT",   # EUR/AUD
    "ALGO/USDT",  # EUR/CHF
    "VET/USDT",   # CAD/JPY
]

PAIR_MAP    = {kc: fx for kc, fx in zip(KUCOIN_PAIRS, FOREX_PAIRS_DISPLAY)}
REVERSE_MAP = {fx: kc for kc, fx in PAIR_MAP.items()}


# ─────────────────────────────────────────────
# Exchange
# ─────────────────────────────────────────────
def get_exchange():
    return ccxt.kucoin({"enableRateLimit": True, "timeout": 30000})

def fetch_ohlcv(exchange, symbol, timeframe="1m", limit=200):
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["timestamp","open","high","low","close","volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df.set_index("timestamp", inplace=True)
        return df.astype(float)
    except Exception as e:
        logger.warning(f"Error fetch {symbol}: {e}")
        return None

def fetch_current_price(exchange, kucoin_symbol: str) -> float | None:
    try:
        ticker = exchange.fetch_ticker(kucoin_symbol)
        return float(ticker["last"])
    except Exception as e:
        logger.warning(f"Error precio {kucoin_symbol}: {e}")
        return None


# ─────────────────────────────────────────────
# Timing: esperar hasta 10 seg antes del minuto
# ─────────────────────────────────────────────
async def wait_until_10s_before_minute():
    now       = datetime.now(timezone.utc)
    seconds   = now.second + now.microsecond / 1_000_000
    wait_secs = (60 - seconds) - 10
    if wait_secs < 0:
        wait_secs += 60
    if wait_secs > 0.1:
        logger.info(f"Esperando {wait_secs:.1f}s → envío 10s antes del minuto")
        await asyncio.sleep(wait_secs)


# ─────────────────────────────────────────────
# Resultado automático al vencimiento
# ─────────────────────────────────────────────
async def check_and_send_result(
    app: Application,
    chat_id: str,
    kucoin_symbol: str,
    display_name: str,
    direction: str,
    entry_price: float,
    expiry_minutes: int,
) -> None:
    await asyncio.sleep(expiry_minutes * 60)

    exchange   = get_exchange()
    exit_price = fetch_current_price(exchange, kucoin_symbol)

    if exit_price is None:
        logger.warning(f"No se pudo obtener precio de cierre para {kucoin_symbol}")
        return

    if direction == "CALL":
        won = exit_price > entry_price
    else:
        won = exit_price < entry_price

    if won:
        bot_state["wins"] += 1
    else:
        bot_state["losses"] += 1

    total    = bot_state["wins"] + bot_state["losses"]
    win_rate = (bot_state["wins"] / total * 100) if total > 0 else 0

    logger.info(
        f"RESULTADO: {display_name} | {direction} | "
        f"Entrada: {entry_price} | Salida: {exit_price} | "
        f"{'✅ GANADA' if won else '❌ PERDIDA'}"
    )

    msg = format_result(
        symbol=display_name,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        won=won,
        wins=bot_state["wins"],
        losses=bot_state["losses"],
        win_rate=win_rate,
    )

    try:
        await app.bot.send_message(chat_id=chat_id, text=msg, parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Error enviando resultado: {e}")


# ═══════════════════════════════════════════════
# FUNCIÓN PRINCIPAL DE ANÁLISIS
# ═══════════════════════════════════════════════
async def run_analysis(app: Application, chat_id: str | None = None) -> None:
    target = chat_id or CHANNEL_ID
    expiry = bot_state["expiry_minutes"]

    if not target:
        return

    logger.info(f"Analizando {len(KUCOIN_PAIRS)} pares | Venc: {expiry}m")

    exchange      = get_exchange()
    best_signal   = None
    best_score    = -1
    best_kucoin   = None
    fallback_list = []

    for kucoin_sym in KUCOIN_PAIRS:
        display = PAIR_MAP.get(kucoin_sym, kucoin_sym)
        try:
            df = fetch_ohlcv(exchange, kucoin_sym, TIMEFRAME, 200)
            if df is None or df.empty:
                continue
            sig = get_signal(df, display, forced=False)
            if sig and sig["score"] > best_score:
                best_signal = sig
                best_score  = sig["score"]
                best_kucoin = kucoin_sym
            elif not sig:
                direction, sc = score_all(df)
                fallback_list.append((sc, display, kucoin_sym, df))
        except Exception as e:
            logger.error(f"Error {kucoin_sym}: {e}")

    if best_signal is None and fallback_list:
        fallback_list.sort(key=lambda x: x[0], reverse=True)
        sc, display, kucoin_sym, df = fallback_list[0]
        forced_sig = get_signal(df, display, forced=True)
        if forced_sig:
            best_signal = forced_sig
            best_kucoin = kucoin_sym

    if best_signal is None:
        logger.info("Sin señal disponible en este ciclo.")
        return

    logger.info(f"Mejor señal: {best_signal['symbol']} | {best_signal['direction']} | Score: {best_signal['score']}")

    await wait_until_10s_before_minute()

    entry_price = fetch_current_price(exchange, best_kucoin) or best_signal["price"]

    try:
        msg = format_binary_signal(best_signal, expiry_minutes=expiry)
        await app.bot.send_message(chat_id=target, text=msg, parse_mode="MarkdownV2")
        bot_state["last_signal_time"] = datetime.now(timezone.utc)
        logger.info(f"Señal enviada: {best_signal['symbol']} | {best_signal['direction']} | Entrada: {entry_price}")
    except Exception as e:
        logger.error(f"Error enviando señal: {e}")
        return

    asyncio.create_task(
        check_and_send_result(
            app=app,
            chat_id=target,
            kucoin_symbol=best_kucoin,
            display_name=best_signal["symbol"],
            direction=best_signal["direction"],
            entry_price=entry_price,
            expiry_minutes=expiry,
        )
    )


# ═══════════════════════════════════════════════
# HANDLERS DE COMANDOS
# ═══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_welcome(), parse_mode="MarkdownV2")

async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    await update.message.reply_text("🔄 *Analizando los 19 pares Forex\\.\\.\\.*", parse_mode="MarkdownV2")
    await run_analysis(context.application, chat_id=chat_id)

async def cmd_estado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last     = bot_state["last_signal_time"]
    last_str = last.strftime("%H:%M UTC") if last else "Nunca"
    total    = bot_state["wins"] + bot_state["losses"]
    wr       = f"{bot_state['wins'] / total * 100:.1f}%" if total > 0 else "N/A"
    await update.message.reply_text(
        format_status(
            expiry=bot_state["expiry_minutes"],
            timeframe=TIMEFRAME,
            interval=INTERVAL_MIN,
            last_signal=last_str,
            wins=bot_state["wins"],
            losses=bot_state["losses"],
            win_rate=wr,
        ),
        parse_mode="MarkdownV2",
    )

async def cmd_pares(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(format_pairs(FOREX_PAIRS_DISPLAY), parse_mode="MarkdownV2")

async def set_expiry(update, context, minutes: int):
    bot_state["expiry_minutes"] = minutes
    await update.message.reply_text(format_expiry_changed(minutes), parse_mode="MarkdownV2")
    logger.info(f"Vencimiento → {minutes} minuto(s)")

async def cmd_v1(u, c):  await set_expiry(u, c, 1)
async def cmd_v2(u, c):  await set_expiry(u, c, 2)
async def cmd_v5(u, c):  await set_expiry(u, c, 5)
async def cmd_v15(u, c): await set_expiry(u, c, 15)


# ═══════════════════════════════════════════════
# SCHEDULER — cada 5 minutos exactos
# ═══════════════════════════════════════════════
async def scheduled_job(app: Application):
    now = datetime.now(timezone.utc)
    logger.info(f"[AUTO] {now.strftime('%H:%M:%S UTC')}")
    await run_analysis(app)


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════
def main():
    if not BOT_TOKEN:
        logger.critical("❌ No se encontró TELEGRAM_BOT_TOKEN")
        logger.critical("   Local: crea el archivo .env con TELEGRAM_BOT_TOKEN=tu_token")
        logger.critical("   Railway: agrega la variable en el panel de Variables")
        return

    logger.info("=" * 55)
    logger.info("  BOT DE SEÑALES — OPCIONES BINARIAS  (24/7)")
    logger.info("  Estrategia: Vdub Binary Options Sniper")
    logger.info(f"  Pares: {len(KUCOIN_PAIRS)} | Ciclo: cada {INTERVAL_MIN} min")
    logger.info(f"  1 señal por ciclo | Resultado automático")
    logger.info("=" * 55)

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start",         cmd_start))
    app.add_handler(CommandHandler("señal",         cmd_signal))
    app.add_handler(CommandHandler("senal",         cmd_signal))
    app.add_handler(CommandHandler("estado",        cmd_estado))
    app.add_handler(CommandHandler("pares",         cmd_pares))
    app.add_handler(CommandHandler("vencimiento1",  cmd_v1))
    app.add_handler(CommandHandler("vencimiento2",  cmd_v2))
    app.add_handler(CommandHandler("vencimiento5",  cmd_v5))
    app.add_handler(CommandHandler("vencimiento15", cmd_v15))

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        scheduled_job,
        trigger="cron",
        minute="0,5,10,15,20,25,30,35,40,45,50,55",
        args=[app],
        id="binary_5min",
        misfire_grace_time=30,
    )

    async def post_init(application: Application):
        scheduler.start()
        logger.info("Scheduler activo: análisis en :00, :05, :10... cada hora")
        if ADMIN_ID:
            try:
                await application.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=(
                        "🚀 *Bot de Binarias iniciado \\(24/7\\)*\n\n"
                        f"📊 *Pares:* `{len(KUCOIN_PAIRS)}` pares Forex\n"
                        f"⌛ *Vencimiento:* `{DEFAULT_EXPIRY}` min\n"
                        f"🔄 *Ciclo:* cada `{INTERVAL_MIN}` minutos\n"
                        f"🎯 *Por ciclo:* 1 señal \\(la más fiable\\)\n"
                        f"📊 *Resultado:* automático al vencimiento\n"
                        f"⏰ *Envío:* 10 seg antes del minuto\n\n"
                        "Comandos:\n"
                        "/vencimiento1 \\| /vencimiento2 \\| /vencimiento5 \\| /vencimiento15"
                    ),
                    parse_mode="MarkdownV2",
                )
            except Exception as e:
                logger.warning(f"No se pudo notificar admin: {e}")

    app.post_init = post_init

    logger.info("Bot en ejecución 24/7. Presiona Ctrl+C para detener.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
