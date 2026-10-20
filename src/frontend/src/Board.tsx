import { useEffect, useMemo, useState } from 'react';
import { Chess, type Square } from 'chess.js';
import { Chessboard, type ChessboardOptions } from 'react-chessboard';
import type { Color, Preferences } from './types';
import { useT } from './i18n';
import { X } from 'lucide-react';

interface Props {
  fen: string;
  preferences: Preferences;
  orientation: Color;
  onMove: (uci: string) => void;
  disabled?: boolean;
  lastMove?: string;
  highlightedMove?: string | null;
  arrows?: { startSquare: string; endSquare: string; color: string }[];
}
export function Board({ fen, preferences, orientation, onMove, disabled = false, lastMove, highlightedMove, arrows = [] }: Props) {
  const t = useT(),
    [selected, setSelected] = useState<string | null>(null),
    [held, setHeld] = useState<string | null>(null),
    [promotion, setPromotion] = useState<{ from: string; to: string } | null>(null);
  const chess = useMemo(() => new Chess(fen), [fen]);
  useEffect(() => {
    setSelected(null);
    setHeld(null);
    setPromotion(null);
  }, [fen, disabled]);
  useEffect(() => {
    if (!held) return;
    const release = () => setHeld(null);
    const cancel = (event: KeyboardEvent) => {
      if (event.key === 'Escape') release();
    };
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    window.addEventListener('blur', release);
    window.addEventListener('keydown', cancel);
    return () => {
      window.removeEventListener('pointerup', release);
      window.removeEventListener('pointercancel', release);
      window.removeEventListener('blur', release);
      window.removeEventListener('keydown', cancel);
    };
  }, [held]);
  const activeSquare = disabled || promotion ? null : (held ?? selected);
  const legalMoves =
    activeSquare && preferences.show_legal_moves ? chess.moves({ square: activeSquare as Square, verbose: true }) : [];
  const glowingSquares = new Set(held ? legalMoves.map((move) => move.to) : []);
  const styles: Record<string, React.CSSProperties> = {};
  const moveToHighlight = highlightedMove !== undefined ? highlightedMove : lastMove;
  if (moveToHighlight) {
    styles[moveToHighlight.slice(0, 2)] = { backgroundColor: '#c9cf7090' };
    styles[moveToHighlight.slice(2, 4)] = { backgroundColor: '#d6dc6d99' };
  }
  if (chess.isCheck()) {
    const king = chess
      .board()
      .flat()
      .find((p) => p?.type === 'k' && p.color === chess.turn());
    if (king)
      styles[king.square] = {
        background: 'radial-gradient(ellipse, #c65355 0%, #c6535580 55%, transparent 85%)',
      };
  }
  if (activeSquare) {
    styles[activeSquare] = { backgroundColor: '#d1d87c' };
    if (!held) {
      for (const m of legalMoves)
        styles[m.to] = {
          ...styles[m.to],
          backgroundImage: m.captured
            ? 'radial-gradient(transparent 58%, #204b3d55 60%)'
            : 'radial-gradient(#204b3d55 19%, transparent 21%)',
        };
    }
  }
  function hold(square: string) {
    if (!disabled && !promotion && chess.get(square as Square)?.color === chess.turn()) setHeld(square);
  }
  function tryMove(from: string, to: string) {
    if (disabled) return false;
    const legal = chess.moves({ square: from as Square, verbose: true }).filter((m) => m.to === to);
    if (!legal.length) return false;
    if (legal.some((m) => m.promotion)) {
      setPromotion({ from, to });
      return true;
    }
    onMove(from + to);
    setSelected(null);
    return true;
  }
  function click(square: string) {
    if (disabled) return;
    if (selected && tryMove(selected, square)) return;
    const piece = chess.get(square as Square);
    setSelected(piece?.color === chess.turn() ? square : null);
  }
  const palette =
    preferences.board_theme === 'wood'
      ? ['#ead6b7', '#b38c69']
      : preferences.board_theme === 'blue'
        ? ['#e1e8ed', '#8198ad']
        : ['#e9ecd9', '#8aa18c'];
  const pieces: ChessboardOptions['pieces'] =
    preferences.piece_style === 'modern'
      ? Object.fromEntries(
          ['w', 'b'].flatMap((c) =>
            ['P', 'N', 'B', 'R', 'Q', 'K'].map((p) => [
              c + p,
              () => <span className={`letter-piece ${c === 'w' ? 'white-piece' : 'black-piece'}`}>{p}</span>,
            ]),
          ),
        )
      : undefined;
  return (
    <div
      className="board-shell"
      data-testid="chessboard"
      aria-label={`${chess.turn() === 'w' ? t('white') : t('black')} ${t('sideToMove')}`}
    >
      <Chessboard
        options={{
          id: 'chessmate-board',
          position: fen,
          boardOrientation: orientation,
          pieces,
          allowDragging: !disabled,
          allowDrawingArrows: true,
          arrows,
          canDragPiece: ({ piece }) => !disabled && piece.pieceType[0] === chess.turn(),
          onPieceDrag: ({ square }) => {
            if (square) hold(square);
          },
          onPieceDragCancel: () => setHeld(null),
          onPieceDrop: ({ sourceSquare, targetSquare }) => {
            setHeld(null);
            return targetSquare ? tryMove(sourceSquare, targetSquare) : false;
          },
          onSquareClick: ({ square }) => click(square),
          squareStyles: styles,
          boardStyle: { borderRadius: '4px', overflow: 'hidden' },
          darkSquareStyle: { backgroundColor: palette[1] },
          lightSquareStyle: { backgroundColor: palette[0] },
          darkSquareNotationStyle: { color: palette[0], fontSize: 12 },
          lightSquareNotationStyle: { color: '#48634f', fontSize: 12 },
          animationDurationInMs: 180,
          squareRenderer: ({ square, children }) => (
            <div
              role="button"
              tabIndex={disabled ? -1 : 0}
              aria-label={
                square +
                (chess.get(square as Square)
                  ? ` ${chess.get(square as Square)?.color === 'w' ? t('white') : t('black')} ${chess.get(square as Square)?.type}`
                  : '')
              }
              aria-pressed={selected === square}
              onPointerDownCapture={(event) => {
                if (event.isPrimary && event.button === 0) hold(square);
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  click(square);
                }
              }}
              className={`board-square${glowingSquares.has(square as Square) ? ' board-square--legal-glow' : ''}`}
              style={styles[square]}
            >
              {children}
            </div>
          ),
        }}
      />
      {promotion && (
        <div className="promotion-backdrop">
          <div className="promotion-menu" role="dialog" aria-modal="true" aria-label={t('promotion')}>
            <h3>{t('promotion')}</h3>
            <div>
              {['q', 'r', 'b', 'n'].map((p) => (
                <button
                  key={p}
                  aria-label={p}
                  onClick={() => {
                    onMove(promotion.from + promotion.to + p);
                    setPromotion(null);
                  }}
                >
                  {{ q: '♛', r: '♜', b: '♝', n: '♞' }[p]}
                </button>
              ))}
              <button aria-label={t('close')} onClick={() => setPromotion(null)}>
                <X size={20} />
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
export function evaluationText(cp: number | null | undefined, mate: number | null | undefined) {
  return mate !== null && mate !== undefined
    ? `M${mate}`
    : cp === null || cp === undefined
      ? '—'
      : `${cp >= 0 ? '+' : ''}${(cp / 100).toFixed(1)}`;
}
