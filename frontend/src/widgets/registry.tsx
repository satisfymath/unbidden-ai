// The typed registry: one component per widget type. A spec the registry does not know is never rendered.
import type { ComponentType } from "react";
import {
  Activity,
  BarChart3,
  Beaker,
  Camera,
  CheckSquare,
  Code2,
  Database,
  FileDiff,
  FlaskConical,
  GitPullRequest,
  LayoutGrid,
  ListChecks,
  Map as MapIcon,
  Plug,
  ShieldAlert,
  StickyNote,
  Table2,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import type { WidgetSpec, WidgetType } from "@/contracts";
import { ChartWidget } from "./ChartWidget";
import { TableWidget } from "./TableWidget";
import { SystemMapWidget } from "./SystemMapWidget";
import { ExperimentWidget, FindingWidget, MinimalCaseWidget, ProposalWidget, SqlWidget } from "./EntityWidgets";
import { AcceptanceWidget, ActivityWidget, CodeWidget, DiffWidget, MetricsWidget, NeedWidget, NoteWidget, ResourcesWidget, ScreenshotsWidget, TestsWidget } from "./MiscWidgets";

export type WidgetDef = {
  label: string;
  icon: LucideIcon;
  component: ComponentType<{ widget: WidgetSpec }>;
  size: { w: number; h: number };
  needsData?: boolean;
  needsEntity?: boolean;
  describe: string;
};

export const REGISTRY: Record<WidgetType, WidgetDef> = {
  activity: { label: "Actividad", icon: Activity, component: ActivityWidget, size: { w: 400, h: 300 }, describe: "Qué hace Unbidden ahora y los últimos eventos" },
  resources: { label: "Recursos", icon: Plug, component: ResourcesWidget, size: { w: 460, h: 280 }, describe: "Conexiones y lo que se comprobó de cada una" },
  finding: { label: "Hallazgo", icon: FlaskConical, component: FindingWidget, size: { w: 480, h: 300 }, needsEntity: true, describe: "Una oportunidad con su nivel, decisión y evidencia" },
  experiment: { label: "Experimento", icon: Beaker, component: ExperimentWidget, size: { w: 460, h: 320 }, needsEntity: true, describe: "Reproducir, comparar, validar: con lo medido" },
  chart: { label: "Gráfico", icon: BarChart3, component: ChartWidget, size: { w: 480, h: 320 }, needsData: true, describe: "Línea, barras, dispersión o distribución sobre un dataset" },
  table: { label: "Tabla", icon: Table2, component: TableWidget, size: { w: 520, h: 320 }, needsData: true, describe: "Filas de un dataset, paginadas" },
  metrics: { label: "Métricas", icon: LayoutGrid, component: MetricsWidget, size: { w: 400, h: 200 }, needsData: true, describe: "Resumen numérico de un dataset" },
  code: { label: "Código", icon: Code2, component: CodeWidget, size: { w: 480, h: 300 }, describe: "Un fragmento con números de línea" },
  diff: { label: "Diff", icon: FileDiff, component: DiffWidget, size: { w: 520, h: 320 }, describe: "Un parche unificado" },
  minimal_case: { label: "Caso mínimo", icon: Terminal, component: MinimalCaseWidget, size: { w: 440, h: 320 }, needsEntity: true, describe: "La entrada reducida que reproduce un fallo" },
  tests: { label: "Tests", icon: ListChecks, component: TestsWidget, size: { w: 440, h: 260 }, needsData: true, describe: "Rondas de tests en ambos lados, o los checks del proyecto" },
  screenshots: { label: "Capturas", icon: Camera, component: ScreenshotsWidget, size: { w: 480, h: 300 }, describe: "Comparación visual antes/después" },
  sql: { label: "Consulta SQL", icon: Database, component: SqlWidget, size: { w: 480, h: 280 }, needsEntity: true, describe: "La consulta y el plan observado" },
  need: { label: "Necesita una persona", icon: ShieldAlert, component: NeedWidget, size: { w: 440, h: 280 }, describe: "Bloqueos, accesos y aprobaciones pendientes" },
  acceptance: { label: "Aceptación", icon: CheckSquare, component: AcceptanceWidget, size: { w: 440, h: 260 }, describe: "Condiciones fijadas y lo observado" },
  system_map: { label: "Mapa del sistema", icon: MapIcon, component: SystemMapWidget, size: { w: 520, h: 360 }, describe: "Recursos y relaciones del modelo del mundo" },
  proposal: { label: "Cambio candidato", icon: GitPullRequest, component: ProposalWidget, size: { w: 480, h: 320 }, needsEntity: true, describe: "La propuesta y el estado de su PR" },
  note: { label: "Nota", icon: StickyNote, component: NoteWidget, size: { w: 360, h: 180 }, describe: "Texto libre, tuyo" },
};
