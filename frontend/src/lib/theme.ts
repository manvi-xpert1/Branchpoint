/**
 * Colours for charts (Recharts needs real colour values, not CSS variables).
 * They match the tokens in styles.css: cream text on a muddy background
 * with glassy cinnamon panels, and one hue per meaning.
 */
export const CHART = {
  axis: "#E8CFAE",
  grid: "rgba(255, 226, 180, .14)",
  info: "#8FB8E0",
  prob: "#CFA6E6",
  ok: "#7CD1AB",
  warn: "#F59A3E",
  bad: "#FF6B81",
  gold: "#E9B85A",
  cream: "#FFF3DC",
  tooltip: {
    background: "rgba(43, 26, 14, .94)", border: "1px solid rgba(255, 214, 170, .3)", borderRadius: 12,
    color: "#FFF3DC", fontSize: 12.5,
  } as React.CSSProperties,
  /** One colour per series, for line charts with several entities. */
  series: ["#E9B85A", "#8FB8E0", "#7CD1AB", "#CFA6E6", "#F59A3E", "#FF8FA3", "#C9AE85", "#9FE0E0"],
};
