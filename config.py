"""
ATHENA Trading - Configuration
Toutes les valeurs ajustables sont ici. Modifie ce fichier pour
changer les paires, seuils, ou paramètres sans toucher au reste du code.
"""

import os

# ── Clés API (à définir en variables d'environnement, jamais en dur dans le code) ──
TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

# ── Paires Forex suivies ──
PAIRS = ["EUR/USD", "GBP/USD", "USD/JPY"]

# ── Timeframes ──
HTF_TIMEFRAME = "1day"      # Biais directionnel (D1)
EXEC_TIMEFRAME = "4h"       # Timeframe d'exécution (H4)

# ── Paramètres ICT/SMC ──
OTE_FIB_LOW = 0.62          # Borne basse de la zone OTE
OTE_FIB_HIGH = 0.79         # Borne haute de la zone OTE

# Nombre de bougies à analyser pour détecter structure / PD arrays
LOOKBACK_CANDLES_HTF = 100
LOOKBACK_CANDLES_EXEC = 150

# Tolérance de chevauchement entre PD array et zone OTE (en % du range de l'impulsion)
ZONE_OVERLAP_TOLERANCE = 0.05

# ── Scoring GPT ──
GPT_MODEL = "gpt-4.1-mini"
SCORE_THRESHOLD = 70        # Seuil au-dessus duquel Pine Script affichera le setup (0-100)

# ── Polling ──
POLL_INTERVAL_SECONDS = 240  # Fréquence de recalcul (4 min, cohérent avec exécution H4)

# ── Fichier de publication (ce que Pine Script ira lire via le pont externe) ──
PUBLISH_FILE = "latest_signals.json"
