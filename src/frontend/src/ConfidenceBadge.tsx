import { useT, type TranslationKey } from "./i18n";
const labels: Record<string, TranslationKey> = {
  engine_estimate: "confidenceSearch",
  search_estimate: "confidenceSearch",
  rechecked_estimate: "confidenceRechecked",
  unstable_search: "confidenceUnstable",
  limited: "confidenceLimited",
  forced: "confidenceForced",
  unavailable: "confidenceUnavailable",
};
/** Engine confidence describes this search, never a claim that a move is proven best. */
export function ConfidenceBadge({
  confidence,
  mode,
}: {
  confidence?: string;
  mode?: string;
}) {
  const t = useT();
  if (!confidence) return null;
  return (
    <small className="analysis-confidence">
      {t("analysisConfidence")}:{" "}
      {t(
        mode === "deep" &&
          ["engine_estimate", "search_estimate"].includes(confidence)
          ? "confidenceDeep"
          : labels[confidence] || "confidenceLimited",
      )}
    </small>
  );
}
