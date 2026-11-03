import maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";

import { MapCity, MapView, useResource } from "./api";
import { dateLabel, textOn, whole } from "./format";
import { Problem } from "./parts";

const STYLE = "https://tiles.openfreemap.org/styles/positron";
// Nearby cities sit within a few pixels of each other at this zoom, so they spread out and rejoin as you zoom in.
const FAN: Record<string, [number, number]> = {
  delhi: [-30, -34], gurugram: [-34, 34], noida: [34, 34], ghaziabad: [34, -34],
  lucknow: [26, -22], kanpur: [-26, 22], ludhiana: [-22, -4], chandigarh: [24, 6],
};

function markerHtml(city: MapCity) {
  const fill = city.category?.color ?? "#FFFFFF";
  const arrow = city.wind_from_deg == null ? "" : `
    <svg class="wind" viewBox="0 0 24 24" style="transform: rotate(${(city.wind_from_deg + 180) % 360}deg)" aria-hidden="true">
      <path d="M12 2 L18 14 H13.5 V22 H10.5 V14 H6 Z"/>
    </svg>`;
  return `${arrow}<span class="dot" style="background:${fill};color:${textOn(city.category?.name)}">${city.aqi ?? "?"}</span><span class="name">${city.name}</span>`;
}

export function MapHome() {
  const holder = useRef<HTMLDivElement>(null);
  const map = useRef<maplibregl.Map | null>(null);
  const markers = useRef<{ id: string; marker: maplibregl.Marker }[]>([]);
  const [ready, setReady] = useState(false);
  const [mapFailed, setMapFailed] = useState(false);
  const [day, setDay] = useState<string | null>(null);
  const [days, setDays] = useState<string[]>([]);
  const [playing, setPlaying] = useState(false);
  const view = useResource<MapView>(day ? `/api/map?date=${day}` : "/api/map");

  useEffect(() => {
    if (!holder.current) return;
    const instance = new maplibregl.Map({
      container: holder.current, style: STYLE, bounds: [[75.2, 26.0], [81.6, 31.3]],
      fitBoundsOptions: { padding: { top: 90, bottom: 40, left: 40, right: 40 } }, attributionControl: { compact: true },
      dragRotate: false, pitchWithRotate: false,
    });
    instance.touchZoomRotate.disableRotation();
    instance.on("load", () => {
      instance.addSource("fires", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      instance.addLayer({
        id: "fires", type: "circle", source: "fires",
        paint: { "circle-color": "#C8321E", "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, 1.8, 9, 4], "circle-opacity": 0.8 },
      });
      instance.getContainer().querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      setReady(true);
    });
    instance.on("error", (event) => {
      if (!instance.isStyleLoaded() && String(event.error?.message ?? "").length) setMapFailed(true);
    });
    const fan = () => {
      const scale = Math.max(0, Math.min(1, (8.5 - instance.getZoom()) / 2.5));
      markers.current.forEach(({ id, marker }) => {
        const [x, y] = FAN[id] ?? [0, 0];
        marker.setOffset([x * scale, y * scale]);
      });
    };
    instance.on("zoom", fan);
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, []);

  const data = view.data;
  useEffect(() => {
    if (data && days.length === 0) {
      setDays(data.days);
    }
  }, [data, days.length]);

  useEffect(() => {
    const instance = map.current;
    if (!instance || !ready || !data) return;
    const source = instance.getSource("fires") as maplibregl.GeoJSONSource | undefined;
    source?.setData({
      type: "FeatureCollection",
      features: data.fires.map((f) => ({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [f.lon, f.lat] } })),
    });
    markers.current.forEach(({ marker }) => marker.remove());
    const scale = Math.max(0, Math.min(1, (8.5 - instance.getZoom()) / 2.5));
    markers.current = data.cities.map((city) => {
      const el = document.createElement("a");
      el.href = `#/city/${city.id}`;
      el.className = "pin";
      const wind = city.wind_kmh == null ? "wind unknown" : `wind from ${city.wind_from} at ${Math.round(city.wind_kmh)} km/h`;
      el.setAttribute("aria-label", `${city.name}, AQI ${city.aqi ?? "not available"}, ${city.category?.name ?? ""}, ${wind}`);
      el.innerHTML = markerHtml(city);
      const [x, y] = FAN[city.id] ?? [0, 0];
      const marker = new maplibregl.Marker({ element: el, offset: [x * scale, y * scale] }).setLngLat([city.lon, city.lat]).addTo(instance);
      return { id: city.id, marker };
    });
  }, [data, ready]);

  useEffect(() => {
    if (!playing || days.length === 0) return;
    const timer = window.setInterval(() => {
      setDay((current) => {
        const index = days.indexOf(current ?? days[days.length - 1]);
        if (index >= days.length - 1) {
          setPlaying(false);
          return current;
        }
        return days[index + 1];
      });
    }, 1400);
    return () => window.clearInterval(timer);
  }, [playing, days]);

  const shown = day ?? days[days.length - 1];
  const position = shown ? days.indexOf(shown) : 0;
  const togglePlay = () => {
    if (!playing && position >= days.length - 1) setDay(days[0]);
    setPlaying(!playing);
  };

  return (
    <main className="home">
      <div ref={holder} className="map" role="application" aria-label="Map of city air quality, fires and wind" />
      {mapFailed && <p className="map-failed">The map tiles did not load. City readings are listed below.</p>}
      <header className="brand">
        <h1>AirWatch</h1>
        <p>North India air, fires and wind</p>
      </header>
      <section className="sheet" aria-label="Date and cities">
        {view.error && !data ? <Problem message={view.error} retry={view.retry} /> : (
          <>
            <div className="scrub">
              <button type="button" className="play" onClick={togglePlay} disabled={days.length === 0}
                aria-label={playing ? "Pause" : "Play the last 14 days"}>
                {playing ? "Pause" : "Play"}
              </button>
              <div className="scrub-track">
                <label htmlFor="day">
                  <strong>{shown ? dateLabel(shown) : "Loading"}</strong>
                  {data && <span>{data.fires_covered ? `${whole(data.fires.length)} fire detections` : "Fires not available"}</span>}
                </label>
                <input id="day" type="range" min={0} max={Math.max(days.length - 1, 0)} value={Math.max(position, 0)}
                  aria-valuetext={shown ? dateLabel(shown) : undefined}
                  onChange={(e) => { setPlaying(false); setDay(days[Number(e.target.value)]); }} />
              </div>
            </div>
            {data?.fires_note && <p className="note">{data.fires_note}</p>}
            {view.savedAt && <p className="note">Could not refresh. Showing data saved {new Date(view.savedAt).toLocaleString("en-IN")}.</p>}
            <ul className="key" aria-label="Map key">
              <li><i className="k-fire" />Fire detection</li>
              <li><i className="k-wind" />Wind direction</li>
              <li><i className="k-aqi" />AQI, modelled</li>
            </ul>
            <ul className="city-list">
              {data?.cities.slice().sort((a, b) => (b.aqi ?? -1) - (a.aqi ?? -1)).map((city) => (
                <li key={city.id}>
                  <a href={`#/city/${city.id}`}>
                    <span className="swatch" style={{ background: city.category?.color ?? "#FFFFFF", color: textOn(city.category?.name) }}>{city.aqi ?? "?"}</span>
                    <span className="city-name">{city.name}</span>
                    <span className="city-cat">{city.category?.name ?? "No data"}</span>
                  </a>
                </li>
              ))}
            </ul>
            {data && <p className="fine">Nearby cities are spread apart on the map so you can tap them. Zoom in to see true positions. AQI: {data.source}. Fires: {data.fires_meta.source ?? "unavailable"}.</p>}
          </>
        )}
      </section>
    </main>
  );
}
