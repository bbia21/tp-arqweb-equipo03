# ADR-008: Plataforma de orquestación y red entre nodos

**Estatus:** Aceptado

## Contexto

La infraestructura disponible es un único equipo anfitrión con VirtualBox, una persona trabajando y VMs
de 2 vCPU / 4 GB. Durante el TP el adaptador *host-only* de VirtualBox falló en el anfitrión
(`VERR_INTNET_FLT_IF_NOT_FOUND`, problema del driver de red).

## Decisión

1. **Docker Compose en dos nodos**, coordinado desde VM-1 con un **contexto de Docker por SSH**
   (`docker --context cna-node1`). Un solo comando (`make up`) despliega VM-1 y VM-2.
2. Topología: **VM-1** (`librecloset`, 192.168.56.10): Nginx, Libre Closet, PostgreSQL y `event-bridge`.
   **VM-2** (`cna-node1`, 192.168.56.11): RabbitMQ, S1, S2, S3 y sus almacenes. La VM-3 opcional no se usa
   por RAM del anfitrión; la observabilidad se ubica en VM-2.
3. Red entre nodos: **red interna de VirtualBox** (`intnet` "cnanet") en la segunda placa de cada VM.
   El acceso desde el anfitrión es por reenvío de puertos de la placa NAT (22 y 443 de VM-1).
4. Cada contenedor declara límites de CPU y memoria; `restart: unless-stopped` recrea los que se caen.

## Alternativas descartadas

| Alternativa | Por qué se descartó |
| --- | --- |
| Docker Swarm (2–3 nodos) | Suma hasta 2 pts en B5, pero agrega red *overlay*, secretos y *stacks* que no se llegaban a probar en el plazo; se deja como mejora |
| k3s | ~500 MB de RAM solo el plano de control, en VMs de 4 GB |
| Red *host-only* | Falló el driver del anfitrión; la red interna no depende de drivers de Windows |

## Consecuencias

**Positivas**
- Despliegue reproducible en un comando (CA-7) con las mismas herramientas en los dos nodos.
- La red interna aísla el tráfico entre nodos del exterior.

**Negativas**
- Sin *scheduler*: si VM-2 se apaga, sus contenedores no se mueven a otro nodo; vuelven solos al encenderla
  (experimento X4).
- El escalado de réplicas es manual (`docker compose up --scale`), sin balanceo automático entre nodos.
- Desde Windows no se llega directo a VM-2; se entra por SSH en el puerto 2223.
