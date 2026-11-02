"""Las frases del asistente de configuración y del home en español. Misma tabla de claves que `text.py`."""

from __future__ import annotations

T: dict[str, str] = {
    "welcome": "Unbidden aún no está configurado en este repositorio. Toma unos minutos y no llama a ningún modelo.",
    "resume": (
        "Retomando la configuración donde quedó ({done}); las secciones respondidas se conservan; `setup "
        "--all` las rehace."
    ),
    "found.title": "Encontrado",
    "found.repo": "repositorio {repo} · rama {branch} · head {head}",
    "found.repo.nocommit": (
        "repositorio {repo} · rama {branch} · sin commits todavía (los archivos compose se leen en HEAD)"
    ),
    "found.noremote": (
        "no hay un remoto de GitHub llamado origin: las propuestas quedan como ramas locales hasta que exista"
    ),
    "found.scope.ok": "dentro del alcance",
    "found.scope.no": "fuera de lo que esta versión soporta",
    "found.compose": "servicio de compose, leído por sí solo",
    "found.notgranted": "hallado en el env de compose, no autorizado",
    "found.connections": "conexiones, según lo confirmado en HEAD en {path}: {items}",
    "found.connections.none": "ninguna declarada",
    "found.connections.nocompose": "conexiones: no hay archivo compose en HEAD; `unbidden setup connections` añade una",
    "found.key": "clave de modelo {name}: {state}",
    "found.key.present": "guardada en esta máquina",
    "found.key.absent": "ninguna todavía",
    "found.github": "Acceso a GitHub: {source}",
    "found.github.file": "un token guardado para Unbidden",
    "found.github.env": "un token del entorno",
    "found.github.gh": "la sesión del CLI gh (retenida mientras Unbidden corre, nunca copiada)",
    "found.github.browser": "sesión iniciada en el navegador",
    "found.github.token": "un token que pegaste",
    "found.github.none": "ninguno: las propuestas quedan como ramas locales",
    "found.language": "Idioma: {name} ({how}); /language o `unbidden setup language` lo cambia",
    "github.ask": "¿Acceso a GitHub para los pull requests?",
    "github.browser": "browser: inicia sesión en GitHub desde el navegador (acceso completo al repositorio)",
    "github.token": "token: pega un token (de grano fino, este repositorio, contenidos y pull requests)",
    "github.skip": "skip: las propuestas quedan como ramas locales; `unbidden setup credentials` más tarde",
    "priorities.title": "Prioridades",
    "priorities.ask": "¿Qué debe buscar primero? (separado por comas; p. ej. correctness, performance, consistency)",
    "models.title": "Acceso al modelo",
    "models.key.why": (
        "Una clave de la API de Meta deja que el trabajo pesado vaya a la API de Meta (los secretos y los datos de "
        "producción nunca salen; el código privado solo renombrado por el puente de privacidad). Sin ella, solo "
        "funciona el modelo local."
    ),
    "models.key.ask": "{name} (oculta; Enter para omitir y usar solo el modelo local)",
    "models.key.skipped": "Sin clave. Más tarde: `unbidden setup models`.",
    "models.chosen": "opción de modelo: {option} ({why}); `unbidden setup models` la cambia",
    "models.why.flag": "elegida por --models",
    "models.why.mixed": "hay una clave y un modelo local",
    "models.why.api": "hay una clave y ningún modelo local instalado",
    "models.why.local": "hay un modelo local instalado y ninguna clave guardada",
    "models.why.none": "ni clave ni modelo local todavía",
    "models.none": (
        "Todavía no hay modelo: instala Ollama (ollama.com) y corre `unbidden setup models`, o añade una clave; "
        "`unbidden start` se niega hasta que exista uno."
    ),
    "models.hardware": "máquina: {described}",
    "models.local_model": "modelo local para esta máquina: {tag} ({reason}){installed}",
    "models.not_installed": " · no instalado",
    "models.pull.ask": "¿Descargar {tag} ahora? Unos {gb:.0f} GB en disco y en memoria mientras corre.",
    "models.pull.skip": "No descargado. Más tarde: `unbidden doctor --fix`.",
    "models.private_code.ask": (
        "¿Puede el código privado llegar a la API de Meta sin renombrar? (deny lo mantiene tras el puente)"
    ),
    "private_code.title": "Código privado",
    "credentials.title": "Credenciales",
    "credentials.where": (
        "Guardadas en {path} (modo 600), referidas por nombre; nunca escritas en el repositorio ni en registros."
    ),
    "credentials.have": "{name} ya está guardada. ¿Conservarla?",
    "credentials.ask": "{name} (oculta; deja vacío para omitir)",
    "credentials.saved": "{name} guardada.",
    "credentials.skipped": (
        "{name} sin definir: las llamadas remotas se rechazan hasta que la añadas (`unbidden setup credentials`)."
    ),
    "credentials.listing": "API de Meta: {detail}",
    "credentials.listing.note": (
        "Que el listado de modelos sea rechazado no significa que la inferencia falle (visto el 2026-10-29: /models "
        "respondió 401 mientras las llamadas funcionaban). La prueba pagada opcional de abajo las distingue."
    ),
    "credentials.probe.ask": (
        "¿Hacer una llamada de inferencia pagada para confirmar la clave? Como mucho US${cost:.4f} a precio de lista."
    ),
    "credentials.probe.ok": "La inferencia funciona: {model} respondió; coste US${usd:.4f} anotado en el libro.",
    "credentials.probe.fail": "La inferencia no funcionó: {why}",
    "credentials.probe.skip": "Omitida. La configuración se guarda igual.",
    "credentials.github.ask": "¿Debe Unbidden poder publicar pull requests? (necesita GITHUB_TOKEN)",
    "autonomy.title": "Autonomía y alcance",
    "autonomy.explain": (
        "Un modo fija qué llega a GitHub y a producción. Los demás permisos se conceden por separado y nunca se "
        "heredan de otro proyecto. Los poderes de una credencial nunca amplían el mandato."
    ),
    "autonomy.supervised": "supervised: lo prepara todo, pregunta antes de un pull request; nunca fusiona ni despliega",
    "autonomy.autopilot": "autopilot: abre pull requests por su cuenta para trabajo probado; las personas fusionan",
    "autonomy.autonomous": "autonomous: también fusiona trabajo L4, despliega con los pasos del equipo y vuelve atrás",
    "autonomy.ask": "¿Cuánto puede hacer Unbidden por su cuenta?",
    "autonomy.blocked": "autonomous aún no está disponible:",
    "autonomy.fallback": "¿Qué modo hasta entonces? (sin valor por defecto; nadie elige por ti)",
    "autonomy.fallback.chosen": "Hasta entonces: {mode}.",
    "autonomy.blocked.result": "bloqueado: {mode} aún no puede activarse y no se nombró otro modo",
    "autonomy.blocked.keep": (
        "Nada escrito; {path} conserva su configuración anterior. Nombra el modo a usar hasta entonces con "
        "--mode-fallback supervised|autopilot, o completa los requisitos de arriba."
    ),
    "autonomy.connections.ask": "¿Puede escribir a través de conexiones (acciones tipadas, limitadas y reversibles)?",
    "autonomy.effective": "Permisos efectivos",
    "connections.title": "Conexiones (opcional)",
    "connections.ask": (
        "¿Autorizar una conexión? (una hallada en compose, o una nueva postgres o http_api; none para terminar)"
    ),
    "connections.prefilled": "  {kind} {location}, desde los archivos compose; Enter conserva cada valor sugerido",
    "connections.id": "id de la conexión (p. ej. shop-db)",
    "connections.location": "ubicación (postgres: host:puerto/bd · http_api: http://host:puerto)",
    "connections.docs": "URL del documento OpenAPI (opcional)",
    "connections.username": "usuario de la base de datos (rol de solo lectura)",
    "connections.environment": "entorno (staging, development, production; production nunca se escribe)",
    "connections.credential": (
        "nombre de la credencial, p. ej. SHOP_READER_PW (el valor se pide después y queda en el proyecto)"
    ),
    "budget.title": "Presupuesto",
    "budget.ledger": (
        "Libro de la máquina: {reason}; permitido US${permitted:.2f} · gastado US${spent:.4f} · "
        "disponible US${available:.4f}"
    ),
    "budget.envelopes": "sobres: {envelopes}",
    "budget.explain": (
        "Los créditos del proveedor y el gasto autorizado son cosas distintas: el tope que una persona ingresó con "
        "`unbidden spend --verified-balance` es lo que esta máquina puede gastar; aquí nunca se sube ni se reinicia."
    ),
    "budget.ask": "Tope mensual para este proyecto (US$)",
    "dashboard.title": "Panel",
    "dashboard.explain": (
        "Abrir el panel, restaurar su disposición y mostrar registros no llama a ningún modelo; chatear o pedir un "
        "análisis sí puede."
    ),
    "dashboard.ask": "Panel: ¿abrirlo al terminar (now), más tarde desde el CLI (later), o nunca (never)?",
    "language.title": "Idioma",
    "lang.how.env": "por UNBIDDEN_LANG",
    "lang.how.saved": "guardado en esta máquina",
    "lang.how.locale": "por la configuración regional de la terminal",
    "lang.how.default": "el valor por defecto",
    "language.ask": "¿En qué idioma te habla Unbidden?",
    "summary.title": "Resumen",
    "summary.models": "modelos: {option} (perfil {profile}, código privado a la frontera: {private})",
    "summary.mode": "modo: {mode} · escrituras a través de conexiones: {connections}",
    "summary.budget": "tope mensual: US${budget:.2f}",
    "summary.credentials": "credenciales guardadas: {names}",
    "summary.github": "Acceso a GitHub: {source}",
    "summary.priorities": "prioridades: {names}",
    "summary.dashboard": "panel: {choice}",
    "summary.defaults": "sin preguntar, valores por defecto: {names} (`unbidden setup <sección>` cambia uno)",
    "summary.diff": "Cambios en {path}:",
    "summary.nodiff": "Sin cambios en el mandato.",
    "summary.apply": "¿Aplicar estos cambios?",
    "summary.dry": "Nada escrito. Vuelve a correr con --yes para aplicar.",
    "summary.written": "Mandato escrito y registrado (MANDATE_CHANGED).",
    "summary.cancelled": "Nada escrito; tus respuestas quedan en {path} para `unbidden setup`.",
    "next.title": "Siguiente",
    "next.scan": "unbidden scan        un ciclo en primer plano: mapa, las comprobaciones del proyecto, decisiones",
    "next.doctor": "unbidden doctor      qué funciona aquí y qué es opcional para la opción que elegiste",
    "next.home": "unbidden             el estado del proyecto, los bloqueos y la próxima acción",
    "next.ui": "unbidden ui          el panel",
    "home.title": "{repo} · head {head} · modo {mode} · modelos {profile}",
    "home.kill": "interruptor de emergencia activado: nada corre hasta `unbidden resume`",
    "home.opps": "oportunidades: {counts}",
    "home.scan.none": "sin escaneo todavía",
    "home.scan": "último escaneo: {when}",
    "home.spend": "gasto: US${spent:.4f} gastados en esta máquina · US${available:.4f} disponibles bajo el tope",
    "home.next": "siguiente: {action}",
    "home.agent.running": "agente: corriendo pid {pid} desde {since}, registro {log}",
    "home.agent.stopped": "agente: no está corriendo",
    "home.agent.stale": (
        "agente: no está corriendo; la última ejecución (pid {pid}) terminó sin 'unbidden stop'; "
        "{jobs} trabajo(s) se reanudan al arrancar"
    ),
    "home.commands": (
        "comandos: setup · doctor · scan · start · stop · status · inbox · activity · mode · models · spend · "
        "kill/resume · --json en cada uno"
    ),
    "home.unset": (
        "Aquí no hay espacio de trabajo todavía: corre `unbidden setup` (o `unbidden init` para los valores "
        "por defecto)."
    ),
    "home.nogit": "`unbidden` funciona dentro de un repositorio git: entra primero a tu proyecto.",
}
