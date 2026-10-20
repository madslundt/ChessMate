import { useT } from "./i18n";
import type { Candidate, Preferences } from "./types";
export function equivalentCandidate(
  candidate: Candidate,
  best: Candidate,
): boolean {
  if (candidate.similar_to_best !== undefined) return candidate.similar_to_best;
  return (
    candidate.mate == null &&
    best.mate == null &&
    candidate.cp != null &&
    best.cp != null &&
    Math.abs(candidate.cp - best.cp) <= 35
  );
}
/** Positional effects remain interpretations; engine ranking alone never proves their causal importance. */
export function CandidateDetails({
  candidate,
  preferences,
  similar,
}: {
  candidate: Candidate;
  preferences: Preferences;
  similar: boolean;
}) {
  const t = useT();
  return (
    <>
      {similar && (
        <small className="muted candidate-equivalence">
          {t("similarCandidates")}
        </small>
      )}
      <details
        className="candidate-details"
        open={
          preferences.complexity !== "beginner" &&
          preferences.explanation_mode !== "visual"
        }
      >
        <summary>{t("candidateDetails")}</summary>
        {candidate.reply && (
          <p>
            <strong>{t("opponentReply")}:</strong> {candidate.reply}
          </p>
        )}
        {candidate.strategy?.plan && (
          <p>
            <strong>{t("candidatePlan")}:</strong> {candidate.strategy.plan}
          </p>
        )}
        {!!candidate.strategy?.advantages?.length && (
          <>
            <strong>{t("positionalAdvantages")}</strong>
            <ul>
              {candidate.strategy.advantages.slice(0, 2).map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </>
        )}
        {!!candidate.strategy?.drawbacks?.length && (
          <>
            <strong>{t("positionalDrawbacks")}</strong>
            <ul>
              {candidate.strategy.drawbacks.slice(0, 2).map((text) => (
                <li key={text}>{text}</li>
              ))}
            </ul>
          </>
        )}
        {candidate.risk && <p>{candidate.risk}</p>}
        {candidate.strategy?.qualification && (
          <small className="muted">{t("interpretationQualification")}</small>
        )}
      </details>
    </>
  );
}
