import { useRef, useState, type KeyboardEvent } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CalendarDays, ChevronLeft, ChevronRight, FileText, RefreshCw } from 'lucide-react';
import { api } from './api';
import { ErrorNotice, Field, PageHeading, Spinner } from './components';
import { useT } from './i18n';
import type { Preferences } from './types';
import { DiaryEvidence, type DiaryContent } from './DiaryEvidence';
export { DiaryEvidence } from './DiaryEvidence';
export type { DiaryStatistics, DiaryObservation, DiaryContent } from './DiaryEvidence';
import { monthDays, presetRange, shiftMonth, todayInTimezone, type ReportPreset } from './diaryCalendar';

interface CalendarData {
  month: string;
  timezone: string;
  days: { date: string; game_count: number; status: string }[];
}

export function Diary({ preferences }: { preferences: Preferences }) {
  const t = useT(),
    client = useQueryClient();
  const locale = preferences.language === 'da' ? 'da-DK' : 'en-GB';
  const today = todayInTimezone(preferences.timezone || 'UTC');
  const [month, setMonth] = useState(today.slice(0, 7));
  const [selected, setSelected] = useState<string | null>(null);
  const [range, setRange] = useState(() => presetRange('30', today));
  const [report, setReport] = useState<DiaryContent | null>(null);
  const [reportsPage, setReportsPage] = useState(0);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<unknown>(null);
  const calendar = useQuery({
    queryKey: ['diary-calendar', month],
    queryFn: ({ signal }) => api<CalendarData>(`/diary/calendar?month=${month}`, undefined, undefined, signal),
    refetchInterval: 30000,
  });
  const day = useQuery({
    queryKey: ['diary-day', selected],
    queryFn: ({ signal }) => api<DiaryContent>(`/diary/days/${selected}`, undefined, undefined, signal),
    enabled: !!selected,
    retry: false,
    refetchInterval: (query) =>
      query.state.data && ['pending', 'partial'].includes(query.state.data.status) ? 5000 : false,
  });
  const reports = useQuery({
    queryKey: ['diary-reports', reportsPage],
    queryFn: () => api<DiaryContent[]>(`/diary/reports?offset=${reportsPage * 20}&limit=20`),
  });
  const activity = new Map(calendar.data?.days.map((item) => [item.date, item]));
  async function action(operation: () => Promise<DiaryContent>, isReport = false) {
    setBusy(true);
    setError(null);
    try {
      const result = await operation();
      if (isReport) {
        setReport(result);
        void client.invalidateQueries({ queryKey: ['diary-reports'] });
      } else {
        client.setQueryData(['diary-day', selected], result);
        void client.invalidateQueries({ queryKey: ['diary-calendar'] });
      }
    } catch (failure) {
      setError(failure);
    } finally {
      setBusy(false);
    }
  }
  const weekdays = Array.from({ length: 7 }, (_, index) =>
    new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(new Date(2024, 0, 1 + index, 12)),
  );
  return (
    <>
      <PageHeading title={t('diary')} subtitle={t('diaryHelp')} />
      <ErrorNotice error={error || calendar.error || reports.error} />
      <div className="diary-layout">
        <section className="panel diary-calendar-panel" aria-label={t('activityCalendar')}>
          <div className="diary-month-nav">
            <button
              className="icon-button"
              aria-label={t('previousMonth')}
              onClick={() => setMonth(shiftMonth(month, -1))}
            >
              <ChevronLeft size={20} />
            </button>
            <Field label={t('month')}>
              <input
                type="month"
                min="1900-01"
                max="9998-12"
                value={month}
                onChange={(event) => {
                  if (/^\d{4}-\d{2}$/.test(event.target.value)) setMonth(event.target.value);
                }}
              />
            </Field>
            <button className="icon-button" aria-label={t('nextMonth')} onClick={() => setMonth(shiftMonth(month, 1))}>
              <ChevronRight size={20} />
            </button>
          </div>
          {calendar.isPending ? (
            <Spinner />
          ) : (
            <CalendarGrid
              month={month}
              selected={selected}
              weekdays={weekdays}
              activity={activity}
              language={preferences.language}
              onSelect={setSelected}
            />
          )}
          <small className="muted">
            {t('calendarTimezone')}: {calendar.data?.timezone || preferences.timezone || 'UTC'}
          </small>
        </section>
        <section className="panel diary-detail" aria-live="polite">
          {!selected ? (
            <div className="diary-empty">
              <CalendarDays size={30} />
              <h2>{t('chooseDay')}</h2>
              <p>{t('chooseDayHelp')}</p>
            </div>
          ) : (
            <>
              <div className="diary-detail-heading">
                <h2>
                  {new Intl.DateTimeFormat(locale, {
                    dateStyle: 'long',
                  }).format(new Date(`${selected}T12:00:00`))}
                </h2>
                <button
                  className="icon-button"
                  aria-label={t('regenerateDiary')}
                  disabled={busy}
                  onClick={() => void action(() => api(`/diary/days/${selected}/regenerate`, {}))}
                >
                  <RefreshCw size={17} />
                </button>
              </div>
              <ErrorNotice error={day.error} />
              {day.isPending ? (
                <Spinner />
              ) : day.data ? (
                <DiaryEvidence content={day.data} preferences={preferences} />
              ) : null}
            </>
          )}
        </section>
      </div>
      <section className="panel diary-reports">
        <h2>
          <FileText size={21} /> {t('progressReports')}
        </h2>
        <p className="muted">{t('reportsHelp')}</p>
        <div className="diary-presets">
          {(['7', '30', 'month', 'previous'] as ReportPreset[]).map((preset) => (
            <button key={preset} className="outline-button" onClick={() => setRange(presetRange(preset, today))}>
              {t(
                preset === '7'
                  ? 'last7Days'
                  : preset === '30'
                    ? 'last30Days'
                    : preset === 'month'
                      ? 'thisMonth'
                      : 'previousMonth',
              )}
            </button>
          ))}
        </div>
        <form
          className="diary-range"
          onSubmit={(event) => {
            event.preventDefault();
            void action(() => api('/diary/reports', range), true);
          }}
        >
          <Field label={t('startDate')}>
            <input
              type="date"
              required
              max={range.end_date}
              value={range.start_date}
              onChange={(event) => setRange({ ...range, start_date: event.target.value })}
            />
          </Field>
          <Field label={t('endDate')}>
            <input
              type="date"
              required
              min={range.start_date}
              value={range.end_date}
              onChange={(event) => setRange({ ...range, end_date: event.target.value })}
            />
          </Field>
          <button
            className="primary-button"
            disabled={busy || !range.start_date || !range.end_date || range.start_date > range.end_date}
          >
            {busy ? <Spinner /> : <FileText size={17} />}
            {t('generateReport')}
          </button>
        </form>
        {report && (
          <article className="diary-report-detail">
            <div className="diary-detail-heading">
              <h3>
                {report.start_date} — {report.end_date}
              </h3>
              <button
                className="outline-button"
                disabled={busy}
                onClick={() => void action(() => api(`/diary/reports/${report.id}/regenerate`, {}), true)}
              >
                {t('regenerateReport')}
              </button>
            </div>
            {report.outdated && <p role="status">{t('reportOutdated')}</p>}
            <DiaryEvidence content={report} preferences={preferences} />
          </article>
        )}
        <details>
          <summary>{t('savedReports')}</summary>
          <div className="diary-saved-reports">
            {reports.data?.map((item) => (
              <button
                key={item.id}
                className="lesson-row"
                disabled={busy}
                onClick={() => void action(() => api(`/diary/reports/${item.id}`), true)}
              >
                <span>
                  {item.start_date} — {item.end_date}
                </span>
                <ChevronRight size={17} />
              </button>
            ))}
          </div>
          <div className="diary-presets">
            <button
              className="outline-button"
              disabled={reportsPage === 0 || reports.isFetching}
              onClick={() => setReportsPage((value) => value - 1)}
            >
              {t('previousPage')}
            </button>
            <span>{reportsPage + 1}</span>
            <button
              className="outline-button"
              disabled={(reports.data?.length || 0) < 20 || reports.isFetching}
              onClick={() => setReportsPage((value) => value + 1)}
            >
              {t('nextPage')}
            </button>
          </div>
        </details>
      </section>
    </>
  );
}

export function CalendarGrid({
  month,
  selected,
  weekdays,
  activity,
  language,
  onSelect,
}: {
  month: string;
  selected: string | null;
  weekdays: string[];
  activity: Map<string, { game_count: number; status: string }>;
  language: 'en' | 'da';
  onSelect: (date: string) => void;
}) {
  const t = useT(),
    buttons = useRef(new Map<string, HTMLButtonElement>());
  const days = monthDays(month),
    activeDays = days.filter((date): date is string => !!date && activity.has(date));
  const focusDate = selected && activeDays.includes(selected) ? selected : activeDays[0];
  function onKey(event: KeyboardEvent<HTMLButtonElement>, date: string) {
    const index = activeDays.indexOf(date);
    const offsets: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: 7,
      ArrowUp: -7,
    };
    let target: string | undefined;
    if (event.key === 'Home') target = activeDays[0];
    else if (event.key === 'End') target = activeDays.at(-1);
    else if (event.key in offsets) {
      const nextIndex = Math.max(0, Math.min(days.length - 1, days.indexOf(date) + offsets[event.key]));
      const next = days[nextIndex];
      target =
        next && activity.has(next)
          ? next
          : activeDays[Math.max(0, Math.min(activeDays.length - 1, index + Math.sign(offsets[event.key])))];
    }
    if (target) {
      event.preventDefault();
      buttons.current.get(target)?.focus();
    }
  }
  return (
    <div className="diary-calendar" role="group" aria-label={t('activityCalendar')}>
      {weekdays.map((name, index) => (
        <span key={index} className="diary-weekday" aria-hidden="true">
          {name}
        </span>
      ))}
      {days.map((date, index) =>
        !date ? (
          <span key={`blank-${index}`} />
        ) : (
          <button
            type="button"
            key={date}
            ref={(element) => {
              if (element) buttons.current.set(date, element);
              else buttons.current.delete(date);
            }}
            className={`diary-date ${activity.has(date) ? 'has-activity' : ''} ${selected === date ? 'selected' : ''}`}
            data-intensity={Math.min(4, activity.get(date)?.game_count || 0)}
            aria-label={`${date}: ${activity.get(date)?.game_count || 0} ${language === 'da' ? 'partier' : 'games'}`}
            aria-pressed={date === selected}
            disabled={!activity.has(date)}
            tabIndex={date === focusDate ? 0 : -1}
            onKeyDown={(event) => onKey(event, date)}
            onClick={() => onSelect(date)}
          >
            <span>{Number(date.slice(-2))}</span>
            {activity.has(date) && <small>{activity.get(date)!.game_count}</small>}
          </button>
        ),
      )}
    </div>
  );
}
