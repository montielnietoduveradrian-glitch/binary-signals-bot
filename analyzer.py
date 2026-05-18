"""
analyzer.py — Estrategia Vdub Binary Options Sniper para opciones binarias.

La señal se genera al CIERRE de la vela actual e indica la dirección
de la SIGUIENTE vela (la que el trader debe operar).

Indicadores:
  - TEMA (Triple EMA) vs DEMA (Double EMA) — señal principal
  - RSI (14) — filtro de sobrecompra/sobreventa
  - Bandas de Bollinger (20) — filtro de volatilidad
  - Volumen relativo — confirmación de fuerza

Modo forzado:
  Si no hay cruce nuevo, se selecciona el par con mayor score
  acumulado para garantizar al menos 1 señal por ciclo.
"""

import pandas as pd
import numpy as np
import ta


# ─────────────────────────────────────────────
# Funciones EMA
# ─────────────────────────────────────────────

def _ema(s: pd.Series, p: int) -> pd.Series:
    return s.ewm(span=p, adjust=False).mean()

def calc_tema(s: pd.Series) -> pd.Series:
    e1 = _ema(s, 1); e2 = _ema(e1, 1); e3 = _ema(e2, 1)
    return e1 - e2 + e3

def calc_dema(s: pd.Series) -> pd.Series:
    e1 = _ema(s, 8); e2 = _ema(e1, 5)
    return 2 * e1 - e2

def calc_signal_line(high, low, close):
    avg_lc = (low + close) / 2
    avg_hc = (high + close) / 2
    vh1 = _ema(avg_lc.rolling(5).max(), 5)
    vl1 = _ema(avg_hc.rolling(8).min(), 8)
    tema = calc_tema(close)
    dema = calc_dema(close)
    sig = pd.Series(index=close.index, dtype=float)
    up = tema > dema
    sig[up]  = pd.concat([vh1[up],  vl1[up]],  axis=1).max(axis=1)
    sig[~up] = pd.concat([vh1[~up], vl1[~up]], axis=1).min(axis=1)
    return sig


# ─────────────────────────────────────────────
# Análisis completo
# ─────────────────────────────────────────────

def analyze(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["tema"] = calc_tema(df["close"])
    df["dema"] = calc_dema(df["close"])
    df["vdub"] = calc_signal_line(df["high"], df["low"], df["close"])

    sig_d1 = df["vdub"] - df["vdub"].shift(1)
    sig_d2 = df["vdub"].shift(1) - df["vdub"].shift(2)

    df["is_call"] = (
        (df["tema"] > df["dema"]) &
        (df["vdub"] > df["low"]) &
        (sig_d1 > sig_d2)
    )
    df["is_put"] = (
        (df["tema"] < df["dema"]) &
        (df["vdub"] < df["high"]) &
        (sig_d2 > sig_d1)
    )

    df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()

    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_mid"]   = bb.bollinger_mavg()

    df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean()

    return df


def _score_row(row, direction: str) -> tuple[int, list]:
    """Calcula score y razones para una fila y dirección dada."""
    score   = 3
    reasons = ["Cruce TEMA/DEMA confirmado (Vdub Sniper)"]

    rsi = float(row["rsi"]) if not np.isnan(row["rsi"]) else 50.0
    vol = float(row["vol_ratio"]) if not np.isnan(row["vol_ratio"]) else 1.0

    if direction == "CALL":
        if rsi < 65:
            score += 1
            reasons.append(f"RSI favorable ({rsi:.1f})")
        if float(row["close"]) <= float(row["bb_mid"]):
            score += 1
            reasons.append("Precio bajo media Bollinger")
    else:
        if rsi > 35:
            score += 1
            reasons.append(f"RSI favorable ({rsi:.1f})")
        if float(row["close"]) >= float(row["bb_mid"]):
            score += 1
            reasons.append("Precio sobre media Bollinger")

    if vol > 1.2:
        score += 1
        reasons.append(f"Volumen elevado ({vol:.1f}x)")

    return score, reasons


def get_signal(df: pd.DataFrame, symbol: str, forced: bool = False) -> dict | None:
    """
    Analiza las últimas velas y genera señal de opción binaria.

    Args:
        df:     DataFrame OHLCV
        symbol: Nombre del par (para mostrar)
        forced: Si True, genera señal aunque no haya cruce nuevo,
                eligiendo la dirección más fuerte según indicadores.

    Returns:
        dict con la señal o None si no hay señal (solo cuando forced=False).
    """
    df = analyze(df)
    df.dropna(inplace=True)

    if len(df) < 5:
        return None

    last = df.iloc[-1]

    # ── Buscar cruce nuevo en las últimas 4 velas ──
    direction = None
    ref_row   = None

    for i in range(-1, -5, -1):
        try:
            cur  = df.iloc[i]
            prev = df.iloc[i - 1]
            if bool(cur["is_call"]) and not bool(prev["is_call"]):
                direction = "CALL"
                ref_row   = cur
                break
            if bool(cur["is_put"]) and not bool(prev["is_put"]):
                direction = "PUT"
                ref_row   = cur
                break
        except Exception:
            pass

    # ── Modo forzado: elegir mejor dirección disponible ──
    if direction is None and forced:
        rsi = float(last["rsi"]) if not np.isnan(last["rsi"]) else 50.0
        tema_val = float(last["tema"])
        dema_val = float(last["dema"])

        # Dirección basada en posición TEMA vs DEMA + RSI
        if tema_val > dema_val and rsi < 60:
            direction = "CALL"
        elif tema_val < dema_val and rsi > 40:
            direction = "PUT"
        elif rsi <= 40:
            direction = "CALL"
        else:
            direction = "PUT"

        ref_row = last

    if direction is None or ref_row is None:
        return None

    score, reasons = _score_row(ref_row, direction)

    return {
        "symbol":    symbol,
        "direction": direction,
        "score":     score,
        "reasons":   reasons,
        "rsi":       round(float(ref_row["rsi"]) if not np.isnan(ref_row["rsi"]) else 50.0, 1),
        "price":     round(float(df.iloc[-1]["close"]), 6),
        "forced":    forced and (direction is not None),
    }


def score_all(df: pd.DataFrame) -> tuple[str, int]:
    """
    Evalúa la fuerza de CALL y PUT en el DataFrame actual.
    Retorna la dirección más fuerte y su score.
    Usado para elegir el mejor par en modo forzado.
    """
    df = analyze(df)
    df.dropna(inplace=True)
    if df.empty:
        return "CALL", 0

    last = df.iloc[-1]
    rsi  = float(last["rsi"]) if not np.isnan(last["rsi"]) else 50.0
    vol  = float(last["vol_ratio"]) if not np.isnan(last["vol_ratio"]) else 1.0
    tema = float(last["tema"])
    dema = float(last["dema"])

    call_score = 0
    put_score  = 0

    if tema > dema:
        call_score += 2
    else:
        put_score += 2

    if rsi < 50:
        call_score += 1
    else:
        put_score += 1

    if float(last["close"]) <= float(last["bb_mid"]):
        call_score += 1
    else:
        put_score += 1

    if vol > 1.2:
        call_score += 1
        put_score  += 1

    if call_score >= put_score:
        return "CALL", call_score
    return "PUT", put_score
