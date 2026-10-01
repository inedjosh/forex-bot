"""Strategy registry.

Add your strategy here so the runners can find it by name.
"""

from typing import Dict, Type

from ..core.strategy import Strategy
from .crt import CrtStrategy
from .ema_crossover import EmaCrossover
from .my_formula import MyFormula

REGISTRY: Dict[str, Type[Strategy]] = {
    "crt": CrtStrategy,             # the bot's core strategy
    "my_formula": MyFormula,        # legacy placeholder (EMA + RSI)
    "ema_crossover": EmaCrossover,  # sample
}


def get_strategy(name: str) -> Strategy:
    if name not in REGISTRY:
        available = ", ".join(sorted(REGISTRY))
        raise KeyError(f"Unknown strategy '{name}'. Available: {available}")
    return REGISTRY[name]()
