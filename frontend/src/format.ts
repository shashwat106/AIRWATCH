/** Backend times are India wall-clock strings, so they are read as text and never shifted by the viewer's timezone. */
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const hourOf = (iso: string) => Number(iso.slice(11, 13));

export function hourLabel(iso: string): string {
  const h = hourOf(iso);
  if (h === 0) return "12 am";
  if (h === 12) return "12 pm";
  return h < 12 ? `${h} am` : `${h - 12} pm`;
}

export function dateLabel(iso: string, withYear = false): string {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${d} ${MONTHS[m - 1]}${withYear ? ` ${y}` : ""}`;
}

export const clock = (iso: string) => iso.slice(11, 16);

export const whole = (n: number | null | undefined) => (n == null ? "No data" : Math.round(n).toLocaleString("en-IN"));

const CATEGORY_LIMITS: [number, string, string][] = [
  [50, "Good", "#00B050"], [100, "Satisfactory", "#92D050"], [200, "Moderately Polluted", "#FFFF00"],
  [300, "Poor", "#FF9900"], [400, "Very Poor", "#FF0000"], [Infinity, "Severe", "#C00000"],
];

export function categoryFor(value: number | null): { name: string; color: string } | null {
  if (value == null) return null;
  const hit = CATEGORY_LIMITS.find(([limit]) => value <= limit)!;
  return { name: hit[1], color: hit[2] };
}

/** Text colour that stays readable on each CPCB colour. */
export const textOn = (name?: string) => (name === "Very Poor" || name === "Severe" ? "#FFFFFF" : "#1C2A33");
