"""
ATHENA Trading - Serveur principal
Orchestration : récupère les données -> détecte les setups ICT/SMC -> score via GPT
-> publie les résultats sur un endpoint que Pine Script lira via request.security()
ou un service de pont externe.

Lancer avec : uvicorn server:app --host 0.0.0.0 --port 8000
"""

import json
import time
import threading
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import (
    PAIRS, HTF_TIMEFRAME, EXEC_TIMEFRAME,
    LOOKBACK_CANDLES_HTF, LOOKBACK_CANDLES_EXEC,
    SCORE_THRESHOLD, POLL_INTERVAL_SECONDS, PUBLISH_FILE,
)
from data_fetcher import fetch_all_pairs_data
from ict_engine import find_candidate_setups
from gpt_scorer import score_all_setups
from telegram_notifier import send_all_alerts

app = FastAPI(title="ATHENA Trading Signal Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# État en mémoire, mis à jour par le thread de polling
latest_results = {
    "updated_at": None,
    "signals": [],
}
_lock = threading.Lock()

# Garde une trace des setups déjà notifiés sur Telegram pour éviter les doublons
# (clé = pair + pd_array_formed_at, qui identifie un setup unique)
_notified_setups = set()


def _setup_key(setup: dict) -> str:
    return f"{setup['pair']}|{setup['pd_array_formed_at']}|{setup['pd_array_type']}"


def run_analysis_cycle():
    """Un cycle complet : fetch -> détection -> scoring -> publication."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Démarrage cycle d'analyse...")

    market_data = fetch_all_pairs_data(
        PAIRS, HTF_TIMEFRAME, EXEC_TIMEFRAME,
        LOOKBACK_CANDLES_HTF, LOOKBACK_CANDLES_EXEC,
    )

    all_candidates = []
    for pair, data in market_data.items():
        if not data["htf"] or not data["exec"]:
            continue
        candidates = find_candidate_setups(pair, data["htf"], data["exec"])
        all_candidates.extend(candidates)

    print(f"  -> {len(all_candidates)} setup(s) candidat(s) détecté(s)")

    scored = score_all_setups(all_candidates) if all_candidates else []
    validated = [s for s in scored if s["score"] >= SCORE_THRESHOLD]

    print(f"  -> {len(validated)} setup(s) validé(s) (seuil {SCORE_THRESHOLD})")

    # On ne notifie que les setups jamais envoyés sur Telegram auparavant
    new_setups = [s for s in validated if _setup_key(s) not in _notified_setups]
    if new_setups:
        send_all_alerts(new_setups)
        for s in new_setups:
            _notified_setups.add(_setup_key(s))
        print(f"  -> {len(new_setups)} nouvelle(s) alerte(s) Telegram envoyée(s)")

    with _lock:
        latest_results["updated_at"] = datetime.now(timezone.utc).isoformat()
        latest_results["signals"] = validated

    # Publication sur fichier (utile pour debug local + certains ponts externes)
    with open(PUBLISH_FILE, "w", encoding="utf-8") as f:
        json.dump(latest_results, f, ensure_ascii=False, indent=2)


def polling_loop():
    """Boucle de fond qui relance l'analyse à intervalle régulier."""
    while True:
        try:
            run_analysis_cycle()
        except Exception as e:
            print(f"[polling_loop] Erreur: {e}")
        time.sleep(POLL_INTERVAL_SECONDS)


@app.on_event("startup")
def start_background_polling():
    thread = threading.Thread(target=polling_loop, daemon=True)
    thread.start()


@app.get("/")
def root():
    return {"service": "ATHENA Trading Signal Server", "status": "running"}


@app.get("/signals")
def get_signals():
    """Endpoint principal lu par Pine Script (via pont externe) ou pour debug."""
    with _lock:
        return latest_results


@app.get("/signals/{pair}")
def get_signals_for_pair(pair: str):
    """
    Endpoint filtré par paire, ex: /signals/EUR%2FUSD
    Pratique si Pine Script (via le pont) veut lire un seul score par paire.
    """
    with _lock:
        pair_signals = [s for s in latest_results["signals"] if s["pair"] == pair]
        return {"updated_at": latest_results["updated_at"], "signals": pair_signals}
