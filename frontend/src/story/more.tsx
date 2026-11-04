import { useRef, useState } from "react";

import { LeagueData, Plan, useResource } from "../api";
import { dateLabel } from "../format";
import { Loading, Problem } from "../parts";
import { show } from "./chapters";
import { span, useProgress } from "./scroll";
import type { Bundle } from "./Story";

/** Pick an activity to see the best slot and what moving it saves. */
export function Planner({ data }: { data: Bundle }) {
  const { forecast, now } = data;
  const plans = forecast.plans;
  const [chosen, setChosen] = useState<Plan | undefined>(plans[0]);
  const section = useRef<HTMLElement>(null);
  const result = useRef<HTMLDivElement>(null);
  useProgress(section, (p) => show(result.current, span(p, 0.08, 0.3)));
  if (!chosen) return null;
  const tomorrow = chosen.date !== forecast.issued.slice(0, 10);
  // What stations measured outranks the forecast, so the verdict can never sound safer than the warning.
  const measured = now.check?.warn ? now.check.category.name : null;
  const headline = measured === "Severe" || measured === "Very Poor" ? "Better indoors today" : measured ? "Keep it short" : chosen.verdict;
  return (
    <section ref={section} className="chapter" style={{ height: "190vh" }}>
      <div className="stick s-plan">
        <div className="s-wide">
          <h2>Should I go out?</h2>
          <p>Pick what you're planning in {now.city}.</p>
          <div className="s-choices" role="group" aria-label="Choose an activity">
            {plans.map((plan) => (
              <button key={plan.id} type="button" aria-pressed={plan.id === chosen.id} onClick={() => setChosen(plan)}>{plan.label}</button>
            ))}
          </div>
          <div ref={result} className="s-answer" aria-live="polite">
            <b>{headline}</b>
            <p className="s-big">{measured ? "If you do go, the best time is " : "Best time: "}{chosen.best}{tomorrow ? ` on ${dateLabel(chosen.date)}` : " today"}</p>
            <p>{chosen.summary}</p>
            {measured && <p className="s-reason">Stations measured {measured} air, worse than this forecast, so we've gone with the stations.</p>}
          </div>
          <p className="s-fine">Based on the next 24 hours from {forecast.source}. General guidance only, not medical advice.</p>
        </div>
      </div>
    </section>
  );
}

/** All eight cities ranked, each with what stations measured beside the estimate. */
export function League({ current }: { current: string }) {
  const res = useResource<LeagueData>("/api/league");
  const section = useRef<HTMLElement>(null);
  const bars = useRef<(HTMLElement | null)[]>([]);
  const rows = res.data?.cities ?? [];
  const top = Math.max(1, ...rows.map((r) => r.aqi ?? 0));
  useProgress(section, (p) => {
    rows.forEach((r, i) => {
      const bar = bars.current[i];
      if (bar) bar.style.transform = `scaleX(${((r.aqi ?? 0) / top) * span(p, 0.03 + i * 0.07, 0.18 + i * 0.07)})`;
    });
  });
  return (
    <section ref={section} className="chapter" style={{ height: "230vh" }}>
      <div className="stick s-league">
        <div className="s-wide">
          <h2>How the cities compare right now</h2>
          {res.error && <Problem message={res.error} retry={res.retry} />}
          {!res.data && !res.error && <Loading what="all cities" />}
          <ol>
            {rows.map((r, i) => (
              <li key={r.id} className={r.id === current ? "here" : undefined}>
                <a href={`#/${r.id}`}>{i + 1}. {r.name}</a>
                <div className="s-lbar"><i ref={(e) => { bars.current[i] = e; }} style={{ background: r.category?.color ?? "#FFFFFF" }} /></div>
                <strong>{r.aqi ?? "?"} {r.category?.name}</strong>
                <span>{r.check ? `${r.check.warn ? "Measured worse: " : "Measured: "}${r.check.category.name}` : r.has_stations ? "Not enough recent readings" : "No stations available"}</span>
              </li>
            ))}
          </ol>
          <p className="s-fine">AQI is modelled, CPCB scale. "Measured" is the latest 24-hour PM2.5 average from nearby stations. Gurugram and Noida share model data.</p>
        </div>
      </div>
    </section>
  );
}
