import { createContext, useContext } from "react";
import { en } from "./locale-en";
import { da } from "./locale-da";
export type TranslationKey = keyof typeof en;
export const LocaleContext = createContext<"en" | "da">("en");
export const translate = (lang: "en" | "da", key: TranslationKey) =>
  (lang === "da" ? da : en)[key];
export function useT() {
  const lang = useContext(LocaleContext);
  return (key: TranslationKey) => translate(lang, key);
}
