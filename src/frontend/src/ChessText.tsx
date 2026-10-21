import { useMemo } from 'react';
import { Chess, type Move } from 'chess.js';
import { VisualHighlight } from './FeedbackHighlights';
import type { Feedback, VisualInsight } from './types';
import './styles/feedback-highlights.css';

interface ChessTextProps {
  text?: string;
  fen: string;
  beforeFen?: string;
  coaching?: Pick<
    Feedback,
    'insights' | 'threats' | 'variations' | 'played' | 'best' | 'alternatives'
  >;
  activeVisual?: VisualInsight | null;
  onVisual?: (insight: VisualInsight) => void;
}

interface TextReference {
  text: string;
  insight?: VisualInsight;
}

// Match whole references, keeping punctuation and the surrounding prose intact.
const referencePattern =
  /(?<![\p{L}\p{N}_])(?:[a-h][1-8](?:\s*(?:->|[-–→])\s*)?[a-h][1-8][qrbnQRBN]?|[O0]-[O0](?:-[O0])?|[KQRBN](?:[a-h][1-8]|[a-h1-8])?x?[a-h][1-8]|[a-h](?:x[a-h])?[1-8](?:=?[QRBN])?)[+#]?[!?]*(?![\p{L}\p{N}_])/gu;
const normalize = (text: string) =>
  text.replace(/[!?+#]/g, '').replace(/0/g, 'O');

/** Resolve moves on their own positions; unresolved SAN still identifies its destination. */
export function chessTextReferences({
  text = '',
  fen,
  beforeFen,
  coaching,
}: Omit<ChessTextProps, 'onVisual' | 'activeVisual'>): TextReference[] {
  const matches = [...text.matchAll(referencePattern)];
  if (!matches.length) return [{ text }];
  const positions = new Map<string, Move[]>();
  const addPosition = (position?: string) => {
    if (!position || positions.has(position)) return;
    try {
      positions.set(position, new Chess(position).moves({ verbose: true }));
    } catch {
      /* Ignore malformed context. */
    }
  };
  addPosition(beforeFen);
  addPosition(fen);
  if (!positions.size) return [{ text }];
  const primaryFen = positions.has(fen) ? fen : positions.keys().next().value!;
  const insights = [
    ...(coaching?.threats || []),
    ...(coaching?.insights || []),
  ];
  for (const insight of insights) addPosition(insight.fen);
  const addLine = (base: string, line: string[]) => {
    try {
      const board = new Chess(base);
      for (const move of line) {
        addPosition(board.fen());
        board.move(move);
      }
      addPosition(board.fen());
    } catch {
      /* Keep the verified portion of a line. */
    }
  };
  for (const variation of coaching?.variations || [])
    addLine(variation.base_fen, variation.moves);
  for (const candidate of [
    coaching?.played,
    coaching?.best,
    ...(coaching?.alternatives || []),
  ]) {
    if (candidate)
      addLine(
        beforeFen || fen,
        candidate.pv_uci?.length ? candidate.pv_uci : candidate.pv,
      );
  }
  const parts: TextReference[] = [];
  let end = 0;
  let continuation: { fen: string; moves: Move[] } | undefined;
  for (const match of matches) {
    const reference = match[0],
      start = match.index;
    if (start > end) parts.push({ text: text.slice(end, start) });
    const token = normalize(reference);
    const coordinates = token.match(
      /^([a-h][1-8])(?:\s*(?:->|[-–→])\s*)?([a-h][1-8])([qrbnQRBN])?$/,
    );
    const squareOnly =
      /^[a-h][1-8]$/.test(token) &&
      /\b(?:on|at|to|from|via|square|squares|control(?:s|led|ling)?|defend(?:s|ed|ing)?|protect(?:s|ed|ing)?|attack(?:s|ed|ing)?|target(?:s|ed|ing)?|occup(?:y|ies)|toward(?:s)?|cover(?:s|ed|ing)?|på|til|fra|felt(?:et|er|erne)?|kontroller(?:er|e)|beskyt(?:ter)?|angrib(?:er)?)\s+(?:[a-h][1-8](?:\s*[,/]\s*|\s+(?:and|or|og|eller)\s+))*$/iu.test(
        text.slice(0, start),
      );
    const sameLine =
      continuation && /^[\s\d.→–>,-]*$/.test(text.slice(end, start));
    const contexts =
      sameLine && continuation
        ? [[continuation.fen, continuation.moves] as const, ...positions]
        : [...positions];
    let resolved: { fen: string; move: Move } | undefined;
    if (!squareOnly) {
      for (const [position, moves] of contexts) {
        const move = moves.find((move) =>
          coordinates
            ? move.from === coordinates[1] &&
              move.to === coordinates[2] &&
              (move.promotion || '') === (coordinates[3]?.toLowerCase() || '')
            : normalize(move.san) === token,
        );
        if (move) {
          resolved = { fen: position, move };
          break;
        }
      }
    }
    // Structured evidence can identify a threat several moves beyond the text's base position.
    const evidence =
      !resolved && !squareOnly
        ? insights.find(
            (insight) =>
              positions.has(insight.fen) &&
              (insight.squares?.length || insight.arrows?.length) &&
              [
                ...`${insight.label || ''} ${insight.text}`.matchAll(
                  referencePattern,
                ),
              ].some((item) => normalize(item[0]) === token),
          )
        : undefined;
    const destination = token.match(/[a-h][1-8]/g)?.at(-1);
    const castleDestination = token.startsWith('O-O')
      ? `${token === 'O-O-O' ? 'c' : 'g'}${primaryFen.split(' ')[1] === 'b' ? '8' : '1'}`
      : undefined;
    const from = resolved?.move.from || coordinates?.[1];
    const to = resolved?.move.to || coordinates?.[2];
    const visualFen = resolved?.fen || (evidence ? evidence.fen : primaryFen);
    const squares =
      from && to
        ? [from, to]
        : evidence?.squares || [destination || castleDestination!];
    const insight: VisualInsight = {
      id: `feedback-reference-${visualFen}-${token}`,
      text: reference,
      fen: visualFen,
      squares,
      arrows: from && to ? [{ from, to, color: '#326e9c' }] : evidence?.arrows,
    };
    parts.push({ text: reference, insight });
    continuation = undefined;
    if (resolved) {
      const board = new Chess(resolved.fen);
      board.move(resolved.move.lan);
      continuation = {
        fen: board.fen(),
        moves: board.moves({ verbose: true }),
      };
    }
    end = start + reference.length;
  }
  if (end < text.length) parts.push({ text: text.slice(end) });
  return parts;
}

export function ChessText({
  text = '',
  fen,
  beforeFen,
  coaching,
  onVisual,
  activeVisual,
}: ChessTextProps) {
  const parts = useMemo(
    () => chessTextReferences({ text, fen, beforeFen, coaching }),
    [text, fen, beforeFen, coaching],
  );
  if (!onVisual) return <>{text}</>;
  return (
    <>
      {parts.map((part, index) =>
        part.insight ? (
          <VisualHighlight
            key={index}
            className="chess-text-reference"
            insight={part.insight}
            activeVisual={activeVisual}
            onVisual={onVisual}
          >
            {part.text}
          </VisualHighlight>
        ) : (
          part.text
        ),
      )}
    </>
  );
}
