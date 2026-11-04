import "./story.css";

import { ScoreboardData, useResource } from "../api";
import { Loading, Problem } from "../parts";

const pct = (a: number, b: number) => (b ? Math.round((a / b) * 100) : 0);

export function Accuracy() {
  const res = useResource<ScoreboardData>("/api/scoreboard");
  const data = res.data;
  const total = data?.warning_total;
  return (
    <main className="s-acc">
      <p><a href="#/delhi">Back to AirWatch</a></p>
      <h1>How accurate is AirWatch?</h1>
      <p className="s-lead">Every number we can check, including where we fall short.</p>
      {res.error && <Problem message={res.error} retry={res.retry} />}
      {!data && !res.error && <Loading what="scoreboard" />}
      {total && (
        <section>
          <h2>Does the station warning work?</h2>
          <div className="s-stats">
            <div><b>{total.under_before} to {total.under_after}</b><span>days we showed cleaner air than stations measured</span></div>
            <div><b>{pct(total.fired_right, total.fired)}%</b><span>of warnings were right ({total.fired_right} of {total.fired})</span></div>
            <div><b>{total.over_before.toLocaleString("en-IN")} to {total.over_after.toLocaleString("en-IN")}</b><span>days we showed worse air than stations measured</span></div>
          </div>
          <p className="s-fine">Replayed at noon on {total.days.toLocaleString("en-IN")} past city-days, using only readings at least 18 hours old. Stations give PM2.5 only, while our AQI counts other pollutants too, so the last figure runs high either way.</p>
        </section>
      )}
      {data && (
        <section>
          <h2>The model against real CPCB stations</h2>
          <p>PM2.5 in µg/m³, this season so far. Averages are fairly close, but the model understates the worst hours in {data.cities.filter((c) => c.stations?.understates_peaks).length} of the {data.cities.filter((c) => c.stations).length} cities we can check.</p>
          <div className="s-scroll">
            <table>
              <thead>
                <tr><th>City</th><th>Average: stations</th><th>Average: model</th><th>Worst hours: stations</th><th>Worst hours: model</th><th>Tracks daily changes (r)</th><th>Warning right</th></tr>
              </thead>
              <tbody>
                {data.cities.map((c) => (
                  <tr key={c.id}>
                    <th><a href={`#/${c.id}`}>{c.name}</a></th>
                    {c.stations ? (
                      <>
                        <td>{c.stations.real_pm}</td><td>{c.stations.model_pm}</td>
                        <td>{c.stations.worst_real}</td>
                        <td className={c.stations.understates_peaks ? "low" : undefined}>{c.stations.worst_model}{c.stations.understates_peaks ? " (too low)" : ""}</td>
                        <td>{c.stations.daily_r}</td>
                        <td>{c.warning ? `${c.warning.fired_right} of ${c.warning.fired}` : "No data"}</td>
                      </>
                    ) : <td colSpan={6}>No station PM2.5 data available</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <h2>Our forecast against Open-Meteo</h2>
          <p>Average error in µg/m³ on live hours after the forecast was made. This is one forecast run, a very small test, scored against Open-Meteo's own later values, which favours it.</p>
          <div className="s-scroll">
            <table>
              <thead><tr><th>City</th><th>AirWatch</th><th>Open-Meteo</th><th>Shown on the site</th></tr></thead>
              <tbody>
                {data.cities.map((c) => (
                  <tr key={c.id}>
                    <th>{c.name}</th><td>{c.ours_live?.mae ?? "No data"}</td><td>{c.open_meteo_live?.mae ?? "No data"}</td>
                    <td>{c.served === "ours" ? "AirWatch" : "Open-Meteo"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="s-fine">{data.note} AQI on this site is modelled, not official.</p>
        </section>
      )}
    </main>
  );
}
