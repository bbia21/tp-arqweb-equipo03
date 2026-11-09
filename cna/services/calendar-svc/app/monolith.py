"""Llamada síncrona al monolito: verifica que un outfit existe (B4, usuario de servicio).

Es opcional: si MONOLITH_URL está vacío no se usa. Aplica timeout, reintentos con
backoff exponencial e interruptor de circuito (experimento X5). Si el monolito no
responde, el servicio degrada: guarda la entrada igual y lo deja registrado en el log.
"""
import logging
import os

from .tracing import SpanKind, Status, StatusCode, inject, tracer

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .breaker import CircuitBreaker, CircuitOpenError

log = logging.getLogger("monolith")


class OutfitNotFound(Exception):
    pass


class MonolithClient:
    def __init__(self, base_url: str, email: str, password: str, timeout: float, verify_tls: bool,
                 password_file: str = ""):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.password_file = password_file
        self.password_mtime = None
        self.client = httpx.AsyncClient(timeout=timeout, verify=verify_tls, follow_redirects=False)
        self.breaker = CircuitBreaker(fail_max=5, reset_timeout=30)
        self.logged_in = False

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.email and self.password)

    def _current_password(self) -> str:
        """Contraseña vigente: la del archivo de rotación si existe, si no la de la variable de entorno."""
        if self.password_file and os.path.exists(self.password_file):
            with open(self.password_file, encoding="utf-8") as f:
                value = f.read().strip()
            if value:
                return value
        return self.password

    def _check_rotation(self) -> None:
        """Si el archivo de rotación cambió, descarta la sesión para volver a entrar con la clave nueva."""
        if not self.password_file or not os.path.exists(self.password_file):
            return
        mtime = os.path.getmtime(self.password_file)
        if mtime != self.password_mtime:
            if self.password_mtime is not None or self.logged_in:
                log.info("credencial del usuario de servicio rotada: se renueva la sesión")
            self.password_mtime = mtime
            self.logged_in = False
            self.client.cookies.clear()

    async def _login(self) -> None:
        response = await self.client.post(
            f"{self.base_url}/auth/login", data={"email": self.email, "password": self._current_password()}
        )
        if "access_token" not in self.client.cookies:
            raise RuntimeError(f"login del usuario de servicio falló (HTTP {response.status_code})")
        self.logged_in = True

    async def _get_outfit(self, outfit_id: int) -> int:
        if not self.logged_in:
            await self._login()
        with tracer.start_as_current_span(f"GET /outfits/{outfit_id}", kind=SpanKind.CLIENT,
                                          attributes={"server.address": "librecloset.arqweb.test"}) as span:
            response = await self.client.get(f"{self.base_url}/outfits/{outfit_id}", headers=inject({}))
            if response.status_code in (301, 302, 401):  # sesión vencida
                self.logged_in = False
                await self._login()
                response = await self.client.get(f"{self.base_url}/outfits/{outfit_id}", headers=inject({}))
            span.set_attribute("http.response.status_code", response.status_code)
            return response.status_code

    async def outfit_exists(self, outfit_id: int) -> bool | None:
        """True / False si el monolito respondió; None si no se pudo verificar (degradación)."""
        if not self.enabled:
            return None
        with tracer.start_as_current_span("monolito: verificar outfit", attributes={"outfit_id": outfit_id}) as span:
            result = await self._outfit_exists(outfit_id)
            span.set_attribute("circuito", self.breaker.state)
            span.set_attribute("resultado", "degradado" if result is None else str(result).lower())
            if result is None:
                span.set_status(Status(StatusCode.ERROR, "no se pudo verificar (degradación)"))
            return result

    async def _outfit_exists(self, outfit_id: int) -> bool | None:
        self._check_rotation()
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
