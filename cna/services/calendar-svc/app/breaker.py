"""Interruptor de circuito mínimo (ADR y experimento X5).

closed  -> las llamadas pasan; cada falla suma.
open    -> tras `fail_max` fallas seguidas, se rechaza todo durante `reset_timeout` segundos.
half    -> pasado ese tiempo, se deja pasar una llamada de prueba: si sale bien se cierra.
"""
import time


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 30.0, clock=time.monotonic):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.clock = clock
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        if self.clock() - self.opened_at >= self.reset_timeout:
            return "half_open"
        return "open"

    def before_call(self) -> None:
        if self.state == "open":
            raise CircuitOpenError("circuito abierto")

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.fail_max:
            self.opened_at = self.clock()
