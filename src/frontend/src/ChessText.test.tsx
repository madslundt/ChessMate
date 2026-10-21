import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Chess } from 'chess.js';
import { ChessText, chessTextReferences } from './ChessText';
import { CoachMessages } from './CoachMessages';
import { LastMoveFeedback } from './LastMoveFeedback';
import { defaults, type Game } from './types';
import { LocaleContext } from './i18n';

const fen = new Chess().fen();
const references = (text: string, position = fen) =>
  chessTextReferences({ text, fen: position }).filter((part) => part.insight);

describe('clickable chess text', () => {
  it('preserves prose and punctuation and matches complete SAN, UCI and square references', () => {
    const text =
      'Try **Nf3!**, e2e4 or d2 → d4; look at c6. Keep abc6 and e4value unchanged.';
    const parts = chessTextReferences({ text, fen });
    expect(parts.map((part) => part.text).join('')).toBe(text);
    expect(
      parts.filter((part) => part.insight).map((part) => part.text),
    ).toEqual(['Nf3!', 'e2e4', 'd2 → d4', 'c6']);
    expect(parts.find((part) => part.text === 'Nf3!')?.insight?.arrows).toEqual(
      [{ from: 'g1', to: 'f3', color: '#326e9c' }],
    );
    expect(references('The knight on f3')[0].insight?.squares).toEqual(['f3']);
    expect(references('The pawn on e4')[0].insight?.arrows).toBeUndefined();
    expect(references('Nf3 controls e4')[1].insight?.squares).toEqual(['e4']);
    expect(references('Protect e4')[0].insight?.arrows).toBeUndefined();
    expect(
      references('Pressure on d4 and e4').map((part) => part.insight?.squares),
    ).toEqual([['d4'], ['e4']]);
    expect(
      references('Pres på d4 og e4').map((part) => part.insight?.squares),
    ).toEqual([['d4'], ['e4']]);
  });

  it('resolves numbered continuations on each move’s own position', () => {
    const parts = references('1.e4 e5 2.Nf3 Nc6');
    expect(parts.map((part) => part.insight?.arrows?.[0].from)).toEqual([
      'e2',
      'e7',
      'g1',
      'b8',
    ]);
    const board = new Chess();
    for (const part of parts) {
      expect(part.insight?.fen).toBe(board.fen());
      board.move(part.text);
    }
  });

  it('handles castling, captures, disambiguation, promotions and unresolved SAN without inventing a source', () => {
    expect(
      references('0-0', 'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1')[0].insight
        ?.arrows?.[0],
    ).toMatchObject({ from: 'e1', to: 'g1' });
    expect(
      references('a8=Q+', '7k/P7/8/8/8/8/8/7K w - - 0 1')[0].insight
        ?.arrows?.[0],
    ).toMatchObject({ from: 'a7', to: 'a8' });
    expect(references('Raxd1+')[0]).toMatchObject({
      text: 'Raxd1+',
      insight: { squares: ['d1'] },
    });
    expect(references('Nxd5')[0].insight?.arrows).toBeUndefined();
    expect(chessTextReferences({ text: 'Nf3 on e4', fen: 'invalid' })).toEqual([
      { text: 'Nf3 on e4' },
    ]);
  });

  it('uses before/after positions and structured threat evidence for feedback', () => {
    const board = new Chess();
    board.move('f3');
    board.move('e5');
    const beforeFen = board.fen();
    board.move('g4');
    const afterFen = board.fen();
    board.move('Qh4#');
    const mateFen = board.fen();
    const parts = chessTextReferences({
      text: 'g4 allows Qh4#; d4 was better.',
      fen: afterFen,
      beforeFen,
      coaching: {
        threats: [
          {
            id: 'mate',
            text: 'Qh4# is mate.',
            fen: mateFen,
            squares: ['h4', 'e1'],
            arrows: [{ from: 'h4', to: 'e1' }],
          },
        ],
      },
    });
    expect(parts.find((part) => part.text === 'g4')?.insight?.fen).toBe(
      beforeFen,
    );
    expect(
      parts.find((part) => part.text === 'Qh4#')?.insight?.arrows?.[0],
    ).toMatchObject({ from: 'd8', to: 'h4' });
    expect(parts.find((part) => part.text === 'd4')?.insight?.fen).toBe(
      beforeFen,
    );
  });

  it('renders accessible inline buttons in user chat, coach chat and feedback even in text mode', () => {
    const chat = renderToStaticMarkup(
      <CoachMessages
        messages={[
          { role: 'user', fen, content: 'Why Nf3 on f3?' },
          { role: 'assistant', fen, content: 'Nf3 develops toward e5.' },
        ]}
        busy={false}
        fen={fen}
        preferences={{ ...defaults, explanation_mode: 'text' }}
        onVisual={() => {}}
        onResolve={() => {}}
        onPreview={() => {}}
      />,
    );
    expect(chat.match(/>Nf3<\/button>/g)).toHaveLength(2);
    expect(chat).toContain('>f3?</button>');
    const board = new Chess();
    board.move('e4');
    const game: Game = {
      id: 'text',
      initial_fen: fen,
      fen: board.fen(),
      revision: 1,
      mode: 'training',
      player_color: 'white',
      difficulty: 1,
      status: 'playing',
      moves: [
        {
          san: 'e4',
          uci: 'e2e4',
          before_fen: fen,
          fen: board.fen(),
          feedback: { text: 'e4 controls d5.' },
        },
      ],
    };
    const html = renderToStaticMarkup(
      <LastMoveFeedback game={game} ply={1} onVisual={() => {}} />,
    );
    expect(html.match(/>e4<\/button>/g)).toHaveLength(2);
    expect(html).toContain('>d5</button>');
    const selected = references('Nf3')[0].insight!;
    const danish = renderToStaticMarkup(
      <LocaleContext.Provider value="da">
        <ChessText
          text="Nf3"
          fen={fen}
          onVisual={() => {}}
          activeVisual={selected}
        />
      </LocaleContext.Provider>,
    );
    expect(danish).toContain('aria-pressed="true"');
    expect(danish).toContain('Klik for at fremhæve på brættet');
    expect(danish).toContain('type="button"');
  });
});
