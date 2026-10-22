import { createContext, useCallback, useEffect, useState } from 'react';
import { Chess } from 'chess.js';
import type { Preferences, VisualInsight } from './types';

export const BoardVisualPreviewContext = createContext<(insight: VisualInsight | null, owner: string) => void>(() => {});

export function useBoardVisuals({ fen, preferences, highlightedMove, exploring, lastMove, retryPosition }: {
  fen: string;
  preferences: Preferences;
  highlightedMove?: string | null;
  exploring: boolean;
  lastMove?: string;
  retryPosition: (fen: string) => void;
}) {
  const [selection, setSelection] = useState<{ insight: VisualInsight; origin: string } | null>(null);
  const [previews, setPreviews] = useState<{ insight: VisualInsight; origin: string; owner: string }[]>([]);
  useEffect(() => setPreviews([]), [fen]);
  const previewVisual = useCallback((insight: VisualInsight | null, owner: string) => {
    if (insight) {
      try { new Chess(insight.fen); } catch { return; }
    }
    setPreviews((current) => {
      const remaining = current.filter((preview) => preview.owner !== owner);
      return insight ? [...remaining, { insight, origin: fen, owner }] : remaining;
    });
  }, [fen]);
  const preview = previews.filter((item) => item.origin === fen).at(-1);
  const displayed = preview || selection;
  const visual = displayed?.insight;
  const feedback = visual?.id.startsWith('feedback-') && displayed?.origin === fen;
  const activeVisual = visual && (feedback || visual.fen === fen) ? visual : null;
  const threat = /threat|attack|pin|fork|skewer|exposed|reply/i.test(`${activeVisual?.claim_type || ''} ${activeVisual?.id || ''}`);
  const visible = !feedback && preferences.highlight_threats === false && threat ? null : activeVisual;
  const arrows = visible?.arrows?.filter((arrow) => (feedback || preferences.highlight_threats !== false || !['red', '#c65355'].includes(arrow.color || '')) && /^[a-h][1-8]$/.test(arrow.from) && /^[a-h][1-8]$/.test(arrow.to)).map((arrow) => ({ startSquare: arrow.from, endSquare: arrow.to, color: arrow.color || '#326e9c' })) || [];
  const move = !feedback && (highlightedMove || (exploring && preferences.explanation_mode !== 'text' ? lastMove : null));
  if (move && /^[a-h][1-8][a-h][1-8]/.test(move)) arrows.push({ startSquare: move.slice(0, 2), endSquare: move.slice(2, 4), color: '#378466' });
  return {
    activeVisual, arrows, previewing: !!preview && selection?.origin !== fen,
    feedbackFen: feedback ? visual?.fen : undefined,
    targets: !feedback && preferences.highlight_pieces === false && visible?.id !== 'hint-guide' ? [] : visible?.squares,
    previewVisual,
    clearVisual: () => { setSelection(null); setPreviews([]); },
    showVisual: (insight: VisualInsight) => {
      setPreviews([]);
      if (insight.id.startsWith('feedback-')) {
        try { new Chess(insight.fen); } catch { return; }
        setSelection((current) => current?.origin === fen && current.insight.id === insight.id && current.insight.fen === insight.fen ? null : { insight, origin: fen });
      } else {
        if (insight.fen !== fen) retryPosition(insight.fen);
        setSelection({ insight, origin: fen });
      }
    },
  };
}
