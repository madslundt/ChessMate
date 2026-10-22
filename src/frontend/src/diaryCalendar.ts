export function dateKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function todayInTimezone(timezone = 'UTC', now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(now);
  const part = (name: string) => parts.find((item) => item.type === name)!.value;
  return `${part('year')}-${part('month')}-${part('day')}`;
}
export function monthDays(month: string): (string | null)[] {
  const [year, number] = month.split('-').map(Number);
  const first = new Date(year, number - 1, 1, 12);
  const count = new Date(year, number, 0, 12).getDate();
  const days: (string | null)[] = Array.from({ length: (first.getDay() + 6) % 7 }, () => null);
  for (let day = 1; day <= count; day++) days.push(`${month}-${String(day).padStart(2, '0')}`);
  while (days.length % 7) days.push(null);
  return days;
}
export function shiftMonth(month: string, amount: number): string {
  const [year, number] = month.split('-').map(Number);
  return dateKey(new Date(year, number - 1 + amount, 1, 12)).slice(0, 7);
}
export type ReportPreset = '7' | '30' | 'month' | 'previous';
export function presetRange(preset: ReportPreset, today: string): { start_date: string; end_date: string } {
  const [year, month, day] = today.split('-').map(Number);
  const end = new Date(year, month - 1, day, 12);
  if (preset === 'previous')
    return {
      start_date: dateKey(new Date(year, month - 2, 1, 12)),
      end_date: dateKey(new Date(year, month - 1, 0, 12)),
    };
  const start =
    preset === 'month' ? new Date(year, month - 1, 1, 12) : new Date(year, month - 1, day - Number(preset) + 1, 12);
  return { start_date: dateKey(start), end_date: dateKey(end) };
}
export function positionPath(gameId: string, ply: number): string {
  return `/analyze/${encodeURIComponent(gameId)}?ply=${Math.max(0, Math.floor(ply))}`;
}
