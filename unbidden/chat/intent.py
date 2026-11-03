"""Inform, analyze or act: decided from the words, in Spanish and English, before any tool or model runs.

- inform: read records, put something on the canvas, edit it. Tools over raw records; no model, or the local one.
- analyze: why, compare, recommend, risk, summary. One model call over a bounded digest, routed like heavy work.
- act: approve, reject, deploy, roll back, merge, freeze or resume the agent, run an experiment. The chat never
  does these: they go through the actions panel or the CLI, under the project's effective permissions.

Asking for a chart or a table is informing, whatever the words around it: it never starts an experiment.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Literal

Intent = Literal["inform", "analyze", "act"]

# What the person would be asking Unbidden to DO. Each pattern names the operation the actions panel or the CLI
# offers, so the refusal can point at it.
_AGENT = r"(agente|motor|agent|engine|unbidden|kill switch|todo)"
_LAUNCH = r"(lanza|lanzar|ejecuta|ejecutar|corre|correr|arranca|arrancar|inicia|iniciar|run|start|launch|kick off)"
_RUN = r"(experimento|experimentos|experiment|experiments|ciclo|cycle|scan|escaneo|lab)"
ACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("approve", re.compile(r"\b(aprueba|apruebalo|apruebala|aprobar|aprueben|approve)\b")),
    ("reject", re.compile(r"\b(rechaza|rechazalo|rechazala|rechazar|reject|descarta|descartar)\b")),
    ("rollback", re.compile(r"\b(rollback|roll back|revierte el despliegue|revertir el despliegue)\b")),
    ("deploy", re.compile(r"\b(despliega|desplegar|deploy|deploya|deployar|redeploy)\b")),
    ("merge", re.compile(r"\b(merge|mergea|mergear|fusiona|fusionar)\b")),
    ("kill", re.compile(r"\b(kill switch|mata el agente|mata al agente|kill the agent|freeze)\b")),
    ("kill", re.compile(r"\b(deten|detener|parar|pausa|pausar|stop|congela)\b[^.]{0,30}\b" + _AGENT + r"\b")),
    # `para` is a preposition far more often than the imperative of `parar`: only `para el/al agente` is a stop.
    ("kill", re.compile(r"\bpara (el|al) " + _AGENT + r"\b")),
    ("resume", re.compile(r"\b(reanuda|reanudar|resume|descongela|unfreeze)\b[^.]{0,30}\b" + _AGENT + r"\b")),
    ("experiment", re.compile(r"\b" + _LAUNCH + r"\b[^.]{0,40}\b" + _RUN + r"\b")),
    ("experiment", re.compile(r"\b(prueba|probar|try|test)\b[^.]{0,20}\b(la oportunidad|the opportunity|opp_\w+)")),
)

# "compare" is not here: comparing two runs is the chart the rules draw (or they say what they need for it).
ANALYZE = re.compile(
    r"\b(por que|porque|why|recomienda|recomiendas|recomendar|"
    r"recomendacion|recommend|recommendation|riesgo|riesgos|risk|risks|resume|resumen|resumir|summary|summari[sz]e|"
    r"evalua|evaluar|evaluate|assess|que opinas|what do you think|deberia|deberiamos|should (i|we)|analiza|analizar|"
    r"analisis|analy[sz]e|analysis|tendencia|trend|diagnostica|diagnos|causa|cause|conclusion|conclu|vale la pena|"
    r"worth|prioriza|priorizar|prioriti[sz]e|que harias|what would you)\b"
)

# Showing something is informing even when an analysis word is nearby ("compare" with two runs selected is the
# comparison chart the rules draw; "summary table" is a table).
SHOW = re.compile(
    r"\b(grafica|graficar|grafico|chart|plot|tabla|table|muestra|muestrame|show|dibuja|draw|lista|list)\b"
)


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", plain.lower()).strip()


def action_asked(text: str) -> str | None:
    """The operation a message asks Unbidden to perform, or None when it only asks to see or understand."""
    t = _norm(text)
    for name, pattern in ACTIONS:
        if pattern.search(t):
            return name
    return None


def classify_intent(text: str) -> Intent:
    t = _norm(text)
    if action_asked(t):
        return "act"
    if ANALYZE.search(t) and not (SHOW.search(t) and not re.search(r"\b(por que|why|deberia|should)\b", t)):
        return "analyze"
    return "inform"
