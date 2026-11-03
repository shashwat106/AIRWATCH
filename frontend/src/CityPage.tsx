import { useState } from "react";
import {
  CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis,
} from "recharts";

import { CalendarDay, Forecast, History, Insights, Now, Resource, Sources, useResource } from "./api";
import { categoryFor, clock, dateLabel, hourLabel, textOn, whole } from "./format";
import { Loading, Problem } from "./parts";

const CHART = { ink: "#1C2A33", muted: "#4A5A66", grid: "#D5DAD4", first: "#0072B2", second: "#A65A00" };
const AXIS = { fontSize: 13, fill: CHART.muted };

function Gate<T>({ res, what, children }: { res: Resource<T>; what: string; children: (data: T) => JSX.Element }) {
  if (res.data) return children(res.data);
  if (res.error) return <Problem message={res.error} retry={res.retry} />;
  return <Loading what={what} />;
}

function Hero({ now, tomorrow }: { now: Now; tomorrow: number | null }) {
  const color = now.category?.color ?? "#FFFFFF";
  return (
    <header className="hero" style={{ background: color, color: textOn(now.category?.name) }}>
      <a className="back" href="#/map">All cities</a>
      <h1>{now.city}</h1>
      <p className="when">Right now, 24-hour average</p>
      <p className="aqi"><span>{now.aqi ?? "No data"}</span>{now.aqi != null && <small>AQI</small>}</p>
      <p className="cat">{now.category?.name ?? "AQI not available"}</p>
      {now.dominant && <p className="driver">Driven mostly by {now.dominant}</p>}
      {now.check?.warn && <p className="alert" role="alert">{now.check.message}</p>}
      {tomorrow != null && <p className="next">Forecast: about {Math.round(tomorrow)} by this time tomorrow, {categoryFor(tomorrow)?.name}</p>}
    </header>
  );
}

const SCALE = [
  { to: 50, color: "#00B050" }, { to: 100, color: "#92D050" }, { to: 200, color: "#FFFF00" },
  { to: 300, color: "#FF9900" }, { to: 400, color: "#FF0000" }, { to: 500, color: "#C00000" },
];

function Scale({ aqi }: { aqi: number }) {
  let from = 0;
  return (
    <div className="scale" role="img" aria-label={`AQI ${aqi} on the CPCB scale from 0 to 500`}>
      <i className="scale-mark" style={{ left: `${Math.min(aqi, 500) / 5}%` }} />
      <div className="scale-bar">
        {SCALE.map((s) => {
          const width = (s.to - from) / 5;
          from = s.to;
          return <span key={s.to} style={{ width: `${width}%`, background: s.color }} />;
        })}
      </div>
      <div className="scale-ticks" aria-hidden="true">
        {[0, 100, 200, 300, 400, 500].map((n) => <span key={n} style={{ left: `${n / 5}%` }}>{n}</span>)}
      </div>
    </div>
  );
}

function Readings({ now, savedAt }: { now: Now; savedAt: string | null }) {
  const stations = now.official.stations.slice(0, 4);
  return (
    <section className="readings">
      {savedAt && <p className="flag">Could not refresh. Showing data saved {new Date(savedAt).toLocaleString("en-IN")}.</p>}
      {now.stale && <p className="flag">The live feed did not respond, so this is the last saved reading.</p>}
      {now.aqi != null && <Scale aqi={now.aqi} />}
      <p className="caution">
        This is a model estimate. Real stations can read higher or lower, and the gap can be large on smoggy nights.
        If a station near you shows worse air, follow that.
      </p>
      <h2 className="small">What's in the air</h2>
      <ul className="pollutants">
        {now.pollutants.map((p) => (
          <li key={p.id}>
            <strong>{p.label}</strong>
            <span>{p.value ?? "No data"} {p.unit}, {p.window}</span>
            <b>{p.sub_index ?? "?"}</b>
          </li>
        ))}
      </ul>
      <p className="fine">The number on the right is each pollutant's own index. The highest one sets the AQI.</p>
      <p className="fine">{now.source_note} {now.source}. CPCB scale, not the US scale, so values differ from apps that use US AQI. To {clock(now.time)} IST.</p>
      {now.shared_grid_with && (
        <p className="fine">The model gives {now.city} and {now.shared_grid_with} the same air data, so they show the same values here.</p>
      )}
      <h2 className="small">Measured at stations</h2>
      {now.official.available && stations.length > 0 ? (
        <ul className="stations">
          {stations.map((s) => (
            <li key={s.station}><span>{s.station} ({s.provider})</span><strong>PM2.5 {whole(s.pm2_5)} µg/m³{s.time ? `, ${dateLabel(s.time)} ${clock(s.time)}` : ""}</strong></li>
          ))}
        </ul>
      ) : <p className="fine">{now.official.message ?? "No station has data right now."} This page uses the modelled value instead.</p>}
    </section>
  );
}

function Ribbon({ forecast }: { forecast: Forecast }) {
  const best = forecast.best_time;
  const [picked, setPicked] = useState<number | null>(null);
  const hours = forecast.hours;
  const inBest = (t: string) => !!best && t >= best.start && t < best.end;
  const firstBest = hours.findIndex((h) => inBest(h.time));
  const bestCount = hours.filter((h) => inBest(h.time)).length;
  const hour = picked == null ? null : hours[picked];
  const tomorrow = best && best.start.slice(0, 10) !== forecast.issued.slice(0, 10);
  return (
    <section>
      <h2>{best ? `Best time outside ${tomorrow ? "tomorrow" : "today"}: ${hourLabel(best.start)} to ${hourLabel(best.end)}` : "No clear best time today"}</h2>
      {best && <p>Air in that window is about {best.mean_index} on the hourly index, {best.category?.name}. {forecast.timing?.summary}</p>}
      <div className="ribbon" role="group" aria-label="Next 24 hours, one block per hour">
        {hours.map((h, i) => {
          const cat = categoryFor(h.hourly_index);
          return (
            <button key={h.time} type="button" className="cell" style={{ background: cat?.color ?? "#FFFFFF" }}
              aria-label={`${hourLabel(h.time)}, index ${whole(h.hourly_index)}, ${cat?.name ?? "no data"}${inBest(h.time) ? ", best time" : ""}`}
              aria-pressed={picked === i} onClick={() => setPicked(picked === i ? null : i)} />
          );
        })}
        {firstBest >= 0 && (
          <span className="bracket" aria-hidden="true"
            style={{ left: `${(firstBest / hours.length) * 100}%`, width: `${(bestCount / hours.length) * 100}%` }} />
        )}
      </div>
      <div className="ribbon-hours" aria-hidden="true">
        {hours.map((h, i) => (i % 6 === 0 ? <span key={h.time} style={{ left: `${(i / hours.length) * 100}%` }}>{hourLabel(h.time)}</span> : null))}
      </div>
      <p className="readout" aria-live="polite">
        {hour ? `${hourLabel(hour.time)}: index ${whole(hour.hourly_index)}, ${categoryFor(hour.hourly_index)?.name ?? "no data"}` : "Tap an hour to see its value. The bracket marks the best time."}
      </p>
      <p className="fine">{forecast.best_time_note} Forecast from {forecast.source}.</p>
    </section>
  );
}

function ForecastChart({ forecast }: { forecast: Forecast }) {
  const rows = forecast.hours.map((h) => ({ label: hourLabel(h.time), "Open-Meteo": h.open_meteo_pm2_5, AirWatch: h.ours_pm2_5 }));
  const m = forecast.metrics;
  const hasOurs = forecast.hours.some((h) => h.ours_pm2_5 != null);
  return (
    <section>
      <h2>Next 24 hours</h2>
      <p>PM2.5 in µg/m³. {forecast.served === "ours" ? "This page uses our forecast." : "This page uses Open-Meteo's forecast."} {forecast.served_reason}</p>
      <div className="chart">
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" interval={5} tick={AXIS} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={52} />
            <Tooltip formatter={(v: number) => `${Math.round(v)} µg/m³`} />
            <Legend wrapperStyle={{ fontSize: 14, color: CHART.ink }} />
            <Line type="monotone" dataKey="Open-Meteo" stroke={CHART.first} strokeWidth={2} dot={false} />
            {hasOurs && <Line type="monotone" dataKey="AirWatch" stroke={CHART.second} strokeWidth={2} strokeDasharray="6 4" dot={false} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {m.ours && m.persistence && m.test_period && (
        <p className="fine">
          Test, {dateLabel(m.test_period[0])} to {dateLabel(m.test_period[1])}: AirWatch was off by {m.ours.mae} µg/m³ on average,
          against {m.persistence.mae} µg/m³ for assuming no change. Scored against Open-Meteo's own past values, not stations.
        </p>
      )}
    </section>
  );
}

function Contributors({ data, weather }: { data: Sources; weather?: Now["weather"] }) {
  const ranked = data.sources.slice().sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  return (
    <section>
      <h2>Likely contributors</h2>
      <p>{data.note}</p>
      {weather && (
        <dl className="conditions">
          <div><dt>Wind</dt><dd>{whole(weather.wind_kmh)} km/h{weather.wind_from ? ` from ${weather.wind_from}` : ""}</dd></div>
          <div><dt>Humidity</dt><dd>{whole(weather.humidity_pct)}%</dd></div>
          <div><dt>Mixing layer</dt><dd>{whole(weather.mixing_layer_m)} m</dd></div>
        </dl>
      )}
      <ul className="bars">
        {ranked.map((s) => (
          <li key={s.id}>
            <div className="bar-head"><strong>{s.label}</strong><span>{s.level}{s.score != null ? `, ${s.score.toFixed(2)}` : ""}</span></div>
            <div className="bar" role="img" aria-label={`${s.label}: ${s.level}`}><i style={{ width: `${(s.score ?? 0) * 100}%` }} /></div>
            <p>{s.reason}</p>
          </li>
        ))}
      </ul>
      <p className="fine">{data.fires.available ? `${data.fires.source}. ${data.fires.note}` : "Fire data is unavailable right now."}</p>
    </section>
  );
}

const CAUSES: Record<string, { letter: string; label: string }> = {
  crop: { letter: "C", label: "Crop burning" }, vehicles: { letter: "V", label: "Vehicles" },
  dust: { letter: "D", label: "Dust" }, weather: { letter: "W", label: "Weather trapping" },
};

function WhyCalendar({ days }: { days: CalendarDay[] }) {
  const [picked, setPicked] = useState<CalendarDay | null>(null);
  if (days.length === 0) return null;
  const [y, m, d] = days[0].date.split("-").map(Number);
  const blanks = (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7; // weeks start on Monday
  const scored = days.filter((x) => x.crop_scored).length;
  const seen = Object.keys(CAUSES).filter((id) => days.some((x) => x.cause?.id === id));
  return (
    <>
      <h3>This season, day by day</h3>
      <p>Each day shows its AQI and the likeliest cause. Tap a day for details.</p>
      <div className="weekdays" aria-hidden="true">{["M", "T", "W", "T", "F", "S", "S"].map((w, i) => <span key={i}>{w}</span>)}</div>
      <div className="calendar">
        {Array.from({ length: blanks }, (_, i) => <span key={`b${i}`} />)}
        {days.map((day) => (
          <button key={day.date} type="button" className="day" aria-pressed={picked?.date === day.date}
            style={{ background: day.category?.color ?? "#FFFFFF", color: textOn(day.category?.name) }}
            aria-label={`${dateLabel(day.date)}, AQI ${day.aqi ?? "no data"}, ${day.category?.name ?? ""}, ${day.cause ? `likely ${day.cause.label}` : "no clear cause"}`}
            onClick={() => setPicked(picked?.date === day.date ? null : day)}>
            <b>{day.aqi ?? "?"}</b>
            <small>{day.cause ? CAUSES[day.cause.id]?.letter : "–"}</small>
          </button>
        ))}
      </div>
      <p className="readout" aria-live="polite">
        {picked
          ? `${dateLabel(picked.date)}: AQI ${picked.aqi ?? "no data"}, ${picked.category?.name ?? "no data"}. Mostly ${picked.dominant ?? "unknown"}. ${picked.cause ? `Likely cause: ${picked.cause.label} (${picked.cause.score.toFixed(2)}).` : "No clear cause."}`
          : `Key: ${seen.map((id) => `${CAUSES[id].letter} ${CAUSES[id].label}`).join(", ") || "no clear causes yet"}. A dash means no clear cause.`}
      </p>
      <p className="fine">{scored < days.length ? `Crop burning could be scored on ${scored} of ${days.length} days, because fire records don't cover the rest. ` : ""}Causes are estimates.</p>
    </>
  );
}

function Compared({ data }: { data: History }) {
  const { vs_years: years, vs_recent: recent, season } = data;
  const lastYear = years.earlier[0];
  const a = season.this_season;
  const b = season.last_season;
  const rows = data.season_chart.map((r) => ({ label: r.label, "This season": r.this_season, "Last season": r.last_season }));
  const worst = data.notable.this_season[0];
  return (
    <section>
      <h2>Compared with before</h2>
      {season.summary && <p>{season.summary}</p>}
      <WhyCalendar days={data.calendar} />
      <h3>AQI by day, this season and last</h3>
      <div className="chart">
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" interval={Math.max(Math.floor(rows.length / 4), 1)} tick={AXIS} tickLine={false} axisLine={{ stroke: CHART.grid }} />
            <YAxis tick={AXIS} tickLine={false} axisLine={false} width={52} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 14, color: CHART.ink }} />
            <Line type="monotone" dataKey="This season" stroke={CHART.first} strokeWidth={2} dot={false} connectNulls={false} />
            <Line type="monotone" dataKey="Last season" stroke={CHART.second} strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <dl className="facts">
        <div>
          <dt>Same date last year</dt>
          <dd>{lastYear?.available ? `AQI ${lastYear.aqi}, now ${years.day?.aqi ?? "no data"}` : "No data"}</dd>
          {lastYear?.summary && <dd className="sub">{lastYear.summary}</dd>}
        </div>
        <div>
          <dt>Last 7 days</dt>
          <dd>{recent.last_7_days.aqi != null ? `Average AQI ${recent.last_7_days.aqi}, now ${recent.day?.aqi ?? "no data"}` : "No data"}</dd>
          {recent.last_7_days.summary && <dd className="sub">{recent.last_7_days.summary}</dd>}
        </div>
        <div>
          <dt>Last 30 days</dt>
          <dd>{recent.last_30_days.aqi != null ? `Average AQI ${recent.last_30_days.aqi}` : "No data"}</dd>
          {recent.last_30_days.summary && <dd className="sub">{recent.last_30_days.summary}</dd>}
        </div>
        <div>
          <dt>Severe days so far</dt>
          <dd>{a.severe_days} this season, {b.severe_days} last season</dd>
          <dd className="sub">Very Poor: {a.very_poor_days} and {b.very_poor_days}. Poor: {a.poor_days} and {b.poor_days}.</dd>
        </div>
        {worst && (
          <div>
            <dt>Worst day this season</dt>
            <dd>{dateLabel(worst.date)}: AQI {worst.aqi}, {worst.category}</dd>
            <dd className="sub">Driven by {worst.dominant ?? "unknown"}{worst.top_source ? `. Top likely contributor: ${worst.top_source.label}` : ""}.</dd>
          </div>
        )}
      </dl>
      <h3>Fires and next-day PM2.5</h3>
      {season.fire_summary && <p>{season.fire_summary}</p>}
      {data.fire_link.available ? (
        <>
          <p>{data.fire_link.summary}</p>
          {data.fire_link.points && (
            <div className="chart">
              <ResponsiveContainer width="100%" height={200}>
                <ScatterChart margin={{ top: 8, right: 8, bottom: 16, left: -18 }}>
                  <CartesianGrid stroke={CHART.grid} />
                  <XAxis type="number" dataKey="fires" name="Upwind fires" tick={AXIS} label={{ value: "Upwind fires per day", position: "bottom", ...AXIS }} />
                  <YAxis type="number" dataKey="pm2_5" name="PM2.5" unit="" tick={AXIS} width={52} />
                  <Tooltip />
                  <Scatter data={data.fire_link.points} fill={CHART.first} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      ) : <p className="empty">{data.fire_link.reason}</p>}
      <p className="fine">
        {data.window}, {dateLabel(data.range.from, true)} to {dateLabel(data.range.to, true)}. {data.method_note} {data.source}.
        {data.fire_note ? ` ${data.fire_note}` : ""}
      </p>
    </section>
  );
}

function Outlook({ data }: { data: Insights }) {
  const lines = [data.outlook?.summary, data.relief?.summary, data.levers?.summary, data.levers?.rain?.summary, data.limits?.india_summary, data.validation?.summary, data.validation?.peaks, data.validation?.tracking, data.validation?.cleanest?.summary];
  return (
    <section>
      <h2>What happens next</h2>
      <ul className="insights">{lines.filter(Boolean).map((line) => <li key={line}>{line}</li>)}</ul>
      <p className="fine">{data.source}</p>
    </section>
  );
}

function Advice({ now }: { now: Now }) {
  if (!now.advice_category) return null;
  return (
    <section>
      <h2>What to do now</h2>
      <p>For air that is {now.advice_category.name}{now.check?.warn ? ", based on what stations measured" : ""}. If stations near you show worse air, follow the advice for that category.</p>
      <dl className="advice">
        {now.advice.map((a) => (<div key={a.id}><dt>{a.title}</dt><dd>{a.text}</dd></div>))}
      </dl>
      <p className="fine">{now.advice_note}</p>
    </section>
  );
}

export function CityPage({ id }: { id: string }) {
  const now = useResource<Now>(`/api/city/${id}/now`);
  const forecast = useResource<Forecast>(`/api/city/${id}/forecast`);
  const sources = useResource<Sources>(`/api/city/${id}/sources`);
  const history = useResource<History>(`/api/city/${id}/history`);
  const insights = useResource<Insights>(`/api/city/${id}/insights`);
  const issued = forecast.data?.issued;
  return (
    <main className="city">
      {now.data ? <Hero now={now.data} tomorrow={forecast.data?.hours[forecast.data.hours.length - 1]?.aqi ?? null} /> : (
        <header className="hero plain">
          <a className="back" href="#/map">All cities</a>
          {now.error ? <Problem message={now.error} retry={now.retry} /> : <Loading what="current air" />}
        </header>
      )}
      <div className="column">
        {now.data && <Readings now={now.data} savedAt={now.savedAt} />}
        <Gate res={forecast} what="forecast">{(f) => <><Ribbon forecast={f} /><ForecastChart forecast={f} /></>}</Gate>
        <Gate res={sources} what="likely contributors">{(s) => <Contributors data={s} weather={now.data?.weather} />}</Gate>
        <Gate res={history} what="past comparisons">{(h) => <Compared data={h} />}</Gate>
        <Gate res={insights} what="what happens next">{(i) => <Outlook data={i} />}</Gate>
        {now.data && <Advice now={now.data} />}
        {issued && <p className="fine end">Forecast issued {clock(issued)} IST. Estimates only: check official sources for decisions that matter.</p>}
      </div>
    </main>
  );
}
