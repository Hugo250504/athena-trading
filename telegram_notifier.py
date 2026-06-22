"""
ATHENA Trading - Telegram Notifier
Envoie une notification Telegram pour chaque setup validé par le scoring GPT.
"""

import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

TELEGRAM_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def format_setup_message(setup: dict) -> str:
    """Formate un setup validé en message Telegram lisible."""
    direction = "🟢 ACHAT" if setup["htf_bias"] == "bullish" else "🔴 VENTE"
    pd_type = setup["pd_array_type"].replace("_", " ").upper()

    return (
        f"⚡ *ATHENA TRADING - Setup détecté*\n\n"
        f"*Paire :* {setup['pair']}\n"
        f"*Direction :* {direction}\n"
        f"*Score IA :* {setup['score']}/100\n\n"
        f"*PD Array :* {pd_type}\n"
        f"  Zone : {setup['pd_array_zone']['bottom']:.5f} - {setup['pd_array_zone']['top']:.5f}\n"
        f"*Zone OTE :* {setup['ote_zone']['bottom']:.5f} - {setup['ote_zone']['top']:.5f}\n"
        f"*Prix actuel :* {setup['current_price']:.5f}\n\n"
        f"*Verdict GPT :* {setup['verdict']}\n\n"
        f"_Biais HTF (D1) : {setup['htf_reason']}_"
    )


def send_telegram_alert(setup: dict) -> bool:
    """Envoie une alerte Telegram pour un setup validé. Retourne True si succès."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[telegram_notifier] Token ou chat ID manquant, alerte non envoyée.")
        return False

    message = format_setup_message(setup)
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        response = requests.post(TELEGRAM_URL, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"[telegram_notifier] Erreur envoi Telegram: {e}")
        return False


def send_all_alerts(validated_setups: list[dict]) -> None:
    """Envoie une alerte Telegram pour chaque setup validé."""
    for setup in validated_setups:
        send_telegram_alert(setup)
