# Unbidden: plan de producto, instalación y onboarding (CLI + dashboard)

Rama `feat/63-product-onboarding`, worktree `~/unbidden-ai-product`, cortada de `origin/main` (`d560b6f`). Nada de
esto está implementado; nada se ejecutó con modelos de pago. Escrito el 2026-11-01; las decisiones de la sección 8
están pendientes de respuesta de David antes de implementar.

## Contexto

0.9.0 quedó congelado como "candidato experimental" (D-063) y `main` ya contiene el motor más el workspace web
(PR #2, `d560b6f`). El siguiente trabajo es producto: que una persona instale Unbidden sin preparar un entorno de
desarrollo ni editar YAML, configure modelos y permisos, obtenga un primer resultado o un bloqueo explicado, abra
su dashboard y pueda detener y retomar sin perder configuración ni evidencia. Este plan clasifica lo que ya existe,
lo que falta y lo organiza en cinco entregas integrables. No fija v1.0 ni toca los criterios de `CAMPAIGN-v1.md`.

Restricciones de esta fase: sin PR, merge, tag, release ni deploy; no detener labs, contenedores ni corridas; no
tocar el checkout de otra sesión; el ledger de gasto nunca se reinicia; pruebas de inferencia pagada sólo
explícitas y presupuestadas.

---

## 1. Estado real de `main` (inspeccionado 2026-11-01)

| Hecho | Valor |
|---|---|
| `origin/main` | `d560b6f` (merge PR #2: 0.9.0 + web workspace); CI verde |
| Checkout `~/unbidden-ai` | rama `feat/18-runtime-truth` en `0f8bbc7`, limpio, 20 commits **detrás** de main. No se toca; es el checkout primario de otra sesión |
| Checkout `~/unbidden-ai-fe` | `feat/61-adaptive-workspace` en `e3245d4` (ya mergeado en main), limpio; corre `python -m unbidden.web --demo --record` (pid 29805, puerto 8765). No se toca |
| Procesos | Ollama servido (`muse-glimmer:30b-mxfp8-dflash` instalado); contenedores `hosli-*` (de David, ajenos); ningún `unbidden watch` |
| `~/.unbidden` | `.env`, `budget.yaml`, `budget-history.jsonl`, `e2e.lock`, `evidence-archive/`, sin `spend.db` visible en el listado (la ruta la decide `UNBIDDEN_HOME`) |
| GitHub | repo público, **sin tags ni releases**; único workflow `ci.yml` (uv sync, ruff, pyright, pytest, gitleaks); no construye el frontend |
| PyPI | `unbidden` y `unbidden-ai` libres (404) |
| Versión | `pyproject.toml` 0.9.0; `unbidden/__init__.py` dice `0.1.0` y `--version` lo imprime |
| Worktree de trabajo | se crea al aprobar: `~/unbidden-ai-product` en rama `feat/63-product-onboarding` desde `d560b6f` |

Lectura del código hecha sobre `git archive d560b6f` (snapshot en scratch), no sobre los checkouts.

---

## 2. Inventario reutilizable (archivo y símbolo)

Leyenda: **R** existe y se reutiliza · **P** existe parcialmente, necesita integración · **F** falta.
Columna "prueba": test existente por nombre; "verificado": ejercitado en una corrida real documentada.

### 2.1 Instalación y distribución

| Capacidad | Clase | Evidencia | Prueba / verificado |
|---|---|---|---|
| Paquete Python con entry point | R | `pyproject.toml` `[project.scripts] unbidden = "unbidden.cli:main"`, hatchling, `uv.lock` | CI `uv sync --frozen`; walk stage 9 (`docs/bench/stage9-walk/walk.sh`, 18/18 en macOS) |
| Ruedas nativas para macOS arm64 y Linux x86-64 | R | `uv.lock`: google_re2, scipy, psycopg_binary, pydantic_core, numpy con cp312 macosx_arm64 y manylinux_2_28 x86_64 | no verificado en Linux |
| Frontend precompilado en el wheel | F | `.gitignore` excluye `unbidden/web/static/`; `[tool.hatch.build.targets.wheel]` sólo `packages=["unbidden"]` (hatch omite lo ignorado por git); `server.py:39` `STATIC`, `:224-242` sirve página "run make web-build" si falta | — |
| Build del frontend | P | `Makefile` `web-build` (`npm ci && npm run build` → `frontend/vite.config.ts outDir ../unbidden/web/static`) | no en CI |
| Script de instalación, release, verificación de descargas, PATH, update, uninstall | F | no hay install.sh, Dockerfile, formula, publish ni workflow de release | — |
| `--version` correcto | F | `unbidden/__init__.py:3` `__version__="0.1.0"` | — |
| Diagnóstico de dependencias | P | `cli.py:1061-1133 cmd_doctor` (ollama, machine, local model, docker, meta api, github, mandate, repository, scope); exit 1 si falla ollama/local model/docker **siempre**, sin distinguir perfil | `test_doctor_meta.py` (listado), `test_prepare.py` (`diagnose`); `cmd_doctor` entero sin test |
| Elección y descarga del modelo local | R | `brain/hardware.py detect/recommend` (catálogos con GB), `cli.py:1125 --fix` hace `ollama pull` | `test_hardware.py` (3) |

### 2.2 Onboarding y configuración

| Capacidad | Clase | Evidencia | Prueba |
|---|---|---|---|
| Descubrir el repo y el workspace | R | `workspace.py:134 Workspace.find` (git toplevel), `:155 require`, `:138 init`, `:67 default_mandate` | `test_cli.py` (init) |
| Config por proyecto | R | `.unbidden/mandate.yaml` (`guardian/mandate.py load_mandate`), `.unbidden/config.yaml` (`config.py load_config`, `DEFAULTS :65-89`, `extra="forbid"`) | indirecta |
| Config por máquina | P | sólo `~/.unbidden/.env`, `budget.yaml`, `spend.db`, `web/` (`brain/spend.py:44 home()`, `UNBIDDEN_HOME`); no hay preferencias de máquina | `test_spend.py` |
| Credenciales por referencia y broker | R | `guardian/credentials.py CredentialBroker` (load/grant/get/leaked), `workspace.py:206 load_env` (`.unbidden/.env` luego `~/.unbidden/.env`), `runtime.py:57 _grant_model_keys` (auditoría sin valor) | `test_credentials.py`, `test_scanner.py`, `test_egress.py`, `e2e/test_secret_plant.py` |
| Entrada oculta y escritura segura de `.env` | F | ningún `getpass` de contraseña (sólo `getuser`); nada crea `~/.unbidden` ni fija modo 600 en `.env` (sólo `budget.yaml`, `spend.py:157`) | — |
| Redacción en logs/errores/auditoría | R | `store/sqlite.py` redacta todo con `guardian/scanner.redact_json`; `openai_compat.py:136` trunca errores; egress rechaza payload con secreto | `test_scanner.py` |
| Listado de modelos ≠ inferencia | R | `cli.py:1393 meta_api_status`: 401/403 → "calls may still work (see unbidden spend)" | `test_doctor_meta.py` |
| Asistente interactivo, reanudable, con diff y modo no interactivo | F | sólo `cmd_review` pregunta (`cli.py:352,357`) | — |
| Modos de autonomía | R | `cli.py:363 MODES` (supervised/autopilot/autonomous), `:392 _current_mode`, `:396 cmd_mode` (reescribe YAML, valida, evento `MANDATE_CHANGED` con actor `person:<user>`) | `test_cli.py:46` |
| Regla de autonomous | R | `cli.py:412-421`: exige `operations.deploy_steps` y kv `rollback_drill.passed` (escrito por `operate/deploy.py:136 drill`) | `test_cli.py` (rechazo); `drill()` sin test |
| Perfiles de modelos | P | `contracts/guardian.py:94 ModelsPolicy` (profile, private_code_to_frontier, screenshots_to_frontier, local_fallback, local_inference); `cli.py:958 cmd_models` sólo cambia profile y private_code | `test_router.py:297` (deny local_inference), `:204,220` (fallback) |
| Permisos efectivos | P | `guardian/policy.py:18 CAPABILITIES` (capacidad → campo de autonomía → red) y `:66 PolicyEngine.evaluate`; no hay vista "permisos efectivos" para una persona | `test_policy.py` (7) |
| Presupuesto | R | `brain/spend.py SpendLedger` (`status`, `reserve`, `_check_envelope`, `settle`), `Budget` (balance verificado, reserva, envelopes), `cli.py:1418 cmd_spend` (`--verified-balance`, `--amend-cap`, `--envelopes`), `budget-history.jsonl`; cap mensual por workspace `router.py ~550 month_remote_spend` | `test_spend.py` (17) |

### 2.3 Operación desde CLI

| Capacidad | Clase | Evidencia | Prueba |
|---|---|---|---|
| 34 subcomandos con `--json` | R | `cli.py:1609 build_parser`; 8 sin `--json` (approve-writes, watch, approve, review, probe, reject, kill, resume) | `test_cli.py` (4) |
| `unbidden` sin argumentos | F | `required=True` → argparse exit 2 | — |
| Ciclo de trabajo | R | `daemon/loop.py:72 watch` (`requeue_running`, hilo de probes, `_work`), `daemon/cycle.py` (`PRIORITY`, `TIMEOUT_S`, `retry_after`) | `test_daemon_limits.py` (7), `test_cycle.py` (5), `test_store.py:60` |
| Kill switch | R | `guardian/killswitch.py KillSwitch` (archivo `.unbidden/KILL`), `before_effect`, `kill_containers`; comprobado en loop, router y cada efecto | `test_daemon_limits.py`, `test_cli.py:38` |
| Único escritor del estado | P | asumido, no impuesto: `store/sqlite.py:3` "one process owns the file"; **sin** lock/pid; `requeue_running :278` roba jobs de un proceso vivo | — |
| Segundo plano, logs, stop/recuperación | F | `watch` sólo en foreground, logs sólo consola, sin pidfile | — |
| Estado y actividad | R | `cli.py:1368 cmd_status`, `:1571 cmd_activity` (`--html`), `director/activity.py build`, `cmd_errors`, `cmd_inbox`, `cmd_show`, `cmd_why` | `test_activity.py` |
| Aprobaciones | R | `cli.py:262 _approve`, `:290 _reject`, `cmd_review`, `guardian/approvals.py`, `connect/effects.py approve_writes` | `test_publish.py`, `test_send_time_authorization.py` |

### 2.4 Dashboard y chat

| Capacidad | Clase | Evidencia | Prueba |
|---|---|---|---|
| Servidor local seguro | R | `web/server.py` (`_guard :206`: Host, Origin, bearer token; CSP; 2 MB; `free_port :733` nunca mata procesos), `web/__main__.py build/main` (`--workspace`, `--record`, `--demo`, `--planner`, `--state-dir`, `--token`) | `tests/web/test_server.py` (9) |
| Lectura del motor sin escribir | R | `web/reader.py ReadOnlyStore` (`mode=ro`, sin migraciones), `web/sources.py live/historical/demo`, `Provenance` con `mode/freshness` | `test_sources.py` (7) |
| Persistencia de canvas y conversación | R | `web/presentation.py PresentationStore` (`~/.unbidden/web/presentation.db`: layouts, pointer, messages), `frontend/src/data/store.ts` (guardado con `base_version`, 409 recarga) | `test_server.py:107`, Playwright reload |
| Reabrir sin llamar al modelo | R | `store.ts:191 loadPresentation`: `compose(summary)` determinista sólo si el layout está vacío; el modelo sólo en `sendChat` | Playwright "reload keeps the space" |
| Eventos en vivo | R | SSE `server.py:433 _event_iter` (hello/engine/stale/recovered/heartbeat/closed), `sse.ts` reconexión | `test_server.py:148`, `test_sources.py:116` |
| Chat con herramientas | R | `web/chat.py ChatService.turn :895`, `TOOLS :128` (inspect_data, create_widget, update_widget, connect_widgets, undo_presentation, explain), `RulePlanner :571`, `BrainPlanner :803` | `tests/web/test_chat.py` (10, mock provider) |
| Chat por Meta API | F | `web/__main__.py:46 make_brain_for` exige Ollama y cachea `None` para siempre; `web.chat` no está en `brain/tasks.py TASKS` → siempre LOCAL; resultados con `source="runtime"` → PRODUCTION_DATA; no se llama `load_env` (sin clave) | — |
| Gasto del chat en el mismo cap | P | ledger de máquina compartido (`SpendLedger()`), pero cap mensual del workspace calculado por Store y el Brain web usa `~/.unbidden/web/<src>-state.db` | — |
| Acciones desde la UI | P | `web/actions.py`: kill/resume/evaluate; approve/reject/deploy/rollback → `not_supported_here` + comando CLI | `test_sources.py:116` |
| `unbidden ui` | F | ningún comando importa `unbidden.web` (propuesto en `docs/frontend/BASE.md`) | — |
| Demo / histórico / live diferenciados | R | `sources.py` mode y freshness; eventos demo con `payload.demo=True`; devseed marcado en `notes` | `test_sources.py` |

### 2.5 Pruebas y recursos

| Recurso | Dónde |
|---|---|
| Harness CLI | `tests/unit/test_cli.py` (fixture `repo` con git init + `main([...])`) |
| Aislamiento de HOME | `tests/conftest.py:28 spend_home` (`UNBIDDEN_HOME` temporal), reset del broker `:19` |
| Mock de proveedor | `tests/web/test_chat.py:158 MockProvider`, `tests/unit/test_router.py` |
| Walk limpio | `docs/bench/stage9-walk/walk.sh` (HOME vacío, clone HTTPS, sólo comandos documentados) |
| Commits fijados | `bench/repos/level-a.yaml`: full-stack-fastapi-template `104feb42`, rich `9d8f9a37`; `bench/repos/campaign-v1.yaml`: conduit `029eb778` |
| Labs por identidad | `bench/ecosystem/*_lab.py` (`unbidden.lab.id=<lab>`), D-054 |

---

## 3. Recorrido propuesto del usuario

```
curl -LsSf <URL de release, aún no publicada> | sh     # instala uv si falta, Python 3.12 gestionado, unbidden
cd mi-repo
unbidden                                             # primera vez: asistente; después: pantalla de estado
```

Asistente (`unbidden setup`, mismo que la primera ejecución), determinista, sin tokens, reanudable:

1. **Proyecto**: `Workspace.find`; muestra repo, rama, head, y el diagnóstico `observe/scope.py diagnose`
   (dentro/fuera del soporte declarado, con causa). Si no es git o no es Python en raíz: lo dice y sigue sólo con
   lo que puede (estado vacío explicado).
2. **Prioridades**: lista de valores (correctness, performance, consistency…) → `mandate.priorities`.
3. **Modelos**: tres opciones visibles → `ModelsPolicy`:
   Local = `profile: local`; Mixto = `local-first` (explica que lo pesado puede ir primero a remoto y vuelve local
   si falla, `local_fallback`); Solo API = `frontier` + `local_inference: deny` + `local_fallback: deny`.
   Muestra qué hardware detecta (`hardware.detect/recommend`) y, si la opción necesita Ollama, el tamaño del
   modelo (GB del catálogo) antes de ofrecer descargarlo; nunca descarga sin confirmar. Solo API no exige Ollama.
4. **Credenciales**: `MODEL_API_KEY` (y `GITHUB_TOKEN` si se quieren PRs) con entrada oculta; se guardan en
   `~/.unbidden/.env` (máquina) con modo 600 preservando otras claves; comprobación gratuita por listado
   (`meta_api_status`) explicando que un 401 del listado no implica fallo de inferencia; prueba pagada de una
   llamada sólo si la persona la pide, con el coste máximo mostrado (`SpendLedger.worst_cost`) y a través de Brain.
5. **Autonomía y alcance**: modo (`MODES`, misma semántica), más los permisos que el modo no cubre
   (`act_on_connections`, `provision_dependencies`, `delegate_synthetic`). Tabla de permisos efectivos derivada de
   `PolicyEngine.evaluate` sobre `CAPABILITIES` (observación, experimentos, dependencias, nuevas capacidades, PR,
   merge, deploy, rollback, escrituras en conexiones). Si pide autonomous sin `deploy_steps` o sin drill: explica
   lo pendiente y deja una configuración válida (autopilot o supervised) con el camino para completarlo.
6. **Conexiones opcionales**: postgres / http_api con `credential_ref` (la credencial va a `.unbidden/.env` del
   proyecto, modo 600); permisos `read` por defecto; `environment` staging por defecto; producción nunca se escribe.
7. **Presupuesto**: muestra `SpendLedger.status` (cap de máquina, gastado, disponible, envelopes) y pide el cap
   mensual del proyecto (`maximum_monthly_spend_usd`). Explica que créditos del proveedor ≠ presupuesto autorizado;
   el balance verificado se introduce con `unbidden spend --verified-balance` (nunca se reinicia).
8. **Dashboard**: habilitar ahora (`unbidden ui`) o después.
9. **Resumen efectivo** y **diff** del mandato antes de escribir; evento `MANDATE_CHANGED`.
10. **Primer ciclo**: propone `unbidden start` (segundo plano) o `unbidden scan` (un ciclo en foreground).

Después: `unbidden` muestra estado, actividad reciente, bloqueos y siguiente acción, si el agente corre (pid), si
el kill switch está activo, URL del dashboard si está abierto. `unbidden stop` termina el proceso sin tocar el KILL;
`unbidden kill` engancha el KILL (semántica existente); cerrar terminal o dashboard no detiene nada; `unbidden start`
retoma (`requeue_running`). Configuración posterior: `unbidden setup <sección>` o los comandos técnicos existentes.

Separación máquina / proyecto: `~/.unbidden/{.env,budget.yaml,spend.db,machine.yaml,web/}` vs
`<repo>/.unbidden/{mandate.yaml,config.yaml,.env,state.db,KILL,artifacts/,agent.pid,logs/,ui.json}`. Ningún permiso
se hereda entre proyectos (ya es así: `AutonomyPolicy` deniega por defecto y `default_mandate` es por repo).

---

## 4. Arquitectura de integración mínima

Principio: el motor no cambia de forma; se añaden una capa de entrada (`unbidden` sin argumentos, `setup`, `home`),
una capa de proceso (`start/stop/status`, lock de ejecutor, `ui`), y tres ajustes pequeños dentro del motor
(cap mensual desde el ledger, dos propósitos de chat, decisiones en un módulo neutral).

### 4.1 Un único ejecutor del estado (lock del motor)

Hechos: `Store.__init__` siempre ejecuta `_migrate` (`store/sqlite.py:117-130`), que escribe `PRAGMA user_version`;
los comandos "de lectura" abren hoy una conexión rw y SQLite los serializa con su timeout de 5 s. El loop ya abre una
segunda conexión en el mismo proceso para los probes (`loop.py:42`). El riesgo real no es la escritura SQL sino dos
**ejecutores**: `requeue_running` (`sqlite.py:278`) roba jobs RUNNING de un proceso vivo; dos `_probe_forever`; `try`,
`scan`, `deploy`, `drill`, `map`, `forge build`, `probe`, `investigate` ejecutan labs y efectos en proceso mientras un
`watch` puede ejecutar el mismo tipo de job.

Diseño: lock de **ejecución de jobs**, no de decisiones.
- `unbidden/daemon/owner.py` (nuevo): `EngineLock.acquire(state_dir, command)` con `fcntl.flock(LOCK_EX|LOCK_NB)`
  sobre `.unbidden/engine.lock` y contenido JSON `{pid, host, started_at, command, version}`; `holder()` (prueba no
  bloqueante) y `last()` (contenido aunque esté libre). flock lo libera el kernel al morir el proceso: "obsoleto" =
  archivo con contenido y lock adquirible, sin heurísticas de pid reutilizado. (No vale en NFS; el workspace es un
  checkout local por diseño.) `EngineBusy(WorkspaceError)` → `main()` ya lo imprime con exit 2 (`cli.py:1731`).
  Mensaje exacto: `another unbidden is working in this workspace: pid N (unbidden watch, started …, host …).
  See it: unbidden status · stop it: unbidden stop`.
- Toman el lock: `watch`/`start`, `try`, `scan`, `deploy`, `drill`, `map` (sin `--cached`), `forge build|stats`,
  `probe`, `investigate`. Un helper `_own(ws, command)` en `cli.py` antes de `Runtime.open`.
- No lo toman (decisiones cortas en transacción, coexisten hoy con `watch` por diseño: "opens on the next cycle",
  `cli.py:317`; el loop relee el mandato cada tick): `approve`, `reject`, `review`, `approve-writes`, `mode`,
  `models`, `hold release`, `forge approve|disable`, `init`, `kill`, `resume`.
- Sólo lectura en intención: `status`, `inbox`, `show`, `why`, `egress`, `activity`, `deploys`, `decide`, `logs`,
  `errors`, `connections`, `health`, `doctor`, `route`, `spend`. Endurecimiento opcional posterior: abrirlos con
  `web/reader.py ReadOnlyStore` cuando `state.db` existe (quita la escritura de `user_version`); no requerido.
- Carrera conocida que se registra y no se arregla ahora: `_reject` hace read-modify-write fuera de transacción
  (`cli.py:290-306`); seguimiento: `Store.update(collection, id, fn)` dentro de `transaction()`.
- `requeue_running` queda igual: con un solo ejecutor garantizado es correcto por construcción.

### 4.2 Segundo plano: `start` / `stop` / `status`; `kill` intacto

- `unbidden/daemon/service.py` (nuevo). `start [--interval S] [--ui]`: si `holder()` existe → "already running:
  pid N (log …)". Si no, `Popen([sys.executable, "-m", "unbidden.cli", "watch", …], cwd=repo, stdin=DEVNULL,
  stdout=append .unbidden/logs/agent.log, stderr=STDOUT, start_new_session=True)`; espera `holder()` ≤ 5 s; si el
  hijo muere antes, imprime la cola del log y devuelve 1. Rotación por renombre >20 MB. Nada secreto en argv ni env:
  el hijo carga `.env` en el broker él mismo (`workspace.py:206`).
- Parada limpia: un `stopping: asyncio.Event` en `loop.watch/_work/run_job` (`loop.py:72-98, 146-209, 114-136`)
  activado por SIGTERM/SIGINT; en `_work` el `sleep(interval_s)` pasa a `wait_for(stopping.wait(), interval_s)`; en
  `run_job` el poll de 1 s trata `stopping` como el kill switch (`scope.cancel` → `kill_containers` → `Stopped`),
  y en `_work` el job cancelado por parada no consume intento y vuelve a la cola (`attempts -= 1`, `retry_in=0`,
  mismo truco que `loop.py:202`). Segundo SIGTERM: salida inmediata.
- `stop [--timeout 60]`: SIGTERM, espera, SIGKILL con aviso ("N job(s) left running; they resume on the next
  start"). **Nunca toca `KILL`.**
- Semántica explícita (help y README): `KILL` = congelar (ningún job, efecto ni llamada a modelo; persiste entre
  reinicios hasta `resume`; cualquier proceso lo respeta). `stop` = el proceso termina limpiamente, nada queda
  congelado. `start` tras `kill` arranca pero espera ("kill switch engaged; waiting", `loop.py:174`). Se añade
  `kill --stop` para además terminar el proceso; `kill` solo sigue igual.
- `status` amplía `cmd_status` (`cli.py:1368`): `agent: running pid N since …, log …` / `not running` / `not
  running; the last run (pid N) ended without 'unbidden stop'; K job(s) resume on start` (K = jobs RUNNING), más
  `dashboard: <url>` si `ui.json` está vivo y la línea de kill switch que ya tiene; `--json` con `agent` y
  `dashboard`.
- Cerrar terminal ≠ detener: `start_new_session` desacopla del TTY (sin SIGHUP). Cerrar dashboard ≠ detener: la UI
  es otro proceso o un hilo daemon; nadie observa desconexiones del navegador.

### 4.3 Acciones desde la UI hacia el proceso dueño, sin segundo ejecutor

Opciones evaluadas: (a) tabla `commands` en `state.db` escrita por la web: cola que nadie consume con el agente
parado, un lector diseñado read-only pasa a escribir, y duplica lo que ya expresan los registros (una aprobación +
un job `github.publish` **es** el comando) → rechazada. (b) socket/HTTP en el daemon: protocolo y auth nuevos, y la
aprobación sólo funcionaría con el daemon vivo, contra la promesa del CLI ("opens on the next cycle") → rechazada
para decisiones. (c) servidor web dentro del daemon (`start --ui`): un proceso, un puerto, y el chat usa
`runtime.brain` con el store del motor (egress y `model_runs` unificados) → **adoptada para el ciclo de vida**;
pero en proceso no significa compartir la conexión del loop (ejecuta `BEGIN IMMEDIATE…COMMIT`, `sqlite.py:132`):
las acciones abren su propia conexión corta (precedente `loop.py:42`).

Recomendación: **(c) para el ciclo de vida; las decisiones por un módulo neutral con conexión rw corta**, usado
igual por la UI independiente, la UI en el daemon y el CLI.
- `unbidden/operate/decisions.py` (nuevo, sin importar web): `approve(ws, proposal_id, hours, by)`,
  `reject(ws, opportunity_id, reason, by)`, `approve_writes(...)`, `release_hold(...)`, `request_deploy(ws, ref,
  reason, by) -> Job`, `request_rollback(...)`. Cada una abre `ws.store()`, escribe en una `transaction()`, cierra.
  `cli._approve/_reject` (`cli.py:262-305`) pasan a ser envoltorios finos; sus tests siguen iguales.
- `web/actions.py`: para fuentes live, `approve|reject|approve_writes|deploy|rollback` llaman al módulo en vez de
  `not_supported_here`; conservan `expected_revision` (`actions.py:52-63`) e idempotencia (`:33-40`). Respuesta
  `effect="done"` con `detail`: "approved by <user>; the pull request opens on the agent's next cycle (agent: running
  pid N / not running: `unbidden start`)". Demo e histórico siguen `not_supported_here`.
- Deploy/rollback desde la UI son **solicitudes**, no efectos: encolan `ops.deploy` con `{commit, reason,
  requested_by, rollback}`; `Cycle.ops_deploy` (`cycle.py:829-848`, hoy sólo `origin/<base>`) aprende `payload.commit`
  y `payload.rollback` (`deploy(..., rollback=True)` ya existe, `operate/deploy.py:98`). El efecto corre bajo el lock,
  por `check()`/PolicyEngine y `before_effect` (`deploy.py:47-57, 103`). Punto a verificar al implementar: si
  `check()` consulta `approvals.find_valid` para `deploy.run` bajo `require_approval`; si no, `request_deploy`
  concede una aprobación acotada y `check` la consume, como `github.publish`.
- **Entra en esta entrega**: approve, reject, approve_writes, kill/resume, evaluate. **Queda pendiente y se dice en
  la UI**: deploy y rollback (botón → solicitud encolada sólo si David lo decide; por defecto siguen mostrando el
  comando CLI). El SSE ya emite `approval.granted`, `proposal.published`, `operations.deployed`; `summary` gana
  `agent: {running, pid, started_at, log}` (`sources.py:271`) para que la UI diga "agent not running" junto al botón.

### 4.4 Dashboard: `unbidden ui`, puertos y ciclo de vida

- Archivo de descubrimiento `.unbidden/ui.json` `{url, host, port, token, pid, started_at, in_daemon}` modo 600,
  escrito por quien sirve la UI tras enlazar el puerto (`python -m unbidden.web --announce <path>`, flag nuevo;
  el puerto puede diferir de 8765 por `free_port`, `server.py:733`), y por el daemon con `--ui`. Se borra al salir.
- `unbidden ui [--open] [--stop]`: lee `ui.json`; pid vivo y `GET /api/session` 200 con el token → reutiliza; si no,
  borra el archivo obsoleto y lanza `python -m unbidden.web --workspace <repo> --announce …` desacoplado (log
  `.unbidden/logs/ui.log`), espera el archivo, imprime la URL. El token nunca va en argv: lo genera el hijo.
- Puerto ocupado: `free_port` sigue (siguiente libre, nunca mata). Como la reutilización va por `ui.json`, un 8765
  ocupado es "servidor de otro", no el nuestro.
- `ui --stop`: SIGTERM al pid de `ui.json` salvo `in_daemon`, en cuyo caso: "the dashboard is served by the agent
  (pid N); `unbidden stop` stops both; closing the tab stops nothing". Nunca toca `engine.lock` ni `KILL`.
- `--ui` en el daemon: `App(sources=[live(repo)], ChatService, Actions(decisions))`, `WebServer.start()` (ya es hilo
  daemon, `server.py:724`), parada en el `finally` de `watch`; `brain_for` devuelve `runtime.brain`.
- Assets: incluidos en el wheel (entrega A); `server.py:224` ya sirve `unbidden/web/static/`.

### 4.5 Chat: informar / analizar / actuar, y la ruta a Meta por Brain

Bloqueo real hoy: no es sólo que falte `web.chat` en `TASKS`; el bucle del `BrainPlanner` adjunta los resultados de
herramientas con `source="runtime"` (`web/chat.py:870`) → `PRODUCTION_DATA` (`classify.py:28`) → `NEVER_REMOTE`
(`route_policy.py:16`, `router.py:404`). Tras el primer `inspect_data` toda la petición es local. Diseño: partir el
turno.
- **informar** (preguntas de datos, edición del canvas): reglas + `inspect_data`/`explain`; sin modelo o con el
  local bajo `chat.inform = TaskSpec("light", escalate=False, local_only=True)`. Los registros crudos siguen con
  `source="runtime"`: correcto, sin cambio.
- **analizar** (por qué, comparar, recomendar, riesgo, resumir): primero la lectura local; después **una** llamada
  sin herramientas con `chat.analyze = TaskSpec("heavy")` (frontier primero si el contenido puede salir; fallback
  local si `local_fallback: allow`). La petición lleva sólo: system prompt y mensaje del usuario (`source="prompt"`),
  el catálogo de datasets (ids y columnas, texto de Unbidden) y un **resumen de evidencia** producido por una función
  pura (conteos, medianas e IC, niveles, estados, títulos e ids; ≤ ~12 KB, bajo el tope de egress de 20 KB,
  `workspace.py:93`). Sin filas, sin líneas de log, sin payloads de eventos.
- **Etiqueta del resumen**: nuevo `Source` `"record"` (`contracts/llm.py:30`) clasificado como `"repo"`
  (`classify.py:63`): PUBLIC_CODE si GitHub confirmó público, PRIVATE_CODE si no; `_text_findings` puede subirlo a
  PRODUCTION_DATA/SECRET (emails, IPs, líneas de log, secretos). El resumen trata "sobre el código", así que sale bajo
  la misma regla que el código. No se cambia la clasificación de ningún dato para que una llamada funcione.
- Comportamiento por perfil para `chat.analyze`: Local → local (deny de inferencia local → `PolicyDenied`);
  Mixto en repo privado con `private_code_to_frontier: deny` → local ("private code leaves only renamed by the
  bridge"); Mixto en repo público → remoto primero, fallback local; Solo API → remoto, o rechazo con la razón del
  router, **nunca** respondido por reglas como si fuera análisis. Siempre pasa `_gate` (política
  `delegate_synthetic`, destinos, tope de payload, cap mensual, reserva en el ledger, registro de egress).
- **Decirlo al usuario**: en `ChatService.turn` (`chat.py:919-926`) `PolicyDenied | EgressBlocked |
  SpendLimitReached | KillSwitchEngaged` → "No puedo analizar esto con un modelo: <razón del router>. Lo permitiría:
  <pista>" (tabla razón → comando: `unbidden models local-first`, `unbidden spend`, `unbidden resume`…); la parte
  informativa del turno se narra igual. `ModelFailed | ProviderError` conservan el fallback a reglas con su sufijo.
  `ChatMessage` gana `route: {purpose, tier, model, reason, blocked}` (`web/contracts.py:245`, zod en
  `frontend/src/contracts/index.ts`, pill en `ChatPanel.tsx`).
- **actuar** (aprobar, rechazar, deploy, rollback, merge, kill, lanzar experimento): el chat lo **rechaza** con
  `ToolError(code="refused")` y señala el botón de acciones o el comando CLI; las acciones van por `Actions` →
  `operate/decisions` → PolicyEngine y aprobaciones. Preguntar "qué ocurre" nunca inicia experimentos.
- Paquete neutral `unbidden/chat/` (nuevo): `intent.py` (`classify_intent(text, selected)` ES/EN), `digest.py`
  (`evidence_digest(results)`, acotado, limpia patrones de `_text_findings` antes de etiquetar), `hints.py`.
  `web/chat.py` conserva `ToolRuntime/RulePlanner/BrainPlanner/ChatService` y llama al paquete. `unbidden chat`
  (terminal) construye `live(repo)` + `PresentationStore` bajo `~/.unbidden/web/` y usa el mismo `ChatService.turn`
  con `emit` a consola: un solo agente de decisiones, sin duplicar política.

### 4.6 `make_brain_for` y el cap mensual compartido

- `make_brain_for` (`web/__main__.py:46-89`): quitar la precondición de Ollama (el Brain ya decide `remote_available`
  por `has_key`, `router.py:166`, y descubre un local caído al llamar); para fuentes **live** llamar
  `Workspace(source.repo).load_env()` (la clave entra al broker y se concede para `model.remote`), nunca para
  demo/histórico; fijar `brain.repo_public` desde el kv `repo_visibility` cacheado (sin red); sonda de alcance de
  Ollama con TTL 30 s sólo para mostrar y para el planner `auto`; `route_info` (`sources.py:173`) expone
  `local.reachable` y `remote.key_present` (`broker().has`, nunca el valor) en vez de "existe el archivo". Sin modelo
  alcanzable: `planner="rule"`, `route.blocked` con la razón, y el sufijo "para análisis: `unbidden doctor --fix` o
  configura la clave".
- Cap mensual: `Brain.month_remote_spend` (`router.py:550`) suma `model_runs` de **su** Store, así que un Brain con
  otro store cuenta aparte. Cambio mínimo correcto: `SpendLedger.workspace_month_spend(workspace, now)` sobre
  `requests` (ya tiene columnas `workspace`, `purpose`, `created_at`, `spend.py:97-116`; `reserve` ya escribe
  `workspace=mandate.workspace`, `router.py:374`), contando reservas en vuelo (más estricto: lo desconocido no es
  gratis); `month_remote_spend` delega en él, misma firma y mismo sitio de llamada (`router.py:358`);
  `test_router.py:145` sigue pasando. Así dos procesos o dos bases no pueden partir el cap. Salvedad: `workspace` es
  el nombre del repo (`workspace.py:71`), dos repos homónimos comparten cap; se documenta.
- UI independiente: sus `model_runs`/egress quedan en `~/.unbidden/web/<src>-state.db` (no aparecen en `unbidden
  egress`); por eso el camino de producto para workspaces live es la UI en el daemon. Seguimiento: `cmd_egress` y
  `activity` leen también esos archivos en modo ro.

### 4.7 Lo que el motor ya impone y lo que esta entrega añade (alcance)

Ya impuesto: todas las capacidades de `CAPABILITIES` por `PolicyEngine` en `publish/github.py`, `operate/deploy.py`,
`sandbox/provision.py`, `connect/effects.py`, `router._gate`, `forge/logs.py`; `NEVER_REMOTE` en ruta y en envío;
deny de inferencia local y de fallback; kill switch antes de cada efecto y llamada; cap de máquina con reserva
previa; límites de escritura por conexión; producción nunca se escribe. Declarado sin imponer (no se promete):
`RemoteModelPolicy.max_tokens_per_call`; el drill sólo se comprueba al cambiar de modo, no en cada deploy (se
registra como seguimiento, sin cambiarlo aquí); revocación de aprobaciones (no existe; sólo expiran). Añadido por
esta entrega: un solo ejecutor por workspace; cap mensual común entre procesos; `act` rechazado en chat.

---

## 5. Entregas y dependencias

### A. Distribución instalable y frontend empaquetado

**Para el usuario**: una línea instala `unbidden`; el dashboard viene dentro; `unbidden update` actualiza;
desinstalar conserva `~/.unbidden` y `.unbidden/`.

**Reutiliza**: pyproject/hatchling, `uv.lock`, `make web-build`, `server.py STATIC`, `uv tool`.

**Cambios mínimos**:
- `pyproject.toml`: `[tool.hatch.build.targets.wheel] artifacts = ["unbidden/web/static/**"]` (hatch incluye
  artefactos aunque estén en `.gitignore`); `[tool.hatch.build.targets.sdist]` igual.
- `unbidden/__init__.py`: `__version__` desde `importlib.metadata.version("unbidden-ai")`.
- `.github/workflows/release.yml` (nuevo): en `workflow_dispatch` y en tag `v*`: `npm ci && npm run build`,
  `uv build`, `sha256sum` → `SHA256SUMS`, sube wheel+sdist+sums+`install.sh` como artefactos; **publicar la
  release sólo en el disparo por tag** (fuera de esta fase; aquí se valida el `workflow_dispatch` que no publica).
- `install.sh` (nuevo, en la raíz): detecta `darwin/arm64` y `linux/x86_64` (otros: mensaje y salida); instala `uv`
  con su instalador oficial si falta (pregunta, salvo `--yes`); `uv python install 3.12` gestionado; descarga el
  wheel de la versión fijada (`UNBIDDEN_VERSION`, por defecto la última release) y `SHA256SUMS`, verifica;
  `uv tool install --python 3.12 --reinstall ./unbidden_ai-X.Y.Z-py3-none-any.whl`; PATH: `uv tool update-shell`
  o instrucción por shell (zsh/bash/fish); idempotente; `--version X` permite volver atrás ante una actualización
  fallida (datos intactos). Variable `UNBIDDEN_INSTALL_BASE` para apuntar a un servidor local en pruebas.
- `unbidden update` (nuevo, `cli.py`): ejecuta la misma lógica (`uv tool install` de la versión pedida tras
  verificar hash); `unbidden uninstall` imprime/ejecuta `uv tool uninstall unbidden-ai` y **no** borra datos salvo
  `--purge` confirmado.
- Doctor por perfil (ver B) para que Ollama/Docker sean obligatorios u opcionales según lo elegido.

**Separación explícita en docs y en `doctor`**: (1) instalar Unbidden (wheel, sin Docker/Ollama); (2) preparar
dependencias de funciones (Docker para el sandbox y los checks; Ollama para perfiles con inferencia local; token de
GitHub para PRs); (3) el código del proyecto corre sólo en el sandbox existente (`sandbox/provision.py`).

**Archivos**: `pyproject.toml`, `unbidden/__init__.py`, `install.sh`, `.github/workflows/release.yml`, `Makefile`
(`dist` target), `cli.py` (update/uninstall), `docs/INSTALL.md` (nuevo), `README.md` (sección Install).

**Pruebas y aceptación**: `uv build` produce un wheel que contiene `unbidden/web/static/index.html`; `uv tool
install` del wheel en un `UNBIDDEN_HOME`/HOME temporal deja `unbidden --version` = versión del wheel y `unbidden ui`
sirve el frontend sin Node; `install.sh` contra un `python -m http.server` local con hash correcto instala, con hash
alterado se niega, repetido no cambia nada; Linux x86-64 real en GitHub Actions (`ubuntu-latest`) ejecutando
`install.sh` + `unbidden doctor --json`; macOS arm64 nativo en esta máquina con HOME vacío. **Limitación**: una VM
OrbStack x86-64 en Apple Silicon es emulación (Rosetta); se declara así; la prueba autoritativa de Linux x86-64 es el
runner de Actions. No existe URL pública: el one-liner se documenta como "disponible cuando exista la primera
release", no como funcional.

**Costo/riesgo**: US$0 en modelos. Riesgos: `requires-python <3.13` obliga a Python gestionado por uv (uv lo
descarga, ~30 MB, se explica); glibc ≥ 2.28 por las ruedas manylinux_2_28; tamaño del wheel con scipy (se mide).

### B. Onboarding sobre mecanismos existentes

**Para el usuario**: `unbidden` la primera vez guía todo sin YAML; se puede interrumpir y retomar; muestra el diff
antes de escribir; tiene forma no interactiva.

**Reutiliza**: `Workspace.init/default_mandate`, `MODES`, la regla de autonomous, `cmd_models`, `ModelsPolicy`,
`CredentialBroker`/`load_env`, `meta_api_status`, `hardware.recommend`, `SpendLedger.status`, `PolicyEngine`,
`diagnose`, `rich.prompt` (ya es dependencia).

**Cambios mínimos**:
- Extraer de `cli.py` funciones puras, sin cambiar comportamiento ni tests: `apply_mode(raw, mode) -> raw`,
  `autonomous_blockers(raw, store) -> list[str]` (de `cmd_mode :396-433`), `apply_models(raw, profile, **flags)`
  (de `cmd_models :958-990`), `record_mandate_change(store, before, after, actor)`. Nuevo módulo
  `unbidden/guardian/mandate_edit.py`; `cmd_mode`/`cmd_models` pasan a llamarlas.
- `unbidden/setup/` (nuevo): `wizard.py` (pasos, estado reanudable en `.unbidden/setup.json`, `--yes`,
  `--non-interactive` con flags `--models local|mixed|api --mode … --budget … --connection …`), `machine.py`
  (`~/.unbidden/.env` lectura/escritura preservando claves, modo 600, `machine.yaml` para preferencias: dashboard
  por defecto, idioma), `effective.py` (tabla de permisos efectivos vía `PolicyEngine.evaluate` sobre
  `CAPABILITIES`, también para `unbidden mode --json`), `diff.py` (diff YAML antes/después).
- `cmd_doctor`: recibe el perfil y las funciones elegidas; cada check lleva `required|optional|blocked`; exit 1
  sólo por obligatorios del perfil (Solo API: ollama/local model opcionales; Docker obligatorio sólo si se quieren
  checks/experimentos). Mantiene `--json`.
- `cli.py`: `command("setup", …)`; `unbidden` sin argumentos → `setup` si no está inicializado, si no → `home`.

**Archivos**: `cli.py`, `unbidden/guardian/mandate_edit.py`, `unbidden/setup/{__init__,wizard,machine,effective,diff}.py`,
`unbidden/workspace.py` (helper `env_write`), `tests/unit/test_setup_*.py`, `tests/unit/test_cli.py`.

**Pruebas y aceptación** (deterministas, sin modelo): el wizard no interactivo produce un mandato válido para
cada una de las tres opciones de modelos; Solo API da `frontier + deny + deny` y `doctor` no marca Ollama como
obligatorio; autonomous sin drill termina en configuración válida con mensaje; interrupción (excepción simulada en
el paso 4) y reanudación conservan respuestas; `.env` con claves previas conserva las otras y queda en 600; ningún
valor de credencial aparece en stdout, JSON, eventos ni auditoría (test que planta un secreto y escanea salidas);
`cmd_mode`/`cmd_models` siguen pasando sus tests tras la extracción. Costo US$0.

### C. Operación y ciclo supervisado desde CLI

**Para el usuario**: `unbidden` muestra estado y siguiente acción; `start`/`stop`/`status` en segundo plano con
logs; nunca dos agentes sobre el mismo workspace; locks obsoletos detectados; `kill` conserva su semántica.

**Reutiliza**: `watch`, `requeue_running`, `KillSwitch`, `cmd_status`, `director/activity.build`, `cmd_inbox`,
`cmd_errors`, `_approve/_reject`.

**Cambios mínimos** (detalle en 4.1-4.2): `unbidden/daemon/owner.py` (lock del escritor con pid/host/inicio,
detección de proceso muerto), `unbidden/daemon/service.py` (`start` desacoplado con `start_new_session`, stdout/err a
`.unbidden/logs/agent.log` con rotación, pidfile, `stop` con SIGTERM → drenaje existente), `cmd_home` (pantalla
por defecto), `cmd_start/cmd_stop`, `cmd_status` ampliado (proceso, lock, UI, kill switch). `watch` toma el lock;
`scan`/`try` lo toman mientras ejecutan; `approve/reject/mode/kill/resume` siguen siendo escrituras cortas en
transacción (no toman el lock de ejecución; justificación en 4.1).

**Archivos**: `unbidden/daemon/owner.py`, `unbidden/daemon/service.py`, `unbidden/daemon/loop.py` (evento
`stopping`), `unbidden/operate/decisions.py`, `cli.py` (`home`, `start`, `stop`, `status`, `_own`, `kill --stop`),
`tests/unit/test_owner.py`, `test_service.py`, `test_decisions.py`, `test_cli.py`.

**Pruebas**: segundo `watch` se niega con el pid del dueño; pid muerto → lock obsoleto recuperado y `requeue_running`
informado; `stop` termina sin crear `KILL`; `kill` crea `KILL` y el proceso en marcha deja de aceptar jobs
(`test_daemon_limits` ya cubre la parte del loop); logs observables; `status --json` expone `agent.pid/running`,
`lock`, `ui.url`. Costo US$0 (mock). Una corrida real acotada en la validación (sección 7).

### D. Dashboard y chat conectados al proyecto real

**Para el usuario**: `unbidden ui` abre el dashboard del repo actual sobre su `state.db` real, con eventos en vivo
del agente; el chat responde sobre los datos existentes sin gastar y, si está autorizado, pide análisis al modelo
por la ruta del mandato; las acciones operativas van al proceso dueño del motor.

**Reutiliza**: todo `unbidden/web` y `frontend/`; `Brain`, `SpendLedger`, `PolicyEngine`, `Actions`.

**Cambios mínimos** (detalle en 4.3-4.4): `cmd_ui` (arranca `unbidden.web` con `--workspace .`, escribe
`.unbidden/ui.json` {url, token, pid}, reutiliza si vive, `--stop` detiene sólo la UI); `make_brain_for` sin
precondición de Ollama, con `load_env` para fuentes live, reintento con TTL; `web.chat` en `brain/tasks.py` con la
política de contenido de 4.4; cap mensual compartido (4.4); clasificación informar/analizar/actuar en
`ChatService`; `unbidden chat` en terminal sobre el mismo `ChatService`; canal de acciones (4.3).

**Archivos**: `cli.py` (`ui`, `chat`), `unbidden/web/__main__.py` (`make_brain_for`, `--announce`),
`unbidden/web/chat.py`, `unbidden/web/actions.py`, `unbidden/web/sources.py` (`route_info`, `summary.agent`),
`unbidden/web/contracts.py` (`route`), `unbidden/chat/{intent,digest,hints}.py`, `unbidden/brain/tasks.py`
(`chat.inform`, `chat.analyze`), `unbidden/brain/spend.py` (`workspace_month_spend`), `unbidden/brain/router.py`
(`month_remote_spend`), `unbidden/contracts/llm.py` + `unbidden/guardian/classify.py` (`"record"`),
`frontend/src/contracts/index.ts`, `frontend/src/shell/ChatPanel.tsx`, `tests/web/*`, `tests/unit/test_spend.py`,
`test_router.py`, `test_route_policy.py`.

**Pruebas**: `tests/web` con una fuente live sobre un workspace escrito por el motor en el test (no sólo devseed);
chat por reglas sin modelo responde preguntas de datos; chat analyze con `MockProvider` pasa por `Brain._gate`
(reserva en el ledger temporal) y respeta `local_inference: deny` con un bloqueo explicado; `ui` sobre puerto ocupado
usa el siguiente sin matar nada; cerrar la UI no detiene el agente; Playwright existente sigue verde.
Costo US$0 salvo turnos reales acotados en la validación.

### E. Instalaciones limpias, documentación, landing y demo

`docs/INSTALL.md`, `README.md` (Install real), `docs/RELEASE.md` (corregir el punto 1c4cab7 → 0.9.0/`main`, el
`--json` que no es universal, la lista de comandos), `site/index.html` (CTA de instalación sólo cuando exista
release), `demo/` (guion del recorrido: instalar → setup → primer ciclo → dashboard → stop/start), D-064 en
`DECISIONS.md`. Walk limpio en macOS arm64 y Linux x86-64 con minutos y decisiones medidos (el formato de
`stage9-walk`). Costo: demo con modelo US$0.5-1.0.

**Dependencias**: A → D (assets en el wheel) y A → E; B → C (home y start usan el mandato del wizard) y B → D
(perfil decide la ruta del chat); C → D para el canal de acciones. **En paralelo sin conflicto**: A (pyproject,
install.sh, release.yml) con B (setup/, mandate_edit); C (daemon/owner, service) con D (web/, frontend) hasta el
canal de acciones, que se integra al final. E recoge.

---

## 6. Matriz de pruebas y repos fijados

Repos (commits de `bench/repos/*.yaml`, forks de satisfymath donde existen; sin PR a terceros):

| Repo | Commit | Para qué |
|---|---|---|
| Rich (fork satisfymath/rich) | `9d8f9a372cc5916fd4781fec207ced7ddac2f08f` | recorrido simple sin base de datos; probe de crashes |
| full-stack-fastapi-template (fork) | `104feb428128ba03c99a448f3bbcec9037f71004` | conexiones, PostgreSQL, experimentos; lab propio `unbidden.lab.id=product-fst` |
| Conduit | `029eb7781c60d5f563ee8990a0cbfb79b244538c` | compatibilidad y ciclo conocido; lab `product-conduit` |
| mínimo nuevo (`unbidden-hello`: pyproject + 1 test) | se crea en el test | onboarding y estados vacíos |

Recursos propios: HOME temporal por prueba (`UNBIDDEN_HOME`), labs con identidad `unbidden.lab.id=product-*`
levantados desde `bench/ecosystem/*_lab.py` con puertos distintos de los labs actuales; limpieza sólo por identidad.
Nunca se tocan `~/unbidden-lab/*` ni los labs existentes. Sin secretos personales: la clave se inyecta en el HOME
temporal sólo en las pruebas con modelo real.

Cobertura razonada (no cartesiana):

| # | Plataforma | Modelos | UI | Instalación | Repo | Nivel |
|---|---|---|---|---|---|---|
| 1 | Linux x86-64 (Actions) | Solo API sin clave | sin | nueva | mínimo | determinista: install, setup --non-interactive, doctor, home, start/stop |
| 2 | macOS arm64 | Local (Ollama presente) | con | nueva | Rich | real acotado: un ciclo local, ui, chat informar |
| 3 | macOS arm64 | Solo API | con | nueva → actualización → reapertura | fst | real acotado: ciclo con experimento, dashboard live, stop/start, update conserva todo |
| 4 | macOS arm64 | Mixto | sin | reapertura | Conduit | real acotado: ciclo conocido, cmd chat analyze 2 turnos |
| 5 | Linux x86-64 (Actions) | Solo API con proveedor simulado | con (Playwright) | nueva | mínimo | integración simulada |
| 6 | macOS arm64 | cualquiera | con | nueva, persona nueva | Rich | recorrido completo medido en minutos y decisiones |

Casos de fallo (deterministas salvo indicación): Docker apagado (doctor: obligatorio sólo si se eligió sandbox;
mensaje); Ollama ausente en Solo API (no bloquea); credencial inválida (listado 401 explicado, inferencia falla con
`ProviderError` y bloqueo explicado, sin valor en logs); listado rechazado pero inferencia disponible (mock 401 en
`/models`, 200 en `/chat/completions`); presupuesto agotado (`SpendLedger.reserve` rechaza, el chat y el motor
muestran el bloqueo); onboarding interrumpido; puerto ocupado; proceso terminado (kill -9 al agente → lock obsoleto);
workspace ya administrado (segundo `start`); lectura parcial (`completeness` en los widgets); dashboard sin evidencia
(estados vacíos del compositor).

Separación: deterministas sin modelos (pytest, Actions) · integración con proveedor simulado (`MockProvider`,
Playwright) · acotadas con modelos reales (3 ciclos + ~6 turnos de chat) · recorrido completo con una persona nueva.
Son validación de producto, no evidencia fuera de muestra (los tres repos son de desarrollo).

---

## 7. Presupuesto estimado

| Partida | Modelo | Estimación |
|---|---|---|
| Implementación A-E | ninguno | US$0 |
| Validación determinista y simulada | ninguno | US$0 |
| Validación real acotada: ciclo Rich local | Ollama | US$0 |
| Ciclo fst Solo API (con experimento) | Spark | US$0.6-1.2 (registros stage 10: 0.3-1.2 por app) |
| Ciclo Conduit mixto | Spark+local | US$0.5 |
| Chat analyze, ~6 turnos | Spark | US$0.1-0.3 |
| Prueba pagada opcional del wizard, 3 veces | Spark | <US$0.05 |
| Demo grabada | Spark | US$0.5-1.0 |
| **Total** | | **US$1.8-3.1**, contingencia 25% → **≤ US$3.9** |

Disponible: US$9.5746 del cap 37.2945 (nunca se reinicia). Propuesta: envelope `s11-product` de US$4.00 tomado
de `s10-close` (3.80 sin gastar) + 0.20 de `s10-dev`, con `unbidden spend --envelopes` (decisión de David; sin
`--amend-cap`). Toda corrida real con `UNBIDDEN_ENVELOPE=s11-product`.

---

## 8. Decisiones que necesitan respuesta de David (cada una con un default)

1. **Canal de distribución**: GitHub Releases (wheel + SHA256SUMS + install.sh) como único canal ahora; PyPI
   (`unbidden-ai`, libre) como segundo canal más adelante. *Default: sólo Releases en esta fase; el tag/release en
   sí queda fuera y se decide aparte.*
2. **Opción de modelos por defecto** cuando hay clave y Ollama: *Default: Mixto (`local-first`), que es el default
   actual de `ModelsPolicy`.* Y si el wizard ofrece la prueba de inferencia pagada: *Default: sí, opt-in, con coste
   máximo mostrado.*
3. **Canal de acciones UI → motor** y qué controles entran: *Default (4.3): UI dentro del daemon con `start --ui`
   para el ciclo de vida; decisiones por `operate/decisions` con conexión corta desde cualquier UI; entran approve,
   reject, approve_writes, kill/resume; deploy y rollback quedan pendientes mostrando el comando CLI.* Alternativa:
   también encolar deploy/rollback como solicitudes (`ops.deploy` con `payload.commit/rollback`).
4. **Idioma de la interfaz**: el código, docs y CLI están en inglés; el `RulePlanner` del chat usa regex en español.
   *Default: CLI y wizard en inglés con textos centralizados (`unbidden/setup/text.py`) para traducir después; el
   chat por reglas acepta ambos idiomas.*
5. **Presupuesto**: envelope `s11-product` US$4.00 como arriba. *Default: esperar la orden antes de cualquier
   llamada.*
6. **Documentos compartidos**: `README.md`, `docs/RELEASE.md`, `docs/PLAN.md`, `docs/DECISIONS.md` los toca también
   la sesión del motor. *Default: esta rama crea `docs/PRODUCT-ONBOARDING-PLAN.md` y `docs/INSTALL.md`, añade D-064,
   y sólo edita README/RELEASE en la entrega E tras acordar quién los mantiene.*
7. **Linux**: *Default: GitHub Actions `ubuntu-latest` es la prueba autoritativa de x86-64; una VM OrbStack sólo
   si se quiere ver el recorrido interactivo, declarada emulada.*

---

## 9. Lo que NO hace falta reconstruir

Guardian (`PolicyEngine`, `AutonomyPolicy`, `ConnectionGrant`, aprobaciones, revocación, kill switch), `MODES` y la
regla de autonomous, `ModelsPolicy` y el router (`may_leave`, `decide_route`, `_gate`, deny de inferencia local y
de fallback), clasificación de contenido (`classify`, `NEVER_REMOTE`), `CredentialBroker` y la redacción,
`SpendLedger` con envelopes y `budget.yaml`, detección de hardware y catálogo de modelos, `meta_api_status`,
`diagnose`, el ciclo (`watch`, `cycle`, prioridades, timeouts, `requeue_running`), el store SQLite, `activity`,
el servidor web con sus guardas, el lector read-only, la persistencia del canvas y la conversación, el SSE, el
compositor determinista, los widgets, el inspector, el `ChatService` con sus herramientas y planners, el frontend
completo y sus pruebas, el walk de stage 9 como formato de medición, los labs por identidad.

---

## 10. Primera entrega propuesta: A + B en paralelo, C a continuación

Orden: (1) worktree `~/unbidden-ai-product` en `feat/63-product-onboarding` desde `d560b6f`, este documento como
`docs/PRODUCT-ONBOARDING-PLAN.md` y D-064; (2) **A**: pyproject artifacts, `__version__`, `release.yml` en modo
`workflow_dispatch` sin publicar, `install.sh` con pruebas contra servidor local, `update/uninstall`; (3) **B**:
extracción `mandate_edit.py` (tests actuales verdes), `setup/` con modo no interactivo primero y después el
interactivo, `doctor` por perfil, `unbidden` sin argumentos; (4) **C**. Nada se ejecuta con modelo hasta que la
decisión 5 autorice el envelope. Aceptación de la primera entrega: `uv build` con assets, `install.sh` local
idempotente y verificado, `unbidden setup --non-interactive` en los tres perfiles sin YAML, `make check` verde.

## Verificación (al implementar)

`make check` y `make web-check`; `uv build && unzip -l dist/*.whl | grep web/static/index.html`; en HOME vacío:
`install.sh` desde servidor local → `unbidden --version`, `unbidden setup --non-interactive --models api …`,
`unbidden doctor --json`, `unbidden`, `unbidden start`, `unbidden ui`, `unbidden stop`, `unbidden start`; Actions
`ubuntu-latest` con los mismos pasos; corridas reales sólo con el envelope autorizado.

---

## Estado 2026-11-01: entregas A y B hechas (commits locales, sin push)

Decisiones de David recogidas: Releases primero y PyPI después; elección explícita de modelos (se recomienda, nunca
se activa solo); UI en el daemon si conserva un único escritor, con approve/reject/approve_writes/kill-resume y
deploy/rollback como comando CLI; inglés con textos centralizados (`unbidden/setup/text.py`); envelope `s11-product`
US$4.00 reasignado desde `s10-close` (cap y total intactos); README/RELEASE/PLAN/DECISIONS sólo en la entrega E;
Linux validado en Actions x86-64 informando cuatro niveles por separado.

**A (distribución)**: `pyproject.toml` incluye `unbidden/web/static/**` en wheel y sdist; `__version__` desde los
metadatos instalados; `install.sh` (raíz y copia en `unbidden/distribution/`, idénticas por test) verifica SHA256 antes
de `uv tool install --python 3.12`, es idempotente, `--version` permite volver atrás, `--uninstall` conserva los
datos; `unbidden update` y `unbidden uninstall`; `make dist`; `.github/workflows/release.yml` sólo `workflow_dispatch`,
construye y prueba en `ubuntu-latest` sin publicar; `docs/INSTALL.md`. Verificado en esta máquina: wheel de 925 KB
con los cuatro assets del frontend, instalado desde un servidor local en un HOME vacío, `unbidden --version` 0.9.0, la
UI servida por el venv de la herramienta sin Node, suma alterada rechazada, desinstalación con `~/.unbidden` intacto.

**B (onboarding)**: `guardian/mandate_edit.py` (MODES, condiciones de autonomous, opciones de modelos, escritura
validada y atómica con `MANDATE_CHANGED`; `mode` y `models` lo usan); `unbidden setup` interactivo y
`--non-interactive` (local / mixed / api; api = frontier + local_inference deny + local_fallback deny y no exige
Ollama); credenciales por nombre en `~/.unbidden/.env` (600, conservando otras claves), listado gratuito explicado,
prueba pagada opt-in con coste máximo; autonomous explicado y degradado a una configuración válida; permisos
efectivos por `PolicyEngine`; conexiones; presupuesto con el ledger; diff antes de escribir; reanudable
(`.unbidden/setup.json`); `unbidden` sin argumentos abre el asistente o la pantalla de estado; `doctor` marca
obligatorio/opcional según la opción. `make check`: 886 tests.

**No validado**: URL pública (no hay release); el runner de Actions no se ejecutó (sin push); integración con Docker
más allá de `docker info`; ciclo con modelo real (gasto US$0; `s11-product` 0 de 4.00). Pendiente C (lock de
ejecutor, start/stop/status) y D (`unbidden ui`, chat, cap común, decisiones).

## Estado 2026-11-01 (tarde): entregas C y D hechas (commits locales, sin push)

Correcciones previas pedidas por David: (1) `autonomous` bloqueado ya no elige otro modo por nadie: en interactivo la
pregunta no tiene valor por defecto; en no interactivo hace falta `--mode-fallback supervised|autopilot` o el asistente
termina con exit 4, el mandato anterior intacto y los requisitos listados (`--yes` sólo confirma la escritura).
(2) Presupuesto: los US$0.20 tomados de `s10-dev` sin autorización registrada volvieron; `s11-product` = US$3.80
(lo autorizado desde `s10-close`); total de envelopes 20.30 y cap 37.2945 intactos; registrado en `budget-history`.

**C (operación real)**: `daemon/owner.py` (lock flock sobre `.unbidden/engine.lock` con pid/host/inicio/comando; el
kernel lo libera al morir el proceso: "obsoleto" = archivo con contenido y lock libre, sin heurísticas de pid;
`alive_holder` sólo devuelve un pid cuyo `ps` nombra unbidden, lo único que `stop` señala), `daemon/service.py`
(`start` desacoplado con `start_new_session`, log en `.unbidden/logs/agent.log` con rotación, `stop` SIGTERM → espera
el lock → SIGKILL con aviso de jobs que retoman, `status`), evento `stopping` en `daemon/loop.py` (el job en curso
vuelve a la cola sin gastar intento), `_own()` en `watch/scan/try/deploy/drill/map/forge build|stats/probe/investigate`
(exit 2 con el pid del dueño); las decisiones cortas (`approve/reject/mode/kill/resume…`) no toman el lock y el ciclo
las recoge. `kill --stop`. Nada arranca al encender la máquina ni instala servicios. Tests: `test_owner.py`,
`test_service.py` (procesos reales, kill -9, lock obsoleto recuperado), `test_daemon_limits.py`, `test_cli.py`.

**D (UI y chat sobre el mismo motor)**: `unbidden ui` (abre o reutiliza por `.unbidden/ui.json`, 600, token generado
por el hijo, nunca en argv; `--stop` sólo detiene la UI servida aparte; con KILL activo abre, lee y permite reanudar);
`start --ui` / `watch --ui` sirven el dashboard dentro del proceso del agente (`web/embed.py`, mismo Brain y store);
`operate/decisions.py` (approve/reject/approve_writes) compartido por CLI y `web/actions.py` sobre workspaces vivos
(deploy/rollback siguen nombrando el comando CLI); `make_brain_for` sin precondición de Ollama; la fuente viva carga
su `.env` al broker; `route_info` dice si hay clave (nunca el valor) y si el servidor local responde. Chat:
`unbidden/chat/{intent,digest,hints}.py`; informar (`chat.inform`, ligero, nunca sale; por reglas sin modelo o con
`local_inference: deny`), analizar (`chat.analyze`, una llamada sin herramientas sobre un digest acotado con la nueva
etiqueta `record`, clasificada como el código; rechazo con la razón del router y una pista, nunca respondido por
reglas), actuar (rechazado y señalado al panel o al CLI); cada mensaje lleva su `route`. Cap mensual:
`SpendLedger.workspace_month_spend` y `Brain.month_remote_spend` delegando en él (dos procesos o dos stores no pueden
partirlo; test en `test_spend.py`). `unbidden chat` en terminal. Frontend: ruta por mensaje, botones aprobar/rechazar
en tarjetas (sólo workspace vivo), clave cargada/servidor local en ajustes. CI: job `frontend` (lint, tipos, vitest,
build, Playwright) y job `installed` (wheel → install.sh en HOME vacío → setup api → doctor → start/status/stop →
ui/chat → uninstall). `make check` verde: 931 tests.

**Validación real acotada** (Meta API, envelope `s11-product`): ver la sección siguiente, escrita al terminar.
