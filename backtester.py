"""
ATHENA Trading - Backtester
Rejoue la logique de détection (ict_engine) sur un historique de bougies,
simule chaque trade avec SL/TP selon les conventions ICT, et calcule
les statistiques réelles : winrate, RR moyen, profit factor.

Usage : python3 backtester.py
"""

import json
from data_fetcher import fetch_candles
from ict_engine import (
    determine_bias, get_virgin_pd_arrays, calculate_ote_zone,
    zones_overlap, find_swing_points,
)
from config import PAIRS, ZONE_OVERLAP_TOLERANCE


def find_next_opposite_swing(candles: list[dict], from_index: int, direction: str) -> dict | None:
    """
    Trouve le prochain swing dans le sens du trade après from_index, pour servir de Take Profit.
    direction 'bullish' -> on cherche le prochain swing high après from_index
    direction 'bearish' -> on cherche le prochain swing low après from_index
    """
    swings = find_swing_points(candles)
    target_type = "high" if direction == "bullish" else "low"
    future_swings = [s for s in swings if s["index"] > from_index and s["type"] == target_type]
    return future_swings[0] if future_swings else None


def simulate_trade(candles: list[dict], entry_index: int, direction: str,
                    pd_array: dict, entry_price: float) -> dict | None:
    """
    Simule un trade unique : calcule SL (au-delà du PD array) et TP (prochain swing
    opposé), puis parcourt les bougies futures pour voir lequel est touché en premier.

    Retourne un dict avec le résultat, ou None si pas de TP trouvable (setup ignoré).
    """
    if direction == "bullish":
        stop_loss = pd_array["bottom"] * 0.9995  # petite marge sous la zone
    else:
        stop_loss = pd_array["top"] * 1.0005  # petite marge au-dessus de la zone

    next_swing = find_next_opposite_swing(candles, entry_index, direction)
    if not next_swing:
        return None  # pas de cible de liquidité claire, on ignore ce setup pour le backtest

    take_profit = next_swing["price"]

    # Le RR doit être positif et raisonnable (filtre les setups dégénérés)
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    if risk <= 0 or reward <= 0:
        return None
    rr = reward / risk

    # Parcours des bougies futures pour voir ce qui est touché en premier
    for c in candles[entry_index + 1:]:
        if direction == "bullish":
            if c["low"] <= stop_loss:
                return {"result": "loss", "rr": rr, "exit_reason": "stop_loss"}
            if c["high"] >= take_profit:
                return {"result": "win", "rr": rr, "exit_reason": "take_profit"}
        else:
            if c["high"] >= stop_loss:
                return {"result": "loss", "rr": rr, "exit_reason": "stop_loss"}
            if c["low"] <= take_profit:
                return {"result": "win", "rr": rr, "exit_reason": "take_profit"}

    return None  # ni SL ni TP touché avant la fin des données -> trade ignoré (incomplet)


def backtest_pair(pair: str, htf_candles: list[dict], exec_candles: list[dict]) -> list[dict]:
    """
    Rejoue la logique de find_candidate_setups bougie par bougie sur l'historique
    d'exécution, en ne regardant à chaque instant que les données disponibles
    jusqu'à cet instant (pour éviter le biais de "voir le futur").
    """
    trades = []
    min_lookback = 30  # nombre minimal de bougies avant de commencer à chercher des setups

    for i in range(min_lookback, len(exec_candles) - 1):
        window = exec_candles[:i + 1]  # uniquement le passé jusqu'à cette bougie

        # Biais HTF : on utilise les bougies D1 dont la date est antérieure à la bougie courante
        current_date = exec_candles[i]["datetime"][:10]
        htf_window = [c for c in htf_candles if c["datetime"][:10] <= current_date]
        if len(htf_window) < 10:
            continue

        bias_info = determine_bias(htf_window)
        bias = bias_info["bias"]
        if bias == "neutral":
            continue

        expected_type = "bullish" if bias == "bullish" else "bearish"
        virgin_arrays = get_virgin_pd_arrays(window)
        matching = [a for a in virgin_arrays if expected_type in a["type"]]
        if not matching:
            continue

        ote_zone = calculate_ote_zone(window, bias)
        if not ote_zone:
            continue

        for arr in matching:
            if not zones_overlap(arr["top"], arr["bottom"], ote_zone["top"], ote_zone["bottom"], ZONE_OVERLAP_TOLERANCE):
                continue

            entry_price = exec_candles[i]["close"]
            trade_result = simulate_trade(exec_candles, i, bias, arr, entry_price)
            if trade_result:
                trades.append({
                    "pair": pair,
                    "datetime": exec_candles[i]["datetime"],
                    "direction": bias,
                    **trade_result,
                })

    return trades


def compute_stats(trades: list[dict]) -> dict:
    """Calcule winrate, RR moyen, et profit factor à partir d'une liste de trades."""
    if not trades:
        return {"total_trades": 0, "winrate": 0, "avg_rr": 0, "profit_factor": 0}

    wins = [t for t in trades if t["result"] == "win"]
    losses = [t for t in trades if t["result"] == "loss"]

    winrate = len(wins) / len(trades) * 100
    avg_rr = sum(t["rr"] for t in trades) / len(trades)

    gross_profit = sum(t["rr"] for t in wins)
    gross_loss = len(losses)  # chaque perte = 1 unité de risque
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": round(winrate, 1),
        "avg_rr": round(avg_rr, 2),
        "profit_factor": round(profit_factor, 2),
    }


def run_full_backtest():
    """Lance le backtest sur toutes les paires configurées et affiche les résultats."""
    all_trades = []

    for pair in PAIRS:
        print(f"\n--- Backtest {pair} ---")
        try:
            htf_candles = fetch_candles(pair, "1day", outputsize=5000)
            exec_candles = fetch_candles(pair, "4h", outputsize=5000)
        except Exception as e:
            print(f"Erreur récupération données pour {pair}: {e}")
            continue

        print(f"  Bougies D1 récupérées: {len(htf_candles)}")
        print(f"  Bougies H4 récupérées: {len(exec_candles)}")

        if htf_candles:
            print(f"  Période D1: {htf_candles[0]['datetime']} -> {htf_candles[-1]['datetime']}")
        if exec_candles:
            print(f"  Période H4: {exec_candles[0]['datetime']} -> {exec_candles[-1]['datetime']}")

        trades = backtest_pair(pair, htf_candles, exec_candles)
        stats = compute_stats(trades)
        print(f"  Résultats: {stats}")

        all_trades.extend(trades)

    print("\n=== RÉSULTATS GLOBAUX (toutes paires confondues) ===")
    global_stats = compute_stats(all_trades)
    print(json.dumps(global_stats, indent=2))

    with open("backtest_results.json", "w", encoding="utf-8") as f:
        json.dump({"trades": all_trades, "stats": global_stats}, f, indent=2, ensure_ascii=False)

    print("\nDétails complets sauvegardés dans backtest_results.json")
    return all_trades, global_stats


if __name__ == "__main__":
    run_full_backtest()
