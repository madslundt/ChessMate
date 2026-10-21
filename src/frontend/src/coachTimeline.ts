import type { ChatMessage, Game } from "./types";

export type CoachTimelineEntry =
  | { kind: "message"; message: ChatMessage }
  | { kind: "move"; moveIndex: number };

export function positionPly(game: Game | null, fen?: string): number {
  if (!game) return 0;
  let ply = fen === game.initial_fen ? 0 : game.moves.length;
  game.moves.forEach((move, index) => { if (move.fen === fen) ply = index + 1; });
  return ply;
}

export function coachTimeline(game: Game | null, messages: ChatMessage[]): CoachTimelineEntry[] {
  if (!game) return messages.map((message) => ({ kind: "message", message }));
  const positions = new Map<string, number>([[game.initial_fen, 0]]);
  game.moves.forEach((move, index) => positions.set(move.fen, index + 1));
  const entries: { revision: number; order: number; entry: CoachTimelineEntry }[] = game.moves.map((move, index) => ({
    revision: move.timeline_revision ?? (move.source === "import" ? 0 : index + 1),
    order: index, entry: { kind: "move", moveIndex: index },
  }));
  messages.forEach((message, index) => entries.push({
    revision: message.timeline_revision ?? message.ply ?? positions.get(message.fen || "") ?? game.revision,
    order: game.moves.length + index, entry: { kind: "message", message },
  }));
  return entries.sort((a, b) => a.revision - b.revision || a.order - b.order).map(({ entry }) => entry);
}

export function mergeConversationMessages(previous: ChatMessage[], saved: ChatMessage[]): ChatMessage[] {
  const savedIds = new Set(saved.map((message) => message.id).filter(Boolean));
  const signature = (message: ChatMessage) => JSON.stringify([message.role, message.fen, message.content]);
  const unmatched = new Map<string, number>();
  saved.forEach((message) => unmatched.set(signature(message), (unmatched.get(signature(message)) || 0) + 1));
  const pending = previous.filter((message) => {
    if (message.id && savedIds.has(message.id)) return false;
    if (message.id && !message.id.startsWith("pending-")) return false;
    const key = signature(message), count = unmatched.get(key) || 0;
    if (count) { unmatched.set(key, count - 1); return false; }
    return true;
  });
  return [...saved, ...pending];
}
