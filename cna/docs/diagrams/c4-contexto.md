# C4 nivel 1 · Contexto (F5-E5)

```mermaid
C4Context
  title Libre Closet Cloud Native · diagrama de contexto

  Person(usuario, "Usuaria", "Organiza su guardarropa, arma outfits y los agenda en el calendario")
  Person(cliente, "Cliente de la API", "curl, k6 o una app que consume /v2/*")

  System(closet, "Libre Closet Cloud Native", "Monolito Libre Closet + microservicios de calendario, estadísticas y clima detrás de un gateway único (443)")

  System_Ext(openmeteo, "Open-Meteo", "API pública de pronóstico del clima")
  System_Ext(nominatim, "Nominatim", "Geocodificación inversa (nombre del lugar)")

  Rel(usuario, closet, "Usa la web", "HTTPS 443 · librecloset.arqweb.test")
  Rel(cliente, closet, "Consulta calendario, estadísticas y clima", "HTTPS 443 · api.librecloset.arqweb.test")
  Rel(closet, openmeteo, "Pide pronósticos", "HTTPS")
  Rel(closet, nominatim, "Pide el nombre del lugar (desde el monolito)", "HTTPS")
```

Todo el tráfico externo entra por el puerto 443 de VM-1 (CA-4). El sistema depende de dos servicios
externos; solo Open-Meteo está protegido con caché e interruptor de circuito (S3).
