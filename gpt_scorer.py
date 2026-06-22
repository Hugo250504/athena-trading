"""
ATHENA Trading - GPT Scorer
Envoie chaque setup candidat à GPT pour un score de confluence final (0-100).
"""

import json
import requests
from config import OPENAI_API_KEY, GPT_MODEL

OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEM_PROMPT = """Tu es un analyste trading spécialisé ICT/SMC (Inner Circle Trader / Smart Money Concepts).
On te donne un setup candidat détecté algorithmiquement sur Forex. Ton rôle est d'évaluer la
QUALITÉ DE CONFLUENCE de ce setup, pas de donner un conseil d'investissement.

Réponds UNIQUEMENT en JSON, sans aucun texte avant ou après, au format exact :
{"score": <entier 0-100>, "verdict": "<court résumé en français, 1 phrase>"}

Critères d'évaluation :
- Clarté et fraîcheur du biais HTF (structure D1 nette = score plus haut)
- Qualité du PD array (un FVG/OB net et bien formé > un signal ambigu)
- Précision de l'alignement avec la zone OTE (chevauchement fort = meilleur score)
- Cohérence générale de la confluence (les 3 éléments doivent raconter la même histoire)

Un score >= 70 signifie un setup de bonne qualité technique. Sois rigoureux et exigeant,
ne donne pas de scores élevés par défaut."""


def score_setup(setup: dict) -> dict:
    """
    Envoie un setup candidat à GPT et retourne {"score": int, "verdict": str}.
    En cas d'erreur API, retourne un score de 0 avec le message d'erreur en verdict.
    """
    user_content = json.dumps(setup, ensure_ascii=False, indent=2)

    payload = {
        "model": GPT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(OPENAI_URL, headers=headers, json=payload, timeout=20)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        return {
            "score": int(result.get("score", 0)),
            "verdict": result.get("verdict", ""),
        }
    except Exception as e:
        print(f"[score_setup] Erreur GPT pour {setup.get('pair')}: {e}")
        return {"score": 0, "verdict": f"Erreur scoring: {e}"}


def score_all_setups(setups: list[dict]) -> list[dict]:
    """Score une liste de setups candidats et retourne ceux enrichis avec score + verdict."""
    scored = []
    for setup in setups:
        result = score_setup(setup)
        enriched = {**setup, **result}
        scored.append(enriched)
    return scored
