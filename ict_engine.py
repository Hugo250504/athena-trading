"""
ATHENA Trading - ICT/SMC Detection Engine
Détecte : biais de structure (BOS/CHoCH), PD arrays vierges (FVG, OB, BB),
et zones OTE. Combine tout pour produire des "setups candidats".
"""

from config import OTE_FIB_LOW, OTE_FIB_HIGH, ZONE_OVERLAP_TOLERANCE


# ───────────────────────── STRUCTURE (BOS / CHoCH) ─────────────────────────

def find_swing_points(candles: list[dict], window: int = 2) -> list[dict]:
    """
    Détecte les swing highs / swing lows simples (fractals).
    window = nombre de bougies de chaque côté pour confirmer le pivot.
    """
    swings = []
    for i in range(window, len(candles) - window):
        high = candles[i]["high"]
        low = candles[i]["low"]

        is_swing_high = all(high >= candles[i - j]["high"] for j in range(1, window + 1)) and \
                         all(high >= candles[i + j]["high"] for j in range(1, window + 1))
        is_swing_low = all(low <= candles[i - j]["low"] for j in range(1, window + 1)) and \
                        all(low <= candles[i + j]["low"] for j in range(1, window + 1))

        if is_swing_high:
            swings.append({"index": i, "type": "high", "price": high, "datetime": candles[i]["datetime"]})
        if is_swing_low:
            swings.append({"index": i, "type": "low", "price": low, "datetime": candles[i]["datetime"]})

    return swings


def determine_bias(candles: list[dict]) -> dict:
    """
    Détermine le biais directionnel (bullish/bearish/neutral) à partir
    de la séquence des derniers swing highs/lows (structure de marché simplifiée).

    Logique : si les derniers swings forment des higher-highs + higher-lows -> bullish
    Si lower-highs + lower-lows -> bearish
    Sinon -> neutral (pas de biais clair, le setup sera ignoré)
    """
    swings = find_swing_points(candles)
    if len(swings) < 4:
        return {"bias": "neutral", "reason": "pas assez de swings détectés"}

    highs = [s for s in swings if s["type"] == "high"][-2:]
    lows = [s for s in swings if s["type"] == "low"][-2:]

    if len(highs) < 2 or len(lows) < 2:
        return {"bias": "neutral", "reason": "swings insuffisants"}

    higher_high = highs[-1]["price"] > highs[-2]["price"]
    higher_low = lows[-1]["price"] > lows[-2]["price"]
    lower_high = highs[-1]["price"] < highs[-2]["price"]
    lower_low = lows[-1]["price"] < lows[-2]["price"]

    if higher_high and higher_low:
        return {"bias": "bullish", "reason": "higher-high + higher-low"}
    if lower_high and lower_low:
        return {"bias": "bearish", "reason": "lower-high + lower-low"}

    return {"bias": "neutral", "reason": "structure mixte"}


# ───────────────────────── PD ARRAYS (FVG, OB, BB) ─────────────────────────

def detect_fvgs(candles: list[dict]) -> list[dict]:
    """
    Détecte les Fair Value Gaps sur 3 bougies consécutives.
    Bullish FVG : low[i+2] > high[i]  (gap entre bougie 1 et 3 vers le haut)
    Bearish FVG : high[i+2] < low[i]
    """
    fvgs = []
    for i in range(len(candles) - 2):
        c1, c3 = candles[i], candles[i + 2]

        if c3["low"] > c1["high"]:
            fvgs.append({
                "type": "bullish_fvg",
                "top": c3["low"],
                "bottom": c1["high"],
                "formed_at_index": i + 2,
                "datetime": candles[i + 2]["datetime"],
                "tested": False,
            })
        elif c3["high"] < c1["low"]:
            fvgs.append({
                "type": "bearish_fvg",
                "top": c1["low"],
                "bottom": c3["high"],
                "formed_at_index": i + 2,
                "datetime": candles[i + 2]["datetime"],
                "tested": False,
            })

    return fvgs


def detect_order_blocks(candles: list[dict]) -> list[dict]:
    """
    Détecte des Order Blocks simplifiés : dernière bougie baissière avant un
    mouvement haussier impulsif (bullish OB), ou inverse (bearish OB).
    Un mouvement impulsif = bougie suivante dont le range dépasse 1.5x la moyenne récente.
    """
    obs = []
    if len(candles) < 10:
        return obs

    avg_range = sum(c["high"] - c["low"] for c in candles[-20:]) / min(20, len(candles))

    for i in range(1, len(candles) - 1):
        prev, curr = candles[i - 1], candles[i]
        curr_range = curr["high"] - curr["low"]
        is_impulsive = curr_range > 1.5 * avg_range

        # Bullish OB : bougie baissière suivie d'une impulsion haussière
        if prev["close"] < prev["open"] and curr["close"] > curr["open"] and is_impulsive:
            obs.append({
                "type": "bullish_ob",
                "top": prev["open"],
                "bottom": prev["low"],
                "formed_at_index": i - 1,
                "datetime": prev["datetime"],
                "tested": False,
            })

        # Bearish OB : bougie haussière suivie d'une impulsion baissière
        if prev["close"] > prev["open"] and curr["close"] < curr["open"] and is_impulsive:
            obs.append({
                "type": "bearish_ob",
                "top": prev["high"],
                "bottom": prev["open"],
                "formed_at_index": i - 1,
                "datetime": prev["datetime"],
                "tested": False,
            })

    return obs


def mark_tested_arrays(arrays: list[dict], candles: list[dict]) -> list[dict]:
    """
    Marque chaque PD array comme 'tested=True' si le prix est revenu dans sa zone
    après sa formation. On ne garde que les vierges (jamais retestés) pour les setups.
    """
    for arr in arrays:
        start = arr["formed_at_index"] + 1
        for c in candles[start:]:
            if c["low"] <= arr["top"] and c["high"] >= arr["bottom"]:
                arr["tested"] = True
                break
    return arrays


def get_virgin_pd_arrays(candles: list[dict]) -> list[dict]:
    """Retourne tous les PD arrays (FVG + OB) jamais retestés depuis leur formation."""
    fvgs = detect_fvgs(candles)
    obs = detect_order_blocks(candles)
    all_arrays = fvgs + obs
    all_arrays = mark_tested_arrays(all_arrays, candles)
    return [a for a in all_arrays if not a["tested"]]


# ───────────────────────── OTE (Optimal Trade Entry) ─────────────────────────

def calculate_ote_zone(candles: list[dict], bias: str) -> dict | None:
    """
    Calcule la zone OTE (62%-79% Fib) de la dernière impulsion dans le sens du biais.

    Pour un biais bullish : on cherche le dernier swing low, puis le swing high
    le plus récent formé APRÈS ce swing low (l'impulsion haussière la plus récente).
    Pour bearish : logique inverse.
    """
    swings = find_swing_points(candles)
    if len(swings) < 2:
        return None

    highs = [s for s in swings if s["type"] == "high"]
    lows = [s for s in swings if s["type"] == "low"]

    if bias == "bullish":
        if not lows:
            return None
        last_low = lows[-1]
        candidate_highs = [h for h in highs if h["index"] > last_low["index"]]
        if not candidate_highs:
            return None
        last_high = candidate_highs[-1]

        impulse_range = last_high["price"] - last_low["price"]
        if impulse_range <= 0:
            return None
        ote_top = last_high["price"] - OTE_FIB_LOW * impulse_range
        ote_bottom = last_high["price"] - OTE_FIB_HIGH * impulse_range
        return {"top": ote_top, "bottom": ote_bottom, "direction": "bullish"}

    if bias == "bearish":
        if not highs:
            return None
        last_high = highs[-1]
        candidate_lows = [l for l in lows if l["index"] > last_high["index"]]
        if not candidate_lows:
            return None
        last_low = candidate_lows[-1]

        impulse_range = last_low["price"] - last_high["price"]
        if impulse_range <= 0:
            return None
        ote_top = last_low["price"] - OTE_FIB_HIGH * impulse_range
        ote_bottom = last_low["price"] - OTE_FIB_LOW * impulse_range
        return {"top": ote_top, "bottom": ote_bottom, "direction": "bearish"}

    return None


# ───────────────────────── CONFLUENCE FINALE ─────────────────────────

def zones_overlap(zone_a_top, zone_a_bottom, zone_b_top, zone_b_bottom, tolerance: float) -> bool:
    """Vérifie si deux zones de prix se chevauchent (avec tolérance en %)."""
    range_a = zone_a_top - zone_a_bottom
    margin = range_a * tolerance
    return not (zone_a_bottom - margin > zone_b_top or zone_a_top + margin < zone_b_bottom)


def find_candidate_setups(pair: str, htf_candles: list[dict], exec_candles: list[dict]) -> list[dict]:
    """
    Combine biais HTF (D1) + PD array vierge (H4) + zone OTE (H4) alignés.
    Retourne la liste des setups candidats prêts à être envoyés à GPT pour scoring.
    """
    htf_bias_info = determine_bias(htf_candles)
    bias = htf_bias_info["bias"]

    if bias == "neutral":
        return []

    expected_array_type = "bullish" if bias == "bullish" else "bearish"

    virgin_arrays = get_virgin_pd_arrays(exec_candles)
    matching_arrays = [a for a in virgin_arrays if expected_array_type in a["type"]]

    if not matching_arrays:
        return []

    ote_zone = calculate_ote_zone(exec_candles, bias)
    if not ote_zone:
        return []

    candidates = []
    for arr in matching_arrays:
        if zones_overlap(arr["top"], arr["bottom"], ote_zone["top"], ote_zone["bottom"], ZONE_OVERLAP_TOLERANCE):
            candidates.append({
                "pair": pair,
                "htf_bias": bias,
                "htf_reason": htf_bias_info["reason"],
                "pd_array_type": arr["type"],
                "pd_array_zone": {"top": arr["top"], "bottom": arr["bottom"]},
                "pd_array_formed_at": arr["datetime"],
                "ote_zone": ote_zone,
                "current_price": exec_candles[-1]["close"],
            })

    return candidates
