import maplibregl from "maplibre-gl";
import { useEffect, useMemo, useRef, useState } from "react";

import { categoryFor, dateLabel, hourLabel, hourOf, textOn, whole } from "../format";
import { clamp, lerp, reducedMotion, span, useProgress } from "./scroll";
import type { Bundle } from "./Story";

type Props = { data: Bundle };

const WHO_GUIDELINE = 15; // WHO 2021 air quality guideline, PM2.5 24-hour mean, ug/m3
const INDIA_STANDARD = 60; // India's NAAQS, PM2.5 24-hour, ug/m3
const CLEAR_SKY = [207, 227, 238];
const SMOG_SKY = [158, 148, 124];
const MAX_SPECKS = 520;

function rgb(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

const mix = (a: number[], b: number[], t: number) => `rgb(${a.map((v, i) => Math.round(lerp(v, b[i], t))).join(",")})`;
const show = (el: HTMLElement | null, on: number) => {
  if (!el) return;
  el.style.opacity = String(on);
  el.style.transform = `translateY(${(1 - on) * 24}px)`;
  el.style.visibility = on <= 0.01 ? "hidden" : "visible";
};

/** Chapter 1. One speck is 1 ug/m3 of PM2.5, so the screen fills to the city's real level. */
export function Specks({ data }: Props) {
  const { now } = data;
  const section = useRef<HTMLElement>(null);
  const stick = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const count = useRef<HTMLSpanElement>(null);
  const aqiNumber = useRef<HTMLSpanElement>(null);
  const steps = useRef<(HTMLDivElement | null)[]>([]);
  const state = useRef({ specks: 0, dark: false });
  const pm = Math.round(now.pollutants.find((p) => p.id === "pm2_5")?.value ?? now.pm2_5 ?? 0);
  const specks = useMemo(() => Array.from({ length: MAX_SPECKS }, (_, i) => ({
    x: (i * 0.6180339) % 1, y: (i * 0.7548776) % 1, r: 5 + ((i * 7) % 5) * 1.6, phase: i * 1.7, speed: 0.4 + ((i * 13) % 10) / 12,
  })), []);

  useEffect(() => {
    const el = canvas.current;
    const ctx = el?.getContext("2d");
    if (!el || !ctx) return;
    let frame = 0;
    const size = () => {
      const scale = Math.min(window.devicePixelRatio || 1, 2);
      el.width = el.clientWidth * scale;
      el.height = el.clientHeight * scale;
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
    };
    size();
    window.addEventListener("resize", size);
    const still = reducedMotion();
    const draw = (time: number) => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      ctx.clearRect(0, 0, w, h);
      const n = Math.min(Math.round(state.current.specks), MAX_SPECKS);
      ctx.fillStyle = state.current.dark ? "rgba(255,255,255,.62)" : "rgba(28,42,51,.6)";
      const t = still ? 0 : time / 1000;
      for (let i = 0; i < n; i += 1) {
        const s = specks[i];
        const x = ((s.x + Math.sin(t * 0.13 * s.speed + s.phase) * 0.018 + 1) % 1) * w;
        const y = ((s.y + Math.cos(t * 0.11 * s.speed + s.phase) * 0.024 + 1) % 1) * h;
        ctx.beginPath();
        ctx.arc(x, y, s.r, 0, Math.PI * 2);
        ctx.fill();
      }
      frame = requestAnimationFrame(draw);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", size);
    };
  }, [specks]);

  const color = now.category?.color ?? "#FFFFFF";
  useProgress(section, (p) => {
    const fill = p < 0.3 ? lerp(0, WHO_GUIDELINE, span(p, 0.08, 0.2))
      : p < 0.52 ? lerp(WHO_GUIDELINE, INDIA_STANDARD, span(p, 0.3, 0.42))
        : lerp(INDIA_STANDARD, pm, span(p, 0.52, 0.66));
    state.current.specks = fill;
    if (count.current) count.current.textContent = String(Math.round(fill));
    const hero = span(p, 0.76, 0.86);
    const haze = clamp(fill / 130);
    if (stick.current) {
      const sky = CLEAR_SKY.map((v, i) => lerp(v, SMOG_SKY[i], haze));
      stick.current.style.background = mix(sky, rgb(color), hero);
      stick.current.style.color = hero > 0.5 ? textOn(now.category?.name) : "#1C2A33";
    }
    state.current.dark = hero > 0.5 && textOn(now.category?.name) === "#FFFFFF";
    if (aqiNumber.current) aqiNumber.current.textContent = String(Math.round((now.aqi ?? 0) * span(p, 0.78, 0.92)));
    const windows = [[-1, 0, 0.04, 0.08], [0.09, 0.13, 0.25, 0.29], [0.31, 0.35, 0.47, 0.51], [0.53, 0.57, 0.7, 0.74], [0.77, 0.82, 2, 3]];
    windows.forEach(([a, b, c, d], i) => show(steps.current[i], Math.min(span(p, a, b), 1 - span(p, c, d))));
    const counter = count.current?.parentElement as HTMLElement | undefined;
    if (counter) show(counter, Math.min(span(p, 0.08, 0.13), 1 - span(p, 0.7, 0.76)));
  });

  return (
    <section ref={section} className="chapter" style={{ height: "560vh" }}>
      <div ref={stick} className="stick s-specks">
        <canvas ref={canvas} aria-hidden="true" />
        <p className="s-count"><span ref={count}>0</span> <small>µg/m³ of PM2.5</small></p>
        <div className="s-step" ref={(e) => { steps.current[0] = e; }}>
          <h1>How is the air in {now.city}?</h1>
          <p>Scroll to fill the sky with what's in it.</p>
        </div>
        <div className="s-step" ref={(e) => { steps.current[1] = e; }}>
          <h2>Each speck is 1 µg/m³ of PM2.5.</h2>
          <p>15 is the World Health Organization's guideline for a 24-hour average.</p>
        </div>
        <div className="s-step" ref={(e) => { steps.current[2] = e; }}>
          <h2>60 is India's own 24-hour standard.</h2>
        </div>
        <div className="s-step" ref={(e) => { steps.current[3] = e; }}>
          <h2>{pm} is {now.city} over the last 24 hours.</h2>
          <p>A model estimate. Street sensors can read much higher.</p>
        </div>
        <div className="s-step s-hero" ref={(e) => { steps.current[4] = e; }}>
          <p className="s-when">Right now, 24-hour average</p>
          <p className="s-aqi"><span ref={aqiNumber}>0</span><small>AQI</small></p>
          <p className="s-cat">{now.category?.name ?? "AQI not available"}</p>
          {now.dominant && <p>Driven mostly by {now.dominant}. CPCB scale, modelled data.</p>}
        </div>
      </div>
    </section>
  );
}

/** Chapter 2. The next 24 hours rise hour by hour as a skyline. */
export function Today({ data }: Props) {
  const { forecast } = data;
  const section = useRef<HTMLElement>(null);
  const bars = useRef<(HTMLDivElement | null)[]>([]);
  const sun = useRef<HTMLElement>(null);
  const hour = useRef<HTMLSpanElement>(null);
  const value = useRef<HTMLSpanElement>(null);
  const finale = useRef<HTMLDivElement>(null);
  const opening = useRef<HTMLDivElement>(null);
  const bracket = useRef<HTMLDivElement>(null);
  const hours = forecast.hours;
  const top = Math.max(300, ...hours.map((h) => h.hourly_index ?? 0));
  const best = forecast.best_time;
  const first = best ? hours.findIndex((h) => h.time >= best.start) : -1;
  const last = best ? hours.filter((h) => h.time < best.end).length : -1;
  const tomorrow = best && best.start.slice(0, 10) !== forecast.issued.slice(0, 10);

  useProgress(section, (p) => {
    const rise = span(p, 0.03, 0.8) * hours.length;
    bars.current.forEach((bar, i) => {
      if (bar) bar.style.transform = `scaleY(${clamp(rise - i)})`;
    });
    const i = Math.min(Math.floor(rise), hours.length - 1);
    const now = hours[i];
    if (hour.current) hour.current.textContent = hourLabel(now.time);
    if (value.current) {
      const cat = categoryFor(now.hourly_index);
      value.current.textContent = `${whole(now.hourly_index)}, ${cat?.name ?? "no data"}`;
    }
    if (sun.current) {
      const h = hourOf(now.time) + (rise % 1);
      const day = span(h, 6, 18);
      sun.current.style.left = `${((i + 0.5) / hours.length) * 100}%`;
      sun.current.style.bottom = `${72 + Math.sin(day * Math.PI) * 24}%`;
      sun.current.style.opacity = h > 6 && h < 18 ? "1" : "0.25";
    }
    show(opening.current, 1 - span(p, 0.8, 0.86));
    show(finale.current, span(p, 0.84, 0.92));
    if (bracket.current) bracket.current.style.opacity = String(span(p, 0.82, 0.9));
  });

  return (
    <section ref={section} className="chapter" style={{ height: "340vh" }}>
      <div className="stick s-today">
        <div className="s-head">
          <div ref={opening}>
            <h2>The next 24 hours</h2>
            <p className="s-big"><span ref={hour}>{hourLabel(hours[0].time)}</span>: <span ref={value}>…</span></p>
          </div>
          <div ref={finale} className="s-over">
            <h2>{best ? `Best time outside ${tomorrow ? "tomorrow" : "today"}: ${hourLabel(best.start)} to ${hourLabel(best.end)}` : "No clear best time today"}</h2>
            {best && <p className="s-big">About {best.mean_index} on the hourly index, {best.category?.name}.</p>}
          </div>
        </div>
        <div className="s-skyline" aria-label="Forecast by hour" role="img">
          <i ref={sun} className="s-sun" aria-hidden="true" />
          {hours.map((h, i) => (
            <div key={h.time} className="s-col">
              <div ref={(e) => { bars.current[i] = e; }} className="s-barfill"
                style={{ height: `${((h.hourly_index ?? 0) / top) * 100}%`, background: categoryFor(h.hourly_index)?.color ?? "#FFFFFF" }} />
            </div>
          ))}
          {first >= 0 && (
            <div ref={bracket} className="s-bracket" style={{ left: `${(first / hours.length) * 100}%`, width: `${((last - first) / hours.length) * 100}%` }} />
          )}
        </div>
        <div className="s-hours" aria-hidden="true">
          {hours.map((h, i) => (i % 4 === 0 ? <span key={h.time} style={{ left: `${(i / hours.length) * 100}%` }}>{hourLabel(h.time)}</span> : null))}
        </div>
        <p className="s-fine">Hourly index from PM2.5 and PM10, not the 24-hour AQI. Forecast from {forecast.source}. {forecast.served_reason}</p>
      </div>
    </section>
  );
}

/** Chapter 3. Real fire detections appear day by day while the map moves towards them. */
export function Fires({ data }: Props) {
  const { days, sources, now, city } = data;
  const section = useRef<HTMLElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const engine = useRef<maplibregl.Map | null>(null);
  const loaded = useRef(false);
  const dateEl = useRef<HTMLSpanElement>(null);
  const countEl = useRef<HTMLSpanElement>(null);
  const reason = useRef<HTMLParagraphElement>(null);
  const totals = useMemo(() => {
    let sum = 0;
    return days.map((d) => (sum += d.fires.length));
  }, [days]);
  const centre = useMemo(() => {
    const all = days.flatMap((d) => d.fires).filter((f) => f.lat > 29);
    if (!all.length) return [city.lon, city.lat];
    return [all.reduce((s, f) => s + f.lon, 0) / all.length, all.reduce((s, f) => s + f.lat, 0) / all.length];
  }, [days, city]);
  const crop = sources.sources.find((s) => s.id === "crop");

  useEffect(() => {
    if (!holder.current) return;
    const instance = new maplibregl.Map({
      container: holder.current, style: "https://tiles.openfreemap.org/styles/positron", center: [city.lon, city.lat], zoom: 8.2,
      interactive: false, attributionControl: { compact: true },
    });
    instance.on("load", () => {
      instance.addSource("fires", {
        type: "geojson",
        data: {
          type: "FeatureCollection",
          features: days.flatMap((d, day) => d.fires.map((f) => ({
            type: "Feature" as const, properties: { day }, geometry: { type: "Point" as const, coordinates: [f.lon, f.lat] },
          }))),
        },
      });
      instance.addLayer({
        id: "fires", type: "circle", source: "fires", filter: ["<=", ["get", "day"], -1],
        paint: { "circle-color": "#C8321E", "circle-opacity": 0.75, "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 2, 9, 5] },
      });
      loaded.current = true;
    });
    const pin = document.createElement("div");
    pin.className = "s-pin";
    pin.style.background = now.category?.color ?? "#FFFFFF";
    pin.style.color = textOn(now.category?.name);
    pin.textContent = city.name;
    new maplibregl.Marker({ element: pin }).setLngLat([city.lon, city.lat]).addTo(instance);
    engine.current = instance;
    return () => {
      instance.remove();
      engine.current = null;
    };
  }, [city, days, now]);

  useProgress(section, (p) => {
    const m = engine.current;
    const move = span(p, 0.05, 0.7);
    m?.jumpTo({ center: [lerp(city.lon, centre[0], move), lerp(city.lat, centre[1], move)], zoom: lerp(8.2, 6.1, move) });
    const i = Math.min(Math.floor(span(p, 0.1, 0.82) * days.length), days.length - 1);
    if (m && loaded.current) m.setFilter("fires", ["<=", ["get", "day"], p < 0.1 ? -1 : i]);
    if (days.length) {
      if (dateEl.current) dateEl.current.textContent = dateLabel(days[Math.max(i, 0)].date);
      if (countEl.current) countEl.current.textContent = whole(p < 0.1 ? 0 : totals[i]);
    }
    show(reason.current, span(p, 0.82, 0.9));
  });

  return (
    <section ref={section} className="chapter" style={{ height: "420vh" }}>
      <div className="stick s-fires">
        <div ref={holder} className="s-map" role="img" aria-label="Map of fire detections over the last week" />
        <aside className="s-panel">
          <h2>Fires over the last week</h2>
          {days.length ? (
            <>
              <p className="s-big"><span ref={dateEl}>{dateLabel(days[0].date)}</span></p>
              <p className="s-tally"><span ref={countEl}>0</span> <small>satellite detections so far</small></p>
              <p ref={reason} className="s-reason">{crop?.reason} Crop burning scores {crop?.level.toLowerCase()} right now.</p>
            </>
          ) : <p>Fire data is unavailable right now.</p>}
          <p className="s-fine">NASA FIRMS, VIIRS. One fire can be seen on several passes, so these are detections, not fires.</p>
        </aside>
      </div>
    </section>
  );
}

/** Chapter 4. Each likely cause fills to its score, one after another. */
export function Causes({ data }: Props) {
  const { sources } = data;
  const section = useRef<HTMLElement>(null);
  const fills = useRef<(HTMLElement | null)[]>([]);
  const rows = useRef<(HTMLLIElement | null)[]>([]);
  const ranked = sources.sources.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  useProgress(section, (p) => {
    ranked.forEach((s, i) => {
      const t = span(p, 0.08 + i * 0.18, 0.24 + i * 0.18);
      show(rows.current[i], span(p, 0.03 + i * 0.18, 0.1 + i * 0.18));
      const fill = fills.current[i];
      if (fill) fill.style.transform = `scaleX(${(s.score ?? 0) * t})`;
    });
  });
  return (
    <section ref={section} className="chapter" style={{ height: "300vh" }}>
      <div className="stick s-causes">
        <div className="s-wide">
          <h2>Why it's like this</h2>
          <p>{sources.note}</p>
          <ul>
            {ranked.map((s, i) => (
              <li key={s.id} ref={(e) => { rows.current[i] = e; }}>
                <div className="s-cause-head"><strong>{s.label}</strong><span>{s.level}{s.score != null ? `, ${s.score.toFixed(2)}` : ""}</span></div>
                <div className="s-track"><i ref={(e) => { fills.current[i] = e; }} /></div>
                <p>{s.reason}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/** Chapter 5. This season draws itself against last season, on the same dates. */
export function Season({ data }: Props) {
  const { history } = data;
  const section = useRef<HTMLElement>(null);
  const clip = useRef<SVGRectElement>(null);
  const dot = useRef<SVGCircleElement>(null);
  const label = useRef<HTMLSpanElement>(null);
  const summary = useRef<HTMLParagraphElement>(null);
  const rows = history.season_chart;
  const W = 1000;
  const H = 310;
  const top = Math.max(430, ...rows.flatMap((r) => [r.this_season ?? 0, r.last_season ?? 0]) ) * 1.04;
  const x = (i: number) => (i / Math.max(rows.length - 1, 1)) * W;
  const y = (v: number) => H - (v / top) * H;
  const path = (key: "this_season" | "last_season") => {
    let d = "";
    let pen = false;
    rows.forEach((r, i) => {
      const v = r[key];
      if (v == null) { pen = false; return; }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  };
  useProgress(section, (p) => {
    const t = span(p, 0.04, 0.84);
    clip.current?.setAttribute("width", String(t * W + 8));
    const i = Math.min(Math.round(t * (rows.length - 1)), rows.length - 1);
    const r = rows[i];
    if (dot.current && r?.this_season != null) {
      dot.current.setAttribute("cx", String(x(i)));
      dot.current.setAttribute("cy", String(y(r.this_season)));
    }
    if (label.current && r) label.current.textContent = `${r.label}: ${r.this_season ?? "no data"} this season, ${r.last_season ?? "no data"} last season`;
    show(summary.current, span(p, 0.84, 0.92));
  });
  const bands: [number, string][] = [[100, "Good and Satisfactory end"], [200, "Moderately Polluted ends"], [300, "Poor ends"], [400, "Very Poor ends"]];
  return (
    <section ref={section} className="chapter" style={{ height: "340vh" }}>
      <div className="stick s-season">
        <div className="s-wide">
          <h2>This season against last</h2>
          <p className="s-big"><span ref={label}>…</span></p>
          <svg viewBox={`-4 -8 ${W + 8} ${H + 16}`} preserveAspectRatio="xMinYMid meet" role="img" aria-label="Daily AQI this season and last season on the same dates">
            <defs><clipPath id="s-reveal"><rect ref={clip} x="-4" y="-8" width="0" height={H + 16} /></clipPath></defs>
            {bands.map(([v, name]) => (
              <g key={v}>
                <line x1="0" x2={W} y1={y(v)} y2={y(v)} stroke="#C3CAC3" />
                <text x={W} y={y(v) - 5} fontSize="13" textAnchor="end" fill="#4A5A66" stroke="#F5F6F1" strokeWidth="4" paintOrder="stroke">{v}: {name}</text>
              </g>
            ))}
            <g clipPath="url(#s-reveal)">
              <path d={path("last_season")} fill="none" stroke="#A65A00" strokeWidth="3" strokeDasharray="10 7" />
              <path d={path("this_season")} fill="none" stroke="#0072B2" strokeWidth="4" />
            </g>
            <circle ref={dot} r="8" fill="#0072B2" stroke="#F5F6F1" strokeWidth="3" />
          </svg>
          <ul className="s-legend">
            <li><i style={{ background: "#0072B2" }} />This season</li>
            <li><i className="s-dash" />Last season</li>
          </ul>
          <p ref={summary} className="s-reason">{history.season.summary}</p>
          <p className="s-fine">Same model, same CPCB method, same dates. Data from {dateLabel(history.range.from, true)} to {dateLabel(history.range.to, true)}.</p>
        </div>
      </div>
    </section>
  );
}

const CAUSES: Record<string, { letter: string; label: string }> = {
  crop: { letter: "C", label: "Crop burning" }, vehicles: { letter: "V", label: "Vehicles" },
  dust: { letter: "D", label: "Dust" }, weather: { letter: "W", label: "Weather trapping" },
};

/** Chapter 6. Each day of the season lands with its AQI and likely cause. */
export function Calendar({ data }: Props) {
  const days = data.history.calendar;
  const section = useRef<HTMLElement>(null);
  const cells = useRef<(HTMLDivElement | null)[]>([]);
  const end = useRef<HTMLParagraphElement>(null);
  const tally = useMemo(() => {
    const counts: Record<string, number> = {};
    days.forEach((d) => { if (d.cause) counts[d.cause.id] = (counts[d.cause.id] ?? 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [days]);
  const scored = days.filter((d) => d.crop_scored).length;
  useProgress(section, (p) => {
    const t = span(p, 0.03, 0.8) * days.length;
    cells.current.forEach((cell, i) => {
      if (!cell) return;
      const on = clamp(t - i);
      cell.style.opacity = String(on);
      cell.style.transform = `scale(${0.7 + on * 0.3})`;
    });
    show(end.current, span(p, 0.8, 0.88));
  });
  const [y, m, d] = (days[0]?.date ?? "2026-10-01").split("-").map(Number);
  const blanks = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7;
  return (
    <section ref={section} className="chapter" style={{ height: "320vh" }}>
      <div className="stick s-cal">
        <div className="s-cal-text">
          <h2>What each day was about</h2>
          <p>Each square is one day: its AQI, and the likeliest cause.</p>
          <ul className="s-key">
            {Object.entries(CAUSES).map(([id, c]) => <li key={id}><b>{c.letter}</b> {c.label}</li>)}
            <li><b>–</b> No clear cause</li>
          </ul>
          <p ref={end} className="s-reason">
            {tally.length ? `${CAUSES[tally[0][0]].label} led on ${tally[0][1]} of ${days.length} days.` : "No clear cause stood out."} Still air often leads because it traps pollution from every other source. It doesn't create pollution itself.
          </p>
          <p className="s-fine">Crop burning could be scored on {scored} of {days.length} days, because older fire records aren't loaded yet.</p>
        </div>
        <div className="s-grid" role="img" aria-label="Calendar of daily AQI and likely cause this season">
          {["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((w) => <span key={w} className="s-wd">{w}</span>)}
          {Array.from({ length: blanks }, (_, i) => <span key={`b${i}`} />)}
          {days.map((day, i) => (
            <div key={day.date} ref={(e) => { cells.current[i] = e; }} className="s-day" title={dateLabel(day.date)}
              style={{ background: day.category?.color ?? "#FFFFFF", color: textOn(day.category?.name) }}>
              <small>{dateLabel(day.date)}</small>
              <b>{day.aqi ?? "?"}</b>
              <em>{day.cause ? CAUSES[day.cause.id]?.letter : "–"}</em>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

/** Chapter 7. How far to trust all of this, using the real test results. */
export function Trust({ data }: Props) {
  const { forecast, now } = data;
  const section = useRef<HTMLElement>(null);
  const a = useRef<HTMLElement>(null);
  const b = useRef<HTMLElement>(null);
  const lines = useRef<(HTMLLIElement | null)[]>([]);
  const m = forecast.metrics;
  const worst = Math.max(m.ours?.mae ?? 1, m.persistence?.mae ?? 1);
  useProgress(section, (p) => {
    const t = span(p, 0.05, 0.4);
    if (a.current) a.current.style.transform = `scaleX(${((m.ours?.mae ?? 0) / worst) * t})`;
    if (b.current) b.current.style.transform = `scaleX(${((m.persistence?.mae ?? 0) / worst) * t})`;
    lines.current.forEach((line, i) => show(line, span(p, 0.4 + i * 0.13, 0.5 + i * 0.13)));
  });
  return (
    <section ref={section} className="chapter" style={{ height: "260vh" }}>
      <div className="stick s-trust">
        <div className="s-wide">
          <h2>How far to trust this</h2>
          {m.ours && m.persistence && m.test_period && (
            <>
              <p>Average forecast error for {now.city}, {dateLabel(m.test_period[0])} to {dateLabel(m.test_period[1])}. Shorter is better.</p>
              <div className="s-compare">
                <span>AirWatch model</span><div className="s-track"><i ref={a} /></div><strong>{m.ours.mae} µg/m³</strong>
                <span>Assuming no change</span><div className="s-track"><i ref={b} className="s-second" /></div><strong>{m.persistence.mae} µg/m³</strong>
              </div>
            </>
          )}
          <ul className="s-points">
            <li ref={(e) => { lines.current[0] = e; }}>Those errors are measured against Open-Meteo's own past values, not real stations.</li>
            <li ref={(e) => { lines.current[1] = e; }}>{forecast.served_reason}</li>
            <li ref={(e) => { lines.current[2] = e; }}>{now.official.available ? "Official station readings are shown on the details page." : `${now.official.message} All numbers here are modelled.`}</li>
            <li ref={(e) => { lines.current[3] = e; }}>
              {now.shared_grid_with ? `The model gives ${now.city} and ${now.shared_grid_with} the same air data. ` : ""}Street sensors can read much higher than this model.
            </li>
          </ul>
        </div>
      </div>
    </section>
  );
}

/** Chapter 8. Guidance for today's category, then the sources. */
export function Advice({ data }: Props) {
  const { now, id } = data;
  const section = useRef<HTMLElement>(null);
  const items = useRef<(HTMLDivElement | null)[]>([]);
  const [opened] = useState(() => new Date().getFullYear());
  useProgress(section, (p) => {
    items.current.forEach((item, i) => show(item, span(p, 0.05 + i * 0.16, 0.2 + i * 0.16)));
  });
  return (
    <>
      <section ref={section} className="chapter" style={{ height: "240vh" }}>
        <div className="stick s-advice" style={{ borderTop: `12px solid ${now.category?.color ?? "#FFFFFF"}` }}>
          <div className="s-wide">
            <h2>What to do in {now.category?.name ?? "this"} air</h2>
            <div className="s-cards">
              {now.advice.map((item, i) => (
                <div key={item.id} ref={(e) => { items.current[i] = e; }}>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                </div>
              ))}
            </div>
            <p className="s-fine">{now.advice_note} If stations near you show worse air, follow the advice for that category.</p>
          </div>
        </div>
      </section>
      <footer className="s-foot">
        <p><a href="#/map">Explore the map</a> <a href={`#/city/${id}`}>See every number for {now.city}</a></p>
        <p className="s-fine">
          Air and weather: Open-Meteo (CAMS global model). Fires: NASA FIRMS. AQI method: CPCB. Guideline: WHO 2021 (15 µg/m³, 24-hour PM2.5). Standard: India's NAAQS (60 µg/m³, 24-hour PM2.5).
          AirWatch, Neural Storm {opened}.
        </p>
      </footer>
    </>
  );
}
