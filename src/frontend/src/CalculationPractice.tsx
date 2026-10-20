import { useEffect, useRef, useState } from "react";
import { CalculationBoard } from "./CalculationBoard";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { api } from "./api";
import { ErrorNotice, Spinner } from "./components";
import { legalVariation } from "./exploration";
import { useT } from "./i18n";
import type { Candidate, Color, Preferences } from "./types";

interface CalculationResult {
  fen: string;
  text: string;
  first_inaccuracy_ply: number | null;
  final_evaluation?: "winning" | "balanced" | "losing";
  assessment_agrees?: boolean | null;
  steps: {
    ply: number;
    classification: string;
    confidence?: string;
    move: string;
    san?: string;
    best_move?: string;
    reply?: string;
    explanation: string;
  }[];
}
/** Calculation is assessed from the same root without submitting a real game move. */
export function CalculationPractice({
  orientation,
  fen,
  preferences,
  onPreview,
  onCommitCandidate,
  revision,
  hintLevel = 0,
}: {
  fen: string;
  orientation?: Color;
  revision: number;
  hintLevel?: number;
  onCommitCandidate?: (
    uci: string,
    base: string,
    revision: number,
  ) => Promise<void>;
  preferences: Preferences;
  onPreview: (candidate: Candidate, baseFen?: string) => void;
}) {
  const t = useT();
  const [prediction, setPrediction] = useState("");
  const [result, setResult] = useState<CalculationResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [line, setLine] = useState<string[]>([]);
  const [expected, setExpected] = useState("");
  const request = useRef<AbortController | null>(null);
  const rootRevision = useRef(revision);
  const [boardEntry, setBoardEntry] = useState(true);
  useEffect(() => () => request.current?.abort(), []);
  async function check() {
    const moves = prediction
      .replace(/\d+\.(?:\.\.)?/g, "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    const legal = legalVariation(fen, moves);
    if (!moves.length || moves.length > 32 || legal.length !== moves.length) {
      setError(
        new Error(
          moves.length > 32 ? t("calculationLimit") : t("calculationIllegal"),
        ),
      );
      return;
    }
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const assessment = await api<CalculationResult>(
        "/calculation",
        {
          fen,
          moves: legal,
          time_ms: Math.min(preferences.analysis_time_ms, 500),
          language: preferences.coach_language,
          hint_level: hintLevel,
          ...(expected ? { expected_evaluation: expected } : {}),
        },
        undefined,
        controller.signal,
      );
      if (!controller.signal.aborted && assessment.fen === fen) {
        setResult(assessment);
        setLine(legal);
      }
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure);
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  return (
    <div className="calculation-practice">
      <p>{t("calculationHelp")}</p>
      <button
        className="text-button"
        aria-expanded={boardEntry}
        onClick={() => setBoardEntry(!boardEntry)}
      >
        {t("buildLineOnBoard")}
      </button>
      {boardEntry && (
        <CalculationBoard
          orientation={orientation}
          base={fen}
          notation={prediction}
          onLine={(line) => {
            setPrediction(line.join(" "));
            setResult(null);
          }}
          preferences={preferences}
          disabled={busy}
        />
      )}
      <label htmlFor="predicted-line">{t("predictedLine")}</label>
      <input
        id="predicted-line"
        value={prediction}
        disabled={busy}
        onChange={(event) => {
          setPrediction(event.target.value);
          setResult(null);
          setError(null);
        }}
        placeholder="e4 e5 Nf3"
        maxLength={500}
      />
      <label htmlFor="predicted-assessment">{t("predictedAssessment")}</label>
      <select
        id="predicted-assessment"
        value={expected}
        disabled={busy}
        onChange={(event) => {
          setExpected(event.target.value);
          setResult(null);
        }}
      >
        <option value="">{t("optional")}</option>
        <option value="winning">{t("positionWinning")}</option>
        <option value="balanced">{t("positionBalanced")}</option>
        <option value="losing">{t("positionLosing")}</option>
      </select>
      <button
        className="outline-button"
        disabled={busy || !prediction.trim()}
        onClick={() => void check()}
      >
        {busy ? <Spinner label={t("thinking")} /> : t("checkCalculation")}
      </button>
      {result && (
        <div role="status">
          <p>{result.text}</p>
          {result.final_evaluation && (
            <p>
              {t("searchAssessment")}:{" "}
              {t(
                result.final_evaluation === "winning"
                  ? "positionWinning"
                  : result.final_evaluation === "losing"
                    ? "positionLosing"
                    : "positionBalanced",
              )}
            </p>
          )}
          {result.first_inaccuracy_ply != null && (
            <p>
              {t("firstCalculationError")}: {result.first_inaccuracy_ply}
            </p>
          )}
          {onCommitCandidate && line[0] && (
            <button
              className="primary-button"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onCommitCandidate(line[0], fen, rootRevision.current);
                } catch (failure) {
                  setError(failure);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t("commitCalculatedCandidate")}
            </button>
          )}
          <ol>
            {result.steps.map((step) => (
              <li key={step.ply}>
                <strong>{step.san || step.move}</strong> · {step.explanation}
                <ConfidenceBadge confidence={step.confidence} />
              </li>
            ))}
          </ol>
          <button
            className="text-button"
            onClick={() =>
              onPreview(
                {
                  uci: line[0],
                  san: t("predictedLine"),
                  cp: null,
                  mate: null,
                  pv: [],
                  pv_uci: line,
                },
                fen,
              )
            }
          >
            {t("showOnBoard")}
          </button>
        </div>
      )}
      <ErrorNotice error={error} onDismiss={() => setError(null)} />
    </div>
  );
}
