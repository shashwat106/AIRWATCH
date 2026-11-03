import { useCallback, useEffect, useState } from "react";

const BASE = import.meta.env.VITE_API_URL ?? "";
// Raise this whenever API shapes change, so an old saved copy is never read by newer code.
const SAVE_VERSION = 2;

export type Category = { name: string; color: string };
export type Station = { station: string; aqi: number | null; dominant: string | null; category: Category | null; last_update?: string };
export type Now = {
  city: string; time: string; aqi: number | null; category: Category | null; dominant: string | null;
  pm2_5: number | null; pm10: number | null; unit: string; source: string; source_note: string;
  pollutants: { id: string; label: string; value: number | null; unit: string; window: string; sub_index: number | null }[];
  weather: { wind_kmh: number | null; wind_from: string | null; humidity_pct: number | null; mixing_layer_m: number | null; rain_mm: number | null };
  shared_grid_with: string | null; official: { available: boolean; message: string | null; stations: Station[]; source: string | null };
  advice: { id: string; title: string; text: string }[]; advice_note: string; fetched_at: string; stale: boolean;
};
export type Score = { mae: number; rmse: number; n: number };
export type ForecastHour = {
  time: string; pm2_5: number | null; pm10: number | null; aqi: number | null; hourly_index: number | null;
  open_meteo_pm2_5: number | null; ours_pm2_5: number | null;
};
export type Forecast = {
  city: string; issued: string; served: string; served_reason: string; hours: ForecastHour[];
  best_time: { start: string; end: string; mean_index: number; category: Category } | null; best_time_note: string;
  metrics: { ours?: Score; persistence?: Score; same_hour_yesterday?: Score; test_period?: string[] }; source: string;
};
export type SourceScore = { id: string; label: string; score: number | null; level: string; reason: string };
export type Sources = {
  city: string; time: string; sources: SourceScore[]; note: string;
  fires: { available: boolean; source?: string; note?: string };
};
export type DayRow = { date: string; aqi: number; pm2_5: number; upwind_fires?: number };
export type Earlier = Partial<DayRow> & { date: string; available: boolean; summary?: string };
export type Average = { days_with_data: number; aqi: number | null; pm2_5: number | null; summary?: string };
export type Season = {
  start: string; end: string; days_with_data: number; days_expected: number; mean_aqi: number | null;
  poor_days: number; very_poor_days: number; severe_days: number; upwind_fires: number | null;
};
export type Notable = { date: string; aqi: number; pm2_5: number; category: string; dominant: string | null; top_source: { label: string; score: number } | null };
export type CalendarDay = {
  date: string; aqi: number | null; category: Category | null; dominant: string | null; crop_scored: boolean;
  cause: { id: string; label: string; score: number } | null;
};
export type History = {
  city: string; as_of: string; window: string;
  vs_years: { day: DayRow | null; earlier: Earlier[] };
  vs_recent: { day: DayRow | null; last_7_days: Average; last_30_days: Average };
  season: { this_season: Season; last_season: Season; summary: string | null };
  season_chart: { label: string; this_season: number | null; last_season: number | null }[];
  calendar: CalendarDay[];
  fire_link: { available: boolean; reason?: string; summary?: string; points?: { fires: number; pm2_5: number }[] };
  notable: { this_season: Notable[]; last_season: Notable[] };
  fire_note: string | null; source: string; method_note: string; range: { from: string; to: string };
};
export type MapCity = {
  id: string; name: string; lat: number; lon: number; aqi: number | null; category: Category | null;
  wind_kmh: number | null; wind_from_deg: number | null; wind_from: string | null;
};
export type MapView = {
  date: string; cities: MapCity[]; fires: { lat: number; lon: number; confidence: string }[];
  fires_covered: boolean; fires_note: string | null; fires_meta: { source?: string; note?: string }; days: string[]; source: string;
};

export type Loaded<T> = { data: T; savedAt: string | null };

/** Fetch from our backend. If that fails, fall back to the last saved copy and report when it was saved. */
export async function load<T>(path: string): Promise<Loaded<T>> {
  const key = `airwatch:${SAVE_VERSION}:${path}`;
  try {
    const response = await fetch(`${BASE}${path}`);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail ?? `The server returned ${response.status}.`);
    }
    const data = (await response.json()) as T;
    try {
      localStorage.setItem(key, JSON.stringify({ at: new Date().toISOString(), data }));
    } catch {
      /* storage full or blocked: the app still works, just without an offline copy */
    }
    return { data, savedAt: null };
  } catch (error) {
    let saved: string | null = null;
    try {
      saved = localStorage.getItem(key);
    } catch {
      saved = null;
    }
    if (saved) {
      const parsed = JSON.parse(saved) as { at: string; data: T };
      return { data: parsed.data, savedAt: parsed.at };
    }
    throw error instanceof TypeError ? new Error("Can't reach AirWatch. Check your connection and try again.") : error;
  }
}

export type Resource<T> = { data: T | null; savedAt: string | null; error: string | null; loading: boolean; retry: () => void };

export function useResource<T>(path: string): Resource<T> {
  const [state, setState] = useState<Omit<Resource<T>, "retry">>({ data: null, savedAt: null, error: null, loading: true });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, loading: true, error: null }));
    load<T>(path)
      .then(({ data, savedAt }) => live && setState({ data, savedAt, error: null, loading: false }))
      .catch((e: Error) => live && setState({ data: null, savedAt: null, error: e.message, loading: false }));
    return () => {
      live = false;
    };
  }, [path, attempt]);
  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
