import "@fontsource-variable/anek-latin/wdth.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { registerSW } from "virtual:pwa-register";

import { CityPage } from "./CityPage";
import { MapHome } from "./MapHome";
import { Boundary } from "./parts";
import { CITY_NAMES, Story } from "./story/Story";

registerSW({ immediate: true });

function App() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  const detail = hash.match(/^#\/city\/([a-z]+)$/);
  if (detail) return <CityPage id={detail[1]} />;
  if (hash === "#/map") return <MapHome />;
  const city = hash.match(/^#\/([a-z]+)$/)?.[1];
  return <Story id={city && city in CITY_NAMES ? city : "delhi"} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Boundary>
      <App />
    </Boundary>
  </StrictMode>,
);
