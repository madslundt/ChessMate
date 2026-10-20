import type { ReactNode } from "react";
import { useT } from "./i18n";
/** Board-first mode keeps explanations available without filling the board's companion pane. */
export function ExplanationText({
  mode,
  children,
}: {
  mode?: string;
  children: ReactNode;
}) {
  const t = useT();
  return mode === "visual" ? (
    <details className="explanation-details">
      <summary>{t("readExplanation")}</summary>
      {children}
    </details>
  ) : (
    <>{children}</>
  );
}
