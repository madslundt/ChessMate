import { useT, type TranslationKey } from "./i18n";
import type { CoachingState } from "./types";
const stages: Record<string, TranslationKey> = {
  notice: "stageNotice",
  identify: "stageIdentify",
  calculate: "stageCalculate",
  evaluate: "stageEvaluate",
  reflect: "stageReflect",
};
export function SocraticProgress({ state }: { state: CoachingState }) {
  const t = useT();
  return (
    <section className="socratic-progress" aria-label={t("guidedDiscovery")}>
      <strong>{t(stages[state.stage] || "guidedDiscovery")}</strong>
      <small>
        {t("discoveredFacts")}: {state.discovered_ids.length}
      </small>
      {state.acknowledgement && <p>{state.acknowledgement}</p>}
      {state.question && <p>{state.question}</p>}
    </section>
  );
}
