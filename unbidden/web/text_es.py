"""Las frases del chat en español. Misma tabla de claves que `text.py`."""

from __future__ import annotations

T: dict[str, str] = {
    "tool.added": "añadido «{title}»",
    "tool.added.nodata": " (sin datos: {note})",
    "change.title": "título",
    "change.size": "tamaño",
    "change.data": "datos",
    "explain.opportunity": "{title}\n\n{summary}\n\nNivel L{level}, estado {status}. Decisión: {chosen} — {reason}.",
    "explain.noreason": "sin motivo registrado",
    "explain.verdict": "\nVeredicto: {outcome}; {reasons}",
    "explain.improved": "mejoró",
    "explain.notimproved": "sin mejora",
    "explain.blocked": "\nBloqueado: {why}",
    "explain.history": "\n\nHistorial: {items}",
    "explain.block": (
        "Bloqueo ({kind}) en «{operation}».\n\nEvidencia: {evidence}\n\nLo mínimo que lo desbloquea: {needs}.\n"
        "Al darlo continúa: {continues}."
    ),
    "explain.experiment": (
        "Experimento {id} sobre «{title}»: {sessions} sesiones, {control} de control, {confirmation} de "
        "confirmación; coste US${usd:.4f}."
    ),
    "explain.experiment.verdict": "\nVeredicto: {outcome} (L{level}): {reasons}",
    "rule.undo": "Deshago el último cambio del lienzo.",
    "rule.select.rename": "Selecciona la tarjeta que quieres renombrar.",
    "rule.rename": "Cambio el título.",
    "rule.select.resize": "Selecciona la tarjeta cuyo tamaño quieres cambiar.",
    "rule.resize": "Cambio el tamaño.",
    "rule.nochart": "No hay ningún gráfico en el lienzo ni seleccionado que pueda cambiar.",
    "rule.chart.kind": "Cambio «{title}» a {kind}.",
    "rule.compare.need": (
        "Para comparar necesito dos ejecuciones compatibles seleccionadas (dos tarjetas de experimento o de "
        "hallazgo con experimento). Ahora mismo tengo {n}."
    ),
    "rule.compare": "Comparo las sesiones de {a} y {b}: medianas por brazo y posición.",
    "rule.compare.title": "Comparación · {a} vs {b}",
    "rule.noexperiment": (
        "No hay ningún experimento con muestras en este espacio: nada que graficar. Cuando el motor ejecute uno "
        "(`unbidden try <oportunidad>`), podré mostrar sus latencias."
    ),
    "rule.latency.title": "Latencia antes y después · {title}",
    "rule.latency": "Grafico las muestras de latencia del experimento {id} por brazo.",
    "rule.failed.tests": "Añado una tabla con los tests que fallaron en alguna ronda.",
    "rule.failed.tests.title": "Tests que fallaron",
    "rule.noblock": "No hay ningún bloqueo registrado en este espacio.",
    "rule.block.map.title": "Dependencias del bloqueo",
    "rule.block.map.label": "depende de",
    "rule.explain.block": "Explico el bloqueo{more}",
    "rule.explain.block.map": " y añado sus dependencias al mapa.",
    "rule.opportunities": "Añado una tabla con las oportunidades.",
    "rule.opportunities.title": "Oportunidades",
    "rule.explain.selected": "Explico lo seleccionado.",
    "rule.select.explain": (
        "Selecciona una tarjeta (hallazgo, experimento, bloqueo) y te la explico con sus referencias."
    ),
    "rule.unknown": (
        "No he entendido la petición. Puedo: graficar la latencia antes y después de un experimento, añadir una "
        "tabla con los tests que fallaron, graficar el gasto por corrida, explicar un bloqueo y añadir sus "
        "dependencias al mapa, cambiar un gráfico a barras/líneas, comparar dos ejecuciones seleccionadas, "
        "renombrar o redimensionar una tarjeta, y deshacer la última tarjeta."
    ),
    "status.line": (
        "Registro de {name} ({mode}, head {head}): {opportunities} oportunidades, {experiments} experimentos, "
        "{proposals} propuestas, {events} eventos, {model_runs} llamadas a modelos, {blocks} bloqueos."
    ),
    "status.jobs": "Jobs: {jobs}",
    "status.jobs.none": "ninguno",
    "status.block": "Bloqueo {kind} en «{operation}»: {evidence}",
    "status.agent": "Agente: {detail}.",
    "status.hint": "Para un porqué o una recomendación pide un análisis; para ver algo, una tabla o un gráfico.",
    "brain.cancelled": "Cancelado antes de completar la planificación.",
    "brain.failed": " (la ruta por el modelo falló; prueba de nuevo o usa el planificador por reglas)",
    "brain.rules": "{reply} (El modelo local no produjo una respuesta válida: {why}. Respondí por reglas.)",
    "cancel.none": "no hay ningún turno en curso",
    "cancel.during": "cancelación pedida durante: {phase}; lo ya aplicado al lienzo permanece",
    "phase.planning": "planificación",
    "phase.reading": "lectura",
    "phase.building": "construcción",
    "refuse.action": (
        "No lo hago desde el chat: «{action}» es una acción, no una consulta. Para hacerla: {where}. Pasa por los "
        "permisos efectivos del proyecto y queda en la auditoría. Si quieres, te muestro o analizo lo que hay antes "
        "de decidir."
    ),
    "analyze.refused": "No puedo analizar esto con un modelo: {why}.",
    "analyze.hint": " Lo permitiría: {hint}.",
    "analyze.noanswer": "El modelo no respondió ({why}); sin análisis. Lo leído queda abajo.",
    "plan.cancelled": " Cancelado antes del paso {step} de {total}; lo anterior queda aplicado.",
    "where.deploy": "`unbidden deploy`",
    "where.rollback": "`unbidden deploy --rollback`",
    "where.merge": "una persona fusiona en GitHub; el modo autonomous fusiona trabajo L4 (`unbidden mode`)",
    "where.kill": "el botón del interruptor de emergencia, o `unbidden kill`",
    "where.resume": "el botón de reanudar, o `unbidden resume`",
    "where.experiment": "`unbidden try <oportunidad>` o el propio ciclo del agente (`unbidden start`)",
    "where.approve": "el botón de aprobar, o `unbidden approve <id>`",
    "where.reject": "el botón de rechazar, o `unbidden reject <id>`",
    "where.start": "`unbidden start`",
    "where.stop": "`unbidden stop`",
}
