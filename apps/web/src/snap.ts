/** Pointer gestures get gentle guides; typed coordinates remain exact. */
export function snapAngle(angle: number, strict = false): number {
  const target = Math.round(angle / 5) * 5;
  return strict || Math.abs(angle - target) <= 1 ? target : angle;
}
