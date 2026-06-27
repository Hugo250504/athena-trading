"""
ATHENA Trading — Daily Check (Asian Range Breakout)

Lance ce script chaque jour après 12:00 UTC pour voir l'état du setup du jour.

Paramètres validés par l'optimisation train/test :
  XAU/USD : H4 | RR 3.0 | Retest 4h (= 1 bougie H4)
  BTC/USD : H4 | RR 1.5 | Retest 4h (= 1 bougie H4)

Lecture du range asiatique : bougies H4 à 00:00 et 04:00 UTC
Cassure détectée          : clôture H4 08:00 UTC au-dessus/en-dessous du range
Retest                    : bougie H4 12:00 UTC touche le niveau ±0.1%

Usage : python3 daily_check.py
"""

import json
import os
import time
import datetime
import requests

# ── Paramètres validés ───────────────────────────────────────────────────────
CONFIGS = {
    "XAU/USD": {"rr": 3.0, "retest_candles": 1},
    "BTC/USD": {"rr": 1.5, "retest_candles": 1},
}

ASIAN_START_H  = 0     # 00:00 UTC
ASIAN_END_H    = 7     # 07:00 UTC inclus → bougies H4 à 00h et 04h
BREAKOUT_H     = 8     # première bougie de cassure potentielle : 08:00 UTC
RETEST_MARGIN  = 0.001 # ±0.1%

API_KEY    = os.environ.get("TWELVE_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
CACHE_DIR  = os.path.join(os.path.dirname(__file__), "cache")
CACHE_TTL  = 3600      # 1h — les données H4 ne changent pas plus souvent


# ── Données H4 ───────────────────────────────────────────────────────────────

def _cache_path(symbol):
    return os.path.join(CACHE_DIR, f"{symbol.replace('/', '_')}_h4_daily.json")


def fetch_h4(symbol, outputsize=30):
    """Récupère les dernières bougies H4, avec cache d'1h."""
    path = _cache_path(symbol)
    if os.path.exists(path):
        with open(path) as f:
            entry = json.load(f)
        if time.time() - entry["ts"] < CACHE_TTL:
            return entry["candles"]

    if not API_KEY:
        raise RuntimeError("TWELVE_DATA_API_KEY non défini.")

    r = requests.get("https://api.twelvedata.com/time_series", params={
        "symbol": symbol, "interval": "4h", "outputsize": outputsize,
        "apikey": API_KEY, "order": "ASC",
    }, timeout=15)
    r.raise_for_status()
    d = r.json()
    if d.get("status") == "error":
        raise RuntimeError(f"Twelve Data ({symbol}): {d['message']}")

    candles = [{"dt": v["datetime"], "o": float(v["open"]), "h": float(v["high"]),
                "l": float(v["low"]), "c": float(v["close"])}
               for v in d.get("values", [])]

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"ts": time.time(), "candles": candles}, f)

    return candles


# ── Helpers ───────────────────────────────────────────────────────────────────

def _date(dt): return dt[:10]
def _hour(dt): return int(dt[11:13])


def _fmt_price(symbol, price):
    """Formatte le prix selon l'actif."""
    if symbol == "BTC/USD":
        return f"${price:,.0f}"
    elif symbol == "XAU/USD":
        return f"${price:.2f}"
    return f"{price:.5f}"


# ── Analyse du jour ───────────────────────────────────────────────────────────

def analyze_today(symbol, candles, cfg):
    """
    Analyse les bougies H4 pour déterminer l'état du setup du jour.

    Retourne un dict décrivant l'état :
      status : "no_asian" | "no_breakout" | "breakout_pending" |
               "window_expired" | "setup_active" | "setup_closed"
    """
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    now_h = datetime.datetime.utcnow().hour

    # Bougies du jour courant
    today_candles = [c for c in candles if _date(c["dt"]) == today]

    # ── Range asiatique ──────────────────────────────────────────────────────
    asian = [c for c in today_candles if ASIAN_START_H <= _hour(c["dt"]) <= ASIAN_END_H]
    if len(asian) < 1:
        return {
            "status": "no_asian",
            "msg": f"Session asiatique non encore complète (heure UTC actuelle : {now_h:02d}h). "
                   f"Relancez après 09:00 UTC."
        }

    asian_high = max(c["h"] for c in asian)
    asian_low  = min(c["l"] for c in asian)
    asian_range = asian_high - asian_low

    # ── Bougies post-08h UTC ─────────────────────────────────────────────────
    post = [c for c in today_candles if _hour(c["dt"]) >= BREAKOUT_H]
    if not post:
        return {
            "status": "no_breakout",
            "msg": f"Range asiatique calculé. En attente de la bougie 08:00 UTC "
                   f"(heure UTC actuelle : {now_h:02d}h).",
            "asian_high": asian_high,
            "asian_low":  asian_low,
            "asian_range": asian_range,
        }

    # ── Détection de la cassure (1ère bougie 08h) ────────────────────────────
    breakout_candle = post[0]  # bougie 08:00 UTC
    if breakout_candle["c"] > asian_high:
        direction    = "bullish"
        broken_level = asian_high
        stop_loss    = asian_low
    elif breakout_candle["c"] < asian_low:
        direction    = "bearish"
        broken_level = asian_low
        stop_loss    = asian_high
    else:
        return {
            "status": "no_breakout",
            "msg": "Pas de cassure du range asiatique sur la bougie 08:00 UTC.",
            "asian_high": asian_high,
            "asian_low":  asian_low,
            "asian_range": asian_range,
        }

    risk        = abs(broken_level - stop_loss)
    take_profit = (broken_level + cfg["rr"] * risk
                   if direction == "bullish"
                   else broken_level - cfg["rr"] * risk)
    margin      = broken_level * RETEST_MARGIN

    # ── Bougies disponibles pour le retest (après la cassure) ────────────────
    retest_candidates = post[1: 1 + cfg["retest_candles"]]   # 1 bougie H4 = 4h

    # Retest trouvé ?
    retest_candle = None
    for c in retest_candidates:
        if direction == "bullish":
            if broken_level - margin <= c["l"] <= broken_level + margin:
                retest_candle = c; break
        else:
            if broken_level - margin <= c["h"] <= broken_level + margin:
                retest_candle = c; break

    # ── Fenêtre de retest expirée sans retest ? ──────────────────────────────
    if retest_candle is None:
        if len(retest_candidates) >= cfg["retest_candles"]:
            return {
                "status": "window_expired",
                "msg": "Cassure confirmée mais le retest ne s'est pas produit dans la fenêtre de 4h. Setup abandonné.",
                "direction":    direction,
                "broken_level": broken_level,
                "asian_high":   asian_high,
                "asian_low":    asian_low,
                "asian_range":  asian_range,
            }
        else:
            return {
                "status": "breakout_pending",
                "msg": f"Cassure {'haussière' if direction == 'bullish' else 'baissière'} confirmée. "
                       f"En attente du retest à {_fmt_price(symbol, broken_level)} ±0.1% "
                       f"(fenêtre active jusqu'à 12:00 UTC).",
                "direction":    direction,
                "broken_level": broken_level,
                "asian_high":   asian_high,
                "asian_low":    asian_low,
                "asian_range":  asian_range,
                "entry":        broken_level,
                "stop_loss":    stop_loss,
                "take_profit":  take_profit,
                "risk":         risk,
            }

    # ── Retest confirmé → setup entré ────────────────────────────────────────
    entry_price = broken_level

    # Le trade est-il encore ouvert ou déjà clôturé ?
    post_entry = [c for c in today_candles if c["dt"] > retest_candle["dt"]]
    # Inclut aussi les bougies des jours suivants si le trade déborde
    all_after = [c for c in candles if c["dt"] > retest_candle["dt"]]

    result  = None
    exit_dt = None
    for c in all_after:
        if direction == "bullish":
            if c["l"] <= stop_loss:
                result = "STOP LOSS touché"; exit_dt = c["dt"]; break
            if c["h"] >= take_profit:
                result = "TAKE PROFIT touché"; exit_dt = c["dt"]; break
        else:
            if c["h"] >= stop_loss:
                result = "STOP LOSS touché"; exit_dt = c["dt"]; break
            if c["l"] <= take_profit:
                result = "TAKE PROFIT touché"; exit_dt = c["dt"]; break

    if result:
        return {
            "status":       "setup_closed",
            "direction":    direction,
            "entry":        entry_price,
            "stop_loss":    stop_loss,
            "take_profit":  take_profit,
            "risk":         risk,
            "result":       result,
            "exit_dt":      exit_dt,
            "asian_high":   asian_high,
            "asian_low":    asian_low,
            "asian_range":  asian_range,
            "retest_dt":    retest_candle["dt"],
        }
    else:
        return {
            "status":       "setup_active",
            "direction":    direction,
            "entry":        entry_price,
            "stop_loss":    stop_loss,
            "take_profit":  take_profit,
            "risk":         risk,
            "asian_high":   asian_high,
            "asian_low":    asian_low,
            "asian_range":  asian_range,
            "retest_dt":    retest_candle["dt"],
        }


# ── Construction du message ───────────────────────────────────────────────────

def build_message(symbol, state, cfg):
    """Construit le texte du message pour un actif (au lieu de print direct)."""
    fmt  = lambda p: _fmt_price(symbol, p)
    name = f"{'XAU/USD (Or)' if symbol == 'XAU/USD' else 'BTC/USD (Bitcoin)'}"
    rr   = cfg["rr"]

    lines = []
    lines.append(f"\n{'─'*40}")
    lines.append(f"  {name}")
    lines.append(f"{'─'*40}")

    s = state["status"]

    if s == "no_asian":
        lines.append(f"⏳ {state['msg']}")

    elif s == "no_breakout" and "asian_high" in state:
        lines.append(f"📊 Range asiatique du jour :")
        lines.append(f"   High  : {fmt(state['asian_high'])}")
        lines.append(f"   Low   : {fmt(state['asian_low'])}")
        lines.append(f"   Taille: {fmt(state['asian_range'])}")
        lines.append(f"⏳ {state['msg']}")

    elif s == "no_breakout":
        lines.append(f"─ {state['msg']}")

    elif s == "window_expired":
        arr = "↑" if state["direction"] == "bullish" else "↓"
        lines.append(f"📊 Range asiatique : {fmt(state['asian_low'])} — {fmt(state['asian_high'])}")
        lines.append(f"{arr} Cassure {state['direction']} à {fmt(state['broken_level'])}")
        lines.append(f"✗ {state['msg']}")

    elif s == "breakout_pending":
        arr = "↑" if state["direction"] == "bullish" else "↓"
        lines.append(f"📊 Range asiatique : {fmt(state['asian_low'])} — {fmt(state['asian_high'])}")
        lines.append(f"{arr} Cassure {'HAUSSIÈRE' if state['direction'] == 'bullish' else 'BAISSIÈRE'} confirmée")
        lines.append(f"⏳ En attente du retest...")
        lines.append(f"")
        lines.append(f"Si le retest se produit, ordre à prendre :")
        lines.append(f"   Entrée : {fmt(state['entry'])}")
        lines.append(f"   Stop   : {fmt(state['stop_loss'])}")
        lines.append(f"   TP     : {fmt(state['take_profit'])} (RR 1:{rr})")
        lines.append(f"   Risque : {fmt(state['risk'])}")

    elif s == "setup_active":
        arr = "↑" if state["direction"] == "bullish" else "↓"
        lines.append(f"📊 Range asiatique : {fmt(state['asian_low'])} — {fmt(state['asian_high'])}")
        lines.append(f"{arr} Cassure {'HAUSSIÈRE' if state['direction'] == 'bullish' else 'BAISSIÈRE'}")
        lines.append(f"✓ SETUP ACTIF — retest confirmé à {state['retest_dt'][11:16]} UTC")
        lines.append(f"")
        lines.append(f"   Entrée : {fmt(state['entry'])}")
        lines.append(f"   Stop   : {fmt(state['stop_loss'])}")
        lines.append(f"   TP     : {fmt(state['take_profit'])} (RR 1:{rr})")
        lines.append(f"   Risque : {fmt(state['risk'])}")
        lines.append(f"")
        lines.append(f"⏳ Trade en cours — SL et TP pas encore touchés.")

    elif s == "setup_closed":
        arr   = "↑" if state["direction"] == "bullish" else "↓"
        emoji = "✓" if "TAKE PROFIT" in state["result"] else "✗"
        lines.append(f"📊 Range asiatique : {fmt(state['asian_low'])} — {fmt(state['asian_high'])}")
        lines.append(f"{arr} Cassure {'HAUSSIÈRE' if state['direction'] == 'bullish' else 'BAISSIÈRE'}")
        lines.append(f"✓ Setup entré à {state['retest_dt'][11:16]} UTC")
        lines.append(f"")
        lines.append(f"   Entrée : {fmt(state['entry'])}")
        lines.append(f"   Stop   : {fmt(state['stop_loss'])}")
        lines.append(f"   TP     : {fmt(state['take_profit'])} (RR 1:{rr})")
        lines.append(f"")
        lines.append(f"{emoji} {state['result']} à {state['exit_dt'][11:16]} UTC")

    return "\n".join(lines)


def log(msg):
    """Affiche sur stdout avec flush immédiat (utile pour les logs cron/Render)."""
    print(msg, flush=True)


def send_telegram(text):
    """Envoie un message Telegram. Retourne True si succès, False sinon (et log l'erreur)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️  TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID manquant — message non envoyé.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        log(f"✗ Erreur envoi Telegram : {e}")
        return False


# ── Point d'entrée ────────────────────────────────────────────────────────────

def main():
    now_utc = datetime.datetime.utcnow()
    header = (f"ATHENA — Daily Check\n"
              f"{now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    log(f"\n{'═'*56}\n  {header}\n{'═'*56}")

    full_message = [header]
    api_calls = 0

    for symbol, cfg in CONFIGS.items():
        try:
            candles = fetch_h4(symbol, outputsize=40)
            if not candles:
                msg = f"\n{symbol} : aucune donnée reçue."
                log(msg)
                full_message.append(msg)
                continue

            api_calls += 1
            if api_calls > 1:
                time.sleep(9)

            state = analyze_today(symbol, candles, cfg)
            msg = build_message(symbol, state, cfg)
            log(msg)
            full_message.append(msg)

        except Exception as e:
            msg = f"\n{symbol} : erreur — {e}"
            log(msg)
            full_message.append(msg)

    telegram_text = "\n".join(full_message)
    sent = send_telegram(telegram_text)
    log(f"\n{'═'*56}\n  Telegram : {'✓ envoyé' if sent else '✗ non envoyé (voir logs)'}\n{'═'*56}\n")


if __name__ == "__main__":
    main()
