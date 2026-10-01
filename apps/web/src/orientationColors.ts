const COLORS = ["#a874d7", "#e884a9", "#4f9bad", "#d69b54", "#75a075", "#7d83c9", "#c77b72", "#b18e54"];

export function orientationColor(group: number): string {
  return COLORS[group % COLORS.length] ?? "#a874d7";
}
