// Resolves a dataRef through the server with a small cache; live sources refetch when new events arrive.
import { useEffect, useState } from "react";
import type { DataRef, DataResult } from "@/contracts";
import { useStore } from "@/data/store";

const cache = new Map<string, { at: number; result: DataResult }>();
const inflight = new Map<string, Promise<DataResult>>();
const TTL = 8000;

type Loaded = { key: string; result: DataResult | null; error: string | null };

export function useDataRef(ref: DataRef | null | undefined): { result: DataResult | null; loading: boolean; error: string | null; refresh: () => void } {
  const api = useStore((s) => s.api);
  const ws = useStore((s) => s.ws);
  const lastSeq = useStore((s) => s.lastSeq);
  const streams = useStore((s) => s.summary?.connection.streams ?? false);
  const [tick, setTick] = useState(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const dataKey = ref && ws ? `${ws}|${JSON.stringify(ref)}` : null;
  // The fetch key changes with every reason to read again: the ref, the workspace, a refresh, or (live) new events.
  const fetchKey = dataKey ? `${dataKey}|${tick}|${streams ? lastSeq : 0}` : null;

  useEffect(() => {
    if (!fetchKey || !dataKey || !api || !ws || !ref) return;
    const cached = cache.get(dataKey);
    if (cached && Date.now() - cached.at < TTL && tick === 0 && loaded?.key === fetchKey) return;
    let alive = true;
    const run =
      inflight.get(fetchKey) ??
      api.data(ws, ref).then((r) => {
        cache.set(dataKey, { at: Date.now(), result: r });
        inflight.delete(fetchKey);
        return r;
      });
    inflight.set(fetchKey, run);
    run
      .then((r) => alive && setLoaded({ key: fetchKey, result: r, error: null }))
      .catch((err: unknown) => {
        inflight.delete(fetchKey);
        if (alive) setLoaded({ key: fetchKey, result: cache.get(dataKey)?.result ?? null, error: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      alive = false;
    };
    // `ref` is represented by dataKey; `loaded` is read, not a dependency to re-run on.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchKey, dataKey, api, ws, tick]);

  const cached = dataKey ? (cache.get(dataKey)?.result ?? null) : null;
  const current = loaded && loaded.key === fetchKey ? loaded : null;
  const result = current?.result ?? cached;
  const loading = !!fetchKey && !current && !cached;
  return { result, loading, error: current?.error ?? null, refresh: () => setTick((t) => t + 1) };
}

export function invalidateData() {
  cache.clear();
}
