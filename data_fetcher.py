"""
ATHENA Trading - Data Fetcher
Récupère les bougies OHLC depuis Twelve Data pour une paire et un timeframe donnés.
"""

import time
import requests
from config import TWELVE_DATA_API_KEY

BASE_URL = "https://api.twelvedata.com/time_series"


def fetch_candles(pair: str, interval: str, outputsize: int = 150) -> list[dict]:
    """
    Récupère les bougies OHLC pour une paire Forex.

    pair: ex "EUR/USD"
    interval: ex "4h", "1day"
    outputsize: nombre de bougies à récupérer

    Retourne une liste de dicts triés du plus ancien au plus récent :
    [{"datetime": "...", "open": float, "high": float, "low": float, "close": float}, ...]
    """
    params = {
        "symbol": pair,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "order": "ASC",  # plus ancien -> plus récent
    }

    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error pour {pair}/{interval}: {data.get('message')}")

    values = data.get("values", [])
    candles = []
    for v in values:
        candles.append({
            "datetime": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
        })

    return candles


def fetch_all_pairs_data(pairs: list[str], htf_interval: str, exec_interval: str,
                          htf_lookback: int, exec_lookback: int) -> dict:
    """
    Récupère les données HTF (biais) et exécution pour toutes les paires suivies.
    Espace les appels pour respecter le quota du plan gratuit Twelve Data
    (8 requêtes/minute) : on attend ~8 secondes entre chaque paire.

    Retourne : {
        "EUR/USD": {"htf": [...], "exec": [...]},
        ...
    }
    """
    result = {}
    for idx, pair in enumerate(pairs):
        if idx > 0:
            time.sleep(8)  # espacement pour rester sous la limite de débit
        try:
            htf_candles = fetch_candles(pair, htf_interval, htf_lookback)
            exec_candles = fetch_candles(pair, exec_interval, exec_lookback)
            result[pair] = {"htf": htf_candles, "exec": exec_candles}
        except Exception as e:
            print(f"[fetch_all_pairs_data] Erreur sur {pair}: {e}")
            result[pair] = {"htf": [], "exec": []}

    return result
