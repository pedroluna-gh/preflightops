# Operación, resiliencia y recuperación

PreflightOps funciona como CLI/biblioteca offline y UI Streamlit opcional. No tiene
base de datos ni un servicio de assessment alojado. La salud de Streamlit pertenece
al proceso/contenedor que lo ejecuta; no demuestra que un provider sea usable. No se
agrega endpoint de readiness ni se afirma alta disponibilidad o DR de un backend.

## Inicio y diagnóstico offline

Desde una instalación verificada, usar un directorio privado de trabajo y destinos
nuevos. Estos comandos usan sólo fixtures del repositorio y no escriben en integraciones:

```powershell
python -m preflightops.operational_probe --iterations 100 --output probe.json
python -m preflightops.cli --services examples/services-low-risk.yaml --change examples/change-low-risk.yaml --output report.md --telemetry-output operations.json
```

La sonda devuelve 0 si cumple sus objetivos, 1 si una medición/invariante incumple y
2 por configuración o destino inválido. El CLI de assessment conserva 0 para riesgo
LOW/MEDIUM/HIGH, 1 para CRITICAL, 2 para input/política/integración/escritura inválida.
**0 nunca significa aprobación humana.** Los comandos policy/evidence/report conservan
sus códigos y pueden usar el flag global de telemetría. `report render` vincula el
assessment ID validado; el reporte legacy no inventa un ID de assessment.

`--correlation-id` acepta un identificador aprobado de 32 caracteres hex minúsculos;
si se omite se genera un UUID aleatorio. No usar hashes de secretos o identidades.
La telemetría no entra en los bytes reproducibles de assessment. Sin flag, no se crea
ningún artefacto operacional. El destino se reserva con creación exclusiva antes de
evaluar: no reemplaza archivos existentes, inputs ni otros outputs. Un fallo posterior
puede dejar un archivo incompleto; tratarlo como inválido, nunca como éxito.

## SLI, SLO y presupuesto de errores

| Señal | Objetivo interno | Ventana / acción |
| --- | --- | --- |
| Replay con mismos inputs/contexto | 100% bytes iguales | Cada prueba/sonda; cualquier diferencia bloquea promoción |
| ERROR/UNKNOWN no convertido en PASS | 100% | Suite de fallos; presupuesto cero para falsa aprobación |
| Latencia offline warm, fixture LOW incluida | p95 <=250 ms | 100 iteraciones por cambio, mismo runner; investigar regresión antes de promover |
| Memoria asignada por Python durante esa carga | pico <=64 MiB | `tracemalloc`, no RSS; revisar crecimiento y tamaño del workload |
| Finalización técnica en workload válido | >=99.9% | Ventana móvil de 30 días del operador, mínimo 1,000 ejecuciones; <=1 error interno por 1,000 |

250 ms permite ejecutar gates interactivos pequeños con margen para runners variables.
64 MiB limita una carga pequeña, no el RSS de Streamlit ni planes máximos. Estos son
objetivos iniciales de ingeniería: no prometen rendimiento para cualquier input.
El percentil nearest-rank, throughput, plataforma/Python, iteraciones y memoria real
se guardan en `probe.json`. No se inventa una ventana productiva de 30 días: hasta
reunirla, el SLO de finalización es un objetivo **no demostrado**. Un CRITICAL esperado
es una evaluación correcta, no un error técnico. Excluir input inválido de esa tasa;
registrar errores internos/I/O por separado al clasificar incidentes.

Agotar el presupuesto detiene funcionalidades nuevas; priorizar recuperación y
regresiones. No relajar gates o silenciar alertas. Dependencias externas tienen su
propio SLI de degradación: `operations_provider_degraded / latency_provider_count`.
Una dependencia caída se representa como ERROR/UNKNOWN; no se compensa con un PASS.

## Contrato de telemetría y límites

`schemas/operations-v1.schema.json` define campos estrictos. El recorder de Python
se conecta con `ProviderRunner(recorder=OperationsRecorder())`; exportar mediante
`serialize()` a un destino local aprobado. La aplicación que hospeda la biblioteca
decide la persistencia. El CLI instrumenta sus ejecuciones; no activa providers.

| Recurso | Límite |
| --- | --- |
| Eventos estructurados | 256 por recorder, ventana de los últimos eventos; `events_dropped` cuenta descartes |
| Métricas | Conjunto fijo de claves, sin etiquetas de provider/tenant/assessment; contadores saturan en 2^53-1 |
| Caché provider | 32 entradas por defecto; configurable 0..1024, sólo evidencia inmutable, nunca ERROR/UNKNOWN |
| Controles por request | 1..256 |
| Timeout provider | >0 y <=120 s, incluye cola; máximo de espera cancelada es el timeout solicitado |
| YAML de catálogo/cambio/monitores | 4 MiB; profundidad 64, 100,000 nodos expandidos y 128 aliases; ciclos rechazados |
| Texto/plan JSON/reporte de entrada | 16 MiB antes de parseo; parser Terraform mantiene sus límites propios |
| Kubernetes CLI | 4 MiB total; parser conserva límites adicionales de documentos/objetos/contenedores |
| Changed files | 3,000 nombres de hasta 4,096 caracteres; manifiesto 4 MiB e inspección local 32 MiB |
| Retry Zabbix | Existente 0..3 por llamada read-only; contador de intentos adicionales reales |

La memoria de caché depende del tamaño acotado del contrato y los controles, no sólo
del número de entradas; no configurar 1024 sin medir el workload. El runner serializa
por instancia, no limita el número de threads que crea el host. El host debe acotar
su pool (las pruebas usan ocho workers) y aplicar timeout duro de proceso. Python,
DNS o un adapter no cooperativo no pueden ser interrumpidos por este runner. No
reintentar escrituras de sinks con este mecanismo.

## Respuesta a incidentes

1. Conservar exit code, versión, digest de paquete aprobado y correlación. Validar el
   JSON operacional contra su schema. No copiar catálogos, planes, tokens o payloads
   a tickets de soporte. Los reportes legacy contienen datos del negocio y siguen
   requiriendo tratamiento privado.
2. TIMEOUT: reducir carga/pool o revisar deadline/latencia en sandbox autorizado.
   La espera del runner expira sin abrir el segundo provider. Terminar el proceso
   desde su supervisor si un adapter ignora deadlines; no publicar evidencia tardía.
3. AUTH: verificar privilegios y expiración con el propietario de credenciales fuera
   de los logs. No incrementar reintentos ante credenciales inválidas.
4. RATE_LIMIT/UNAVAILABLE: conservar resultado degradado, revisar límites externos y
   esperar antes de otro intento explícito. No reutilizar caché vencida como PASS.
5. INVALID_RESPONSE/MISSING/STALE: obtener evidencia válida en un contexto nuevo;
   nunca editar a mano el status para continuar. Conservar controles completados y
   hacer visibles los faltantes. No inferir cobertura de la mera existencia de un recurso.
6. Input excesivo: dividir por alcance de evaluación real y revisar completitud con
   un humano. No truncar silenciosamente ni elevar límites sin pruebas de carga.
7. Disco lleno/telemetría incompleta: código 2; liberar capacidad mediante el proceso
   de retención aprobado y repetir con un destino nuevo. No sobrescribir el artefacto.

## Retención, recuperación y soporte

No existe envío automático ni almacenamiento central. Política inicial: telemetría y
sondas locales durante **7 días**, sólo el operador; la sonda sintética de CI también
se retiene 7 días (los artefactos de seguridad mantienen sus 30 días). El operador aplica eliminación/retención según su política y
no interpreta la ventana de 256 eventos como retención temporal. La correlación y
assessment ID siguen siendo metadatos internos, no información pública por defecto.

Recuperación del CLI: reinstalar el wheel de una release verificada, verificar su
SHA-256 contra el manifiesto aprobado, ejecutar la sonda y repetir con los mismos
inputs, política, timestamps y digests aprobados conservados en almacenamiento privado.
La caché es descartable y se reconstruye; no es fuente de verdad. Si faltan inputs o
contexto, no hay replay fiel ni RPO recuperable: registrar evidencia incompleta. No se
promete RTO/RPO de un servicio inexistente. Cronómetros, UUIDs y latencias cambian;
los hashes de evidencia deben coincidir cuando el contexto semántico es idéntico.

```powershell
Get-FileHash -Algorithm SHA256 ./preflightops-<version>-py3-none-any.whl
python -m preflightops.operational_probe --iterations 100 --output recovery-probe.json
python -m pytest tests/test_operational_resilience.py tests/test_provider_runtime.py -q
```

Ejecutar las pruebas desde una copia de desarrollo con extras instalados. Para
rollback, retirar el flag de telemetría y revertir sólo etapa 16 por PR con CI verde.
Conservar las correcciones de seguridad de #53/#54 y archivos anteriores. La nueva
versión impone límites antes ausentes; si un workload válido los supera, medir y
evolucionar el contrato explícitamente en vez de usar una versión vulnerable.

Evidencia de implementación y riesgos: [verificación de etapa 16](STAGE16_VERIFICATION.md).
