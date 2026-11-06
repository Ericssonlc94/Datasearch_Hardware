"""Progresso da coleta exibido na tela de carregamento.

O percentual é a fração de consultas concluídas, não uma estimativa de tempo.
Como o coletor dispara todas as fontes em paralelo, o número pode andar em
saltos e depois ficar parado nas fontes mais lentas — é melhor mostrar a
contagem real do que inventar uma barra que finge saber quanto falta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

Stage = Literal["idle", "collecting", "building", "ready", "error"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


@dataclass
class CollectionProgress:
    """Estado mutável de um ciclo de coleta.

    Vive no processo principal, assim como o snapshot. Com `--workers 1`, o
    endpoint de progresso e a coleta enxergam o mesmo objeto.
    """

    stage: Stage = "idle"
    total: int = 0
    completed: int = 0
    started_at: datetime | None = None
    updated_at: datetime | None = None
    finished_at: datetime | None = None
    last_key: str | None = None
    error: str | None = None

    def start(self, total: int) -> None:
        self.stage = "collecting"
        self.total = max(0, total)
        self.completed = 0
        self.started_at = _now()
        self.updated_at = self.started_at
        self.finished_at = None
        self.last_key = None
        self.error = None

    def step(self, key: str) -> None:
        self.completed += 1
        if self.total:
            self.completed = min(self.completed, self.total)
        self.last_key = key
        self.updated_at = _now()

    def building(self) -> None:
        self.stage = "building"
        self.updated_at = _now()

    def ready(self) -> None:
        self.stage = "ready"
        self.completed = self.total
        self.updated_at = _now()
        self.finished_at = self.updated_at

    def fail(self, error: str) -> None:
        self.stage = "error"
        self.error = error
        self.updated_at = _now()
        self.finished_at = self.updated_at

    def percent(self) -> int:
        if self.stage == "ready":
            return 100
        if not self.total:
            return 0
        # Durante a montagem ainda falta gravar o histórico; 99% é mais honesto
        # que 100% com a tela ainda bloqueada.
        return min(99, round(self.completed / self.total * 100))

    def snapshot(self) -> dict:
        now = self.finished_at or _now()
        elapsed = (
            max(0.0, (now - self.started_at).total_seconds())
            if self.started_at is not None
            else 0.0
        )
        return {
            "stage": self.stage,
            "percent": self.percent(),
            "completed": self.completed,
            "total": self.total,
            "elapsed_seconds": round(elapsed, 1),
            "started_at": _iso(self.started_at),
            "updated_at": _iso(self.updated_at),
            "finished_at": _iso(self.finished_at),
            "last_key": self.last_key,
            "error": self.error,
        }


progress = CollectionProgress()
