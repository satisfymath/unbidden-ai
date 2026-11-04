// Charts from a resolved dataset: line, bar, scatter and distribution. Points are capped and the cap is said.
import { useMemo } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import type { DataResult, WidgetSpec } from "@/contracts";
import { useDataRef } from "./useData";
import { DataFrame, Empty, Loading, fmtNum } from "./common";

const PALETTE = ["#f3f1ec", "#77756f", "#d9b779", "#bdb6c9", "#a9c9a4", "#e0776f", "#c9a98f"];
const MAX_POINTS = 1500;
const SERIES_COLORS: Record<string, string> = { before: "#77756f", after: "#f3f1ec", base: "#77756f", candidate: "#f3f1ec", antes: "#77756f", después: "#f3f1ec" };

function colorFor(name: string, i: number): string {
  return SERIES_COLORS[name] ?? PALETTE[i % PALETTE.length] ?? "#f3f1ec";
}

function labelFor(name: string): string {
  return ({ before: "antes", after: "después", base: "antes", candidate: "después" } as Record<string, string>)[name] ?? name;
}

function histogram(result: DataResult, field: string, seriesField: string | null, bins: number) {
  const values = result.rows.map((r) => r[field]).filter((v): v is number => typeof v === "number");
  if (!values.length) return { data: [], series: [] as string[] };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = (max - min) / bins || 1;
  const series = seriesField ? [...new Set(result.rows.map((r) => String(r[seriesField])))] : ["valor"];
  const data = Array.from({ length: bins }, (_, i) => {
    const row: Record<string, number | string> = { bin: Number((min + i * width).toFixed(2)), label: `${fmtNum(min + i * width)}–${fmtNum(min + (i + 1) * width)}` };
    for (const s of series) row[s] = 0;
    return row;
  });
  for (const r of result.rows) {
    const v = r[field];
    if (typeof v !== "number") continue;
    const i = Math.min(bins - 1, Math.floor((v - min) / width));
    const s = seriesField ? String(r[seriesField]) : "valor";
    const row = data[i];
    if (row) row[s] = (Number(row[s]) || 0) + 1;
  }
  return { data, series };
}

function pivot(result: DataResult, x: string, y: string, seriesField: string | null) {
  const series = seriesField ? [...new Set(result.rows.map((r) => String(r[seriesField])))] : [y];
  const byX = new Map<string | number, Record<string, unknown>>();
  for (const r of result.rows.slice(0, MAX_POINTS)) {
    const key = r[x] as string | number;
    const row = byX.get(key) ?? { [x]: key };
    row[seriesField ? String(r[seriesField]) : y] = r[y];
    byX.set(key, row);
  }
  return { data: [...byX.values()], series };
}

const tooltipStyle = { background: "rgba(10,10,10,0.96)", border: "1px solid var(--line-strong)", borderRadius: 10, fontSize: 12, color: "var(--ink)" };
const axisStyle = { fill: "#8e8c87", fontSize: 11 };

export function ChartBody({ widget, result }: { widget: WidgetSpec; result: DataResult }) {
  const view = widget.view;
  const unit = view.unit ?? result.columns.find((c) => c.name === view.y)?.unit ?? null;
  const chart = useMemo(() => {
    if (view.kind === "distribution") {
      const field = view.x ?? view.y ?? result.columns.find((c) => c.type === "number")?.name ?? "";
      return { kind: "distribution" as const, ...histogram(result, field, view.series ?? null, view.bins ?? 20) };
    }
    const x = view.x ?? result.columns[0]?.name ?? "";
    const y = view.y ?? result.columns.find((c) => c.type === "number")?.name ?? "";
    const p = pivot(result, x, y, view.series ?? null);
    return { kind: view.kind, x, y, ...p };
  }, [result, view]);
  const capped = result.rows.length > MAX_POINTS;
  const isTime = result.columns.find((c) => c.name === ("x" in chart ? chart.x : ""))?.type === "datetime";
  const fmtX = (v: unknown) => (isTime && typeof v === "string" ? new Date(v).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" }) : String(v).slice(0, 18));
  const fmtY = (v: unknown) => fmtNum(v);
  const common = { margin: { top: 10, right: 12, bottom: 4, left: 0 } };
  const legend = chart.series.length > 1 ? <Legend formatter={labelFor} wrapperStyle={{ fontSize: 11 }} /> : null;
  const tip = <Tooltip contentStyle={tooltipStyle} formatter={(v) => [fmtNum(v as number, unit), ""]} labelFormatter={(l) => String(l)} />;
  return (
    <div className="chart-wrap nowheel" style={{ height: "100%", minHeight: 120 }}>
      <ResponsiveContainer width="100%" height="100%">
        {chart.kind === "distribution" ? (
          <BarChart data={chart.data} {...common}>
            <CartesianGrid stroke="rgba(243,241,236,0.1)" vertical={false} />
            <XAxis dataKey="label" tick={axisStyle} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={34} />
            {tip}
            {legend}
            {chart.series.map((s, i) => (
              <Bar key={s} dataKey={s} name={labelFor(s)} fill={colorFor(s, i)} radius={[3, 3, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        ) : chart.kind === "bar" ? (
          <BarChart data={chart.data} {...common}>
            <CartesianGrid stroke="rgba(243,241,236,0.1)" vertical={false} />
            <XAxis dataKey={chart.x} tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={fmtX} minTickGap={16} />
            <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={44} tickFormatter={fmtY} />
            {tip}
            {legend}
            {chart.series.map((s, i) => (
              <Bar key={s} dataKey={s} name={labelFor(s)} fill={colorFor(s, i)} radius={[4, 4, 0, 0]} isAnimationActive={false} />
            ))}
          </BarChart>
        ) : chart.kind === "scatter" ? (
          <ScatterChart {...common}>
            <CartesianGrid stroke="rgba(243,241,236,0.1)" />
            <XAxis dataKey={chart.x} name={chart.x} tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={fmtX} />
            <YAxis dataKey={chart.y} name={chart.y} tick={axisStyle} tickLine={false} axisLine={false} width={44} tickFormatter={fmtY} />
            {tip}
            {legend}
            {chart.series.map((s, i) => (
              <Scatter key={s} name={labelFor(s)} data={result.rows.filter((r) => !view.series || String(r[view.series]) === s).slice(0, MAX_POINTS)} fill={colorFor(s, i)} isAnimationActive={false} />
            ))}
          </ScatterChart>
        ) : (
          <LineChart data={chart.data} {...common}>
            <CartesianGrid stroke="rgba(243,241,236,0.1)" vertical={false} />
            <XAxis dataKey={chart.x} tick={axisStyle} tickLine={false} axisLine={false} tickFormatter={fmtX} minTickGap={28} />
            <YAxis tick={axisStyle} tickLine={false} axisLine={false} width={44} tickFormatter={fmtY} domain={["auto", "auto"]} />
            {tip}
            {legend}
            {chart.series.map((s, i) => (
              <Line key={s} type="monotone" dataKey={s} name={labelFor(s)} stroke={colorFor(s, i)} strokeWidth={2} dot={false} isAnimationActive={false} connectNulls />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
      {capped ? <div className="tiny muted" style={{ position: "absolute", right: 10, bottom: 6 }}>primeros {MAX_POINTS} puntos de {result.rows.length}</div> : null}
    </div>
  );
}

export function ChartWidget({ widget }: { widget: WidgetSpec }) {
  const { result, loading, error } = useDataRef(widget.dataRef);
  if (!widget.dataRef) return <Empty kind="warn" title="Gráfico sin datos" detail="Este gráfico no tiene una referencia de datos." />;
  if (error) return <Empty kind="bad" title="No se pudo leer" detail={error} />;
  if (loading && !result) return <Loading />;
  if (!result || !result.rows.length) return <Empty kind="warn" title="Sin datos para este gráfico" detail={result?.provenance.note ?? "El registro no tiene filas para esta referencia."} />;
  return <DataFrame widget={widget} result={result}><ChartBody widget={widget} result={result} /></DataFrame>;
}
