"""Llamada síncrona al monolito: verifica que un outfit existe (B4, usuario de servicio).

Es opcional: si MONOLITH_URL está vacío no se usa. Aplica timeout, reintentos con
backoff exponencial e interruptor de circuito (experimento X5). Si el monolito no
responde, el servicio degrada: guarda la entrada igual y lo deja registrado en el log.
"""
import logging

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .breaker import CircuitBreaker, CircuitOpenError

log = logging.getLogger("monolith")


class OutfitNotFound(Exception):
    pass


class MonolithClient:
    def __init__(self, base_url: str, email: str, password: str, timeout: float, verify_tls: bool):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.client = httpx.AsyncClient(timeout=timeout, verify=verify_tls, follow_redirects=False)
        self.breaker = CircuitBreaker(fail_max=5, reset_timeout=30)
        self.logged_in = False

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.email and self.password)

    async def _login(self) -> None:
        response = await self.client.post(
            f"{self.base_url}/auth/login", data={"email": self.email, "password": self.password}
        )
        if "access_token" not in self.client.cookies:
            raise RuntimeError(f"login del usuario de servicio falló (HTTP {response.status_code})")
        self.logged_in = True

    async def _get_outfit(self, outfit_id: int) -> int:
        if not self.logged_in:
            await self._login()
        response = await self.client.get(f"{self.base_url}/outfits/{outfit_id}")
        if response.status_code in (301, 302, 401):  # sesión vencida
            self.logged_in = False
            await self._login()
            response = await self.client.get(f"{self.base_url}/outfits/{outfit_id}")
        return response.status_code

    async def outfit_exists(self, outfit_id: int) -> bool | None:
        """True / False si el monolito respondió; None si no se pudo verificar (degradación)."""
        if not self.enabled:
            return None
        try:
            self.breaker.before_call()
        except CircuitOpenError:
            log.warning("circuito abierto: no se verifica el outfit %s", outfit_id)
            return None
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=0.2, max=2),
                retry=retry_if_exception_type((httpx.TransportError, RuntimeError)),
                reraise=True,
            ):
                with attempt:
                    code = await self._get_outfit(outfit_id)
            self.breaker.record_success()
            return code != 404
        except (httpx.TransportError, RuntimeError) as exc:
            self.breaker.record_failure()
            log.warning(
                "monolito no disponible (%s); circuito=%s", type(exc).__name__, self.breaker.state,
                extra={"extra_fields": {"outfit_id": outfit_id}},
            )
            return None

    async def close(self) -> None:
        await self.client.aclose()
