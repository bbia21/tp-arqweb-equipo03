// Prueba de carga C2 (k6). Se corre desde VM-1, contra el gateway:
//
//   docker run --rm --network host \
//     --add-host librecloset.arqweb.test:127.0.0.1 --add-host api.librecloset.arqweb.test:127.0.0.1 \
//     -e ESCENARIO=calendario -e VUS=10 -e EMAIL=tu@correo -e PASSWORD=tuclave \
//     -v "$PWD/perf":/perf grafana/k6 run --summary-export /perf/resultados/cal-10.json /perf/load.js
//
// ESCENARIO:
//   calendario  -> compara GET /calendar del monolito contra GET /v2/calendar de S1 (mismo período)
//   clima       -> GET /v2/weather (S3); se corre con 1 réplica y después con 3
// VUS: usuarios virtuales (10 o 50). DURACION: por defecto 60s.
//
// Nota: el gateway tiene limit_req de 20 r/s (burst 10) por IP. Con 50 VUs desde una sola IP
// aparecen respuestas 429: se cuentan aparte (métrica "limitadas") y no como errores, porque
// son el rate limiting funcionando.

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';

const ESCENARIO = __ENV.ESCENARIO || 'calendario';
const VUS = parseInt(__ENV.VUS || '10', 10);
const DURACION = __ENV.DURACION || '60s';
const MONOLITO = __ENV.MONOLITO || 'https://librecloset.arqweb.test';
const API = __ENV.API || 'https://api.librecloset.arqweb.test';

const limitadas = new Counter('limitadas');

function escenario(exec, tag) {
  return { executor: 'constant-vus', vus: VUS, duration: DURACION, exec, tags: { destino: tag } };
}

const escenarios = {};
if (ESCENARIO === 'calendario') {
  escenarios.monolito = escenario('monolito', 'monolito');
  escenarios.microservicio = { ...escenario('microservicio', 's1'), startTime: DURACION };
} else {
  escenarios.clima = escenario('clima', 's3');
}

export const options = {
  insecureSkipTLSVerify: true, // certificado autofirmado del TP I
  scenarios: escenarios,
  summaryTrendStats: ['avg', 'p(50)', 'p(95)', 'p(99)', 'max'],
  thresholds: ESCENARIO === 'calendario'
    ? { 'http_req_duration{destino:monolito}': ['p(95)<2000'], 'http_req_duration{destino:s1}': ['p(95)<1000'], checks: ['rate>0.95'] }
    : { 'http_req_duration{destino:s3}': ['p(95)<1000'], checks: ['rate>0.95'] },
};

function registrar(res) {
  if (res.status === 429) {
    limitadas.add(1);
    return;
  }
  check(res, { 'status 200': (r) => r.status === 200 });
}

// Cada VU inicia sesión una sola vez; k6 guarda la cookie en el jar de ese VU.
let logueado = false;
function login() {
  if (logueado) return;
  if (!__ENV.EMAIL || !__ENV.PASSWORD) throw new Error('faltan EMAIL y PASSWORD para el escenario del monolito');
  const res = http.post(`${MONOLITO}/auth/login`, { email: __ENV.EMAIL, password: __ENV.PASSWORD }, { redirects: 0, tags: { destino: 'login' } });
  check(res, { 'login ok': (r) => r.status === 302 || r.status === 200 });
  logueado = true;
}

export function monolito() {
  login();
  registrar(http.get(`${MONOLITO}/calendar`, { tags: { destino: 'monolito' } }));
  sleep(1);
}

export function microservicio() {
  registrar(http.get(`${API}/v2/calendar`, { tags: { destino: 's1' } }));
  sleep(1);
}

// Varias ubicaciones para que no todo salga del mismo registro de caché
const LUGARES = [
  [-25.30, -57.63], // Asunción
  [-25.51, -54.61], // Ciudad del Este
  [-27.33, -55.87], // Encarnación
  [-22.55, -55.73], // Pedro Juan Caballero
];

export function clima() {
  const [lat, lon] = LUGARES[Math.floor(Math.random() * LUGARES.length)];
  registrar(http.get(`${API}/v2/weather?lat=${lat}&lon=${lon}&days=7`, { tags: { destino: 's3' } }));
  sleep(1);
}
