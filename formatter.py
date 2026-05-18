"""
formatter.py — Mensajes de señales de OPCIONES BINARIAS para Telegram.

Incluye:
  - Señal de entrada (CALL/PUT, hora, vencimiento)
  - Resultado automático al vencimiento (GANADA/PERDIDA)
  - Estado con estadísticas de win rate
"""

from datetime import datetime, timedelta, timezone


def _e(text: str) -> str:
    """Escapa caracteres especiales para MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


# ─────────────────────────────────────────────
# Señal de entrada
# ─────────────────────────────────────────────

def format_binary_signal(signal: dict, expiry_minutes: int = 1) -> str:
    """
    Formatea la señal de opción binaria.
    Se envía 10 segundos antes del inicio del minuto de operación.
    """
    direction = signal["direction"]
    symbol    = signal["symbol"]

    is_call    = direction == "CALL"
    emoji_main = "🟢" if is_call else "🔴"
    emoji_dir  = "📈" if is_call else "📉"
    dir_text   = "CALL  ▲  SUBIDA" if is_call else "PUT  ▼  BAJADA"

    # Hora de entrada = próximo minuto completo
    now_utc     = datetime.now(timezone.utc)
    entry_time  = (now_utc + timedelta(minutes=1)).replace(second=0, microsecond=0)
    expiry_time = entry_time + timedelta(minutes=expiry_minutes)

    entry_str  = entry_time.strftime("%H:%M")
    expiry_str = expiry_time.strftime("%H:%M")
    date_str   = now_utc.strftime("%d/%m/%Y")

    score = signal.get("score", 0)
    stars = "⭐" * min(score, 5)

    if score >= 5:
        strength = "MUY FUERTE"
    elif score >= 4:
        strength = "FUERTE"
    else:
        strength = "MODERADA"

    forced_note = "\n🔄 _\\(Mejor par disponible del ciclo\\)_" if signal.get("forced") else ""

    msg = (
        f"{emoji_main}{emoji_main} *SEÑAL OPCIONES BINARIAS* {emoji_main}{emoji_main}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 *Par:*            `{_e(symbol)}`\n"
        f"{emoji_dir} *Dirección:*    *{_e(dir_text)}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏰ *Entrar a las:*   `{_e(entry_str)} UTC`\n"
        f"⌛ *Vencimiento:*   `{_e(expiry_str)} UTC`  \\({_e(str(expiry_minutes))} min\\)\n"
        f"📅 *Fecha:*          `{_e(date_str)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💪 *Fuerza:* {stars}  \\({_e(strength)}\\)\n"
        f"📊 *RSI:* `{_e(str(signal['rsi']))}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━"
        f"{forced_note}\n"
        f"⚠️ _Solo educativo\\. No es asesoría financiera\\._"
    )
    return msg


# ─────────────────────────────────────────────
# Resultado de la operación
# ─────────────────────────────────────────────

def format_result(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    won: bool,
    wins: int,
    losses: int,
    win_rate: float,
) -> str:
    """
    Formatea el resultado de la operación al vencimiento.
    Se envía automáticamente cuando expira el tiempo de la señal.
    """
    is_call = direction == "CALL"

    if won:
        emoji_result = "✅"
        result_text  = "GANADA"
        emoji_move   = "📈" if is_call else "📉"
        move_desc    = "Subió como se esperaba" if is_call else "Bajó como se esperaba"
    else:
        emoji_result = "❌"
        result_text  = "PERDIDA"
        emoji_move   = "📉" if is_call else "📈"
        move_desc    = "No subió como se esperaba" if is_call else "No bajó como se esperaba"

    diff     = exit_price - entry_price
    diff_pct = (diff / entry_price) * 100 if entry_price > 0 else 0
    sign     = "+" if diff >= 0 else ""

    total = wins + losses
    bar_wins   = "🟩" * min(wins, 10)
    bar_losses = "🟥" * min(losses, 10)

    msg = (
        f"{emoji_result}{emoji_result} *RESULTADO DE OPERACIÓN* {emoji_result}{emoji_result}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💱 *Par:*       `{_e(symbol)}`\n"
        f"📊 *Dirección:* `{_e(direction)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 *Entrada:*  `{_e(str(round(entry_price, 6)))}`\n"
        f"🏁 *Salida:*   `{_e(str(round(exit_price, 6)))}`\n"
        f"{emoji_move} *Movimiento:* `{_e(sign + str(round(diff_pct, 4)))}%`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *Resultado: {_e(result_text)}*\n"
        f"_{_e(move_desc)}_\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *Estadísticas del bot:*\n"
        f"  ✅ Ganadas: `{_e(str(wins))}`  {bar_wins}\n"
        f"  ❌ Perdidas: `{_e(str(losses))}`  {bar_losses}\n"
        f"  🎯 Win Rate: `{_e(str(round(win_rate, 1)))}%` \\({_e(str(total))} ops\\)\n"
    )
    return msg


# ─────────────────────────────────────────────
# Otros mensajes
# ─────────────────────────────────────────────

def format_welcome() -> str:
    return (
        "👋 *¡Bienvenido al Bot de Señales de Binarias\\!*\n\n"
        "📊 *Estrategia:* Vdub Binary Options Sniper\n"
        "💱 *Pares:* 19 pares Forex analizados en cada ciclo\n"
        "🎯 *Por ciclo:* 1 señal \\(la más fiable por score\\)\n"
        "⏰ *Envío:* 10 seg antes del minuto de operación\n"
        "📊 *Resultado:* automático al vencimiento\n\n"
        "⚙️ *Comandos:*\n"
        "  /signal \\— Analizar ahora\n"
        "  /senal \\— Analizar ahora \\(alternativo\\)\n"
        "  /vencimiento1 \\— Vencimiento 1 minuto\n"
        "  /vencimiento2 \\— Vencimiento 2 minutos\n"
        "  /vencimiento5 \\— Vencimiento 5 minutos\n"
        "  /vencimiento15 \\— Vencimiento 15 minutos\n"
        "  /estado \\— Configuración y estadísticas\n"
        "  /pares \\— Ver los 19 pares Forex\n\n"
        "⚠️ _Solo educativo\\. No es asesoría financiera\\._"
    )


def format_status(expiry: int, timeframe: str, interval: int,
                  last_signal: str, wins: int, losses: int, win_rate: str) -> str:
    total = wins + losses
    return (
        f"🤖 *Estado del Bot de Binarias*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *Estado:* Activo\n"
        f"⌛ *Vencimiento:* `{_e(str(expiry))} minuto(s)`\n"
        f"⏱ *Timeframe:* `{_e(timeframe)}`\n"
        f"🔄 *Ciclo:* cada `{_e(str(interval))}` minutos\n"
        f"🎯 *Por ciclo:* 1 señal \\(la más fiable\\)\n"
        f"⏰ *Envío:* 10 seg antes del minuto\n"
        f"🕐 *Última señal:* `{_e(last_signal)}`\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 *Estadísticas:*\n"
        f"  ✅ Ganadas: `{_e(str(wins))}`\n"
        f"  ❌ Perdidas: `{_e(str(losses))}`\n"
        f"  🎯 Win Rate: `{_e(win_rate)}` \\({_e(str(total))} ops\\)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Cambia vencimiento con:\n"
        f"/vencimiento1 \\| /vencimiento2 \\| /vencimiento5 \\| /vencimiento15"
    )


def format_expiry_changed(expiry: int) -> str:
    return (
        f"✅ *Vencimiento actualizado a `{_e(str(expiry))}` minuto\\(s\\)*\n\n"
        f"Las próximas señales usarán este tiempo de vencimiento\\."
    )


def format_pairs(pairs: list) -> str:
    pairs_text = "\n".join([f"  {i+1}\\. `{_e(p)}`" for i, p in enumerate(pairs)])
    return (
        f"💱 *Pares Forex monitoreados \\({len(pairs)}\\):*\n\n"
        f"{pairs_text}\n\n"
        f"🎯 _Todos se analizan en cada ciclo de 5 minutos_\n"
        f"_Se envía solo la señal con mayor score_"
    )
