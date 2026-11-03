import "./story.css";

import { useEffect, useState } from "react";

import { Forecast, History, Insights, load, Now, Sources } from "../api";
import { Problem } from "../parts";
import { Advice, Calendar, Causes, Fires, Next, Season, Specks, Today, Trust } from "./chapters";
import { clamp } from "./scroll";

export const CITY_NAMES: Record<string, string> = {
  delhi: "Delhi", gurugram: "Gurugram", noida: "Noida", ghaziabad: "Ghaziabad",
  chandigarh: "Chandigarh", ludhiana: "Ludhiana", lucknow: "Lucknow", kanpur: "Kanpur",
};

export type Bundle = {
  id: string; now: Now; forecast: Forecast; sources: Sources; history: History; insights: Insights;
  city: { id: string; name: string; lat: number; lon: number };
  days: { date: string; fires: { lat: number; lon: number }[] }[];
};

async function loadAll(id: string): Promise<Bundle> {
  const get = async <T,>(path: string) => (await load<T>(path)).data;
  const [now, forecast, sources, history, insights, cities, fires] = await Promise.all([
    get<Now>(`/api/city/${id}/now`), get<Forecast>(`/api/city/${id}/forecast`), get<Sources>(`/api/city/${id}/sources`),
    get<History>(`/api/city/${id}/history`), get<Insights>(`/api/city/${id}/insights`), get<Bundle["city"][]>("/api/cities"), get<{ days: Bundle["days"] }>("/api/fires"),
  ]);
  return { id, now, forecast, sources, history, insights, city: cities.find((c) => c.id === id)!, days: fires.days };
}

function TopBar({ id }: { id: string }) {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    const onScroll = () => {
      const room = document.documentElement.scrollHeight - window.innerHeight;
      setProgress(clamp(window.scrollY / Math.max(room, 1)));
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  return (
    <nav className="s-bar">
      <strong>AirWatch</strong>
      <label>
        <span className="s-hide">Choose a city</span>
        <select value={id} onChange={(e) => { window.location.hash = `#/${e.target.value}`; }}>
          {Object.entries(CITY_NAMES).map(([key, name]) => <option key={key} value={key}>{name}</option>)}
        </select>
      </label>
      <a href="#/map">Map</a>
      <a href={`#/city/${id}`}>Full details</a>
      <i style={{ transform: `scaleX(${progress})` }} />
    </nav>
  );
}

export function Story({ id }: { id: string }) {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setBundle(null);
    setError(null);
    window.scrollTo(0, 0);
    loadAll(id).then((b) => {
      if (!live) return;
      setBundle(b);
      window.scrollTo(0, 0);
    }).catch((e: Error) => live && setError(e.message));
    return () => { live = false; };
  }, [id, attempt]);

  return (
    <div className="story">
      <TopBar id={id} />
      {error && <div className="s-wait"><Problem message={error} retry={() => setAttempt((n) => n + 1)} /></div>}
      {!bundle && !error && <div className="s-wait" role="status"><p>Reading the air over {CITY_NAMES[id]}</p></div>}
      {bundle && (
        <main key={id}>
          <Specks data={bundle} />
          <Today data={bundle} />
          <Fires data={bundle} />
          <Causes data={bundle} />
          <Season data={bundle} />
          <Calendar data={bundle} />
          <Next data={bundle} />
          <Trust data={bundle} />
          <Advice data={bundle} />
        </main>
      )}
    </div>
  );
}
