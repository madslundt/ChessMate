import { describe, expect, it } from "vitest";
import { coachTimeline, mergeConversationMessages } from "./coachTimeline";
import type { ChatMessage, Game } from "./types";

const game: Game = { id: "game", initial_fen: "start", fen: "after-e5", revision: 2, mode: "analysis",
  player_color: "white", difficulty: 1, status: "playing", moves: [
    { uci: "e2e4", san: "e4", fen: "after-e4" }, { uci: "e7e5", san: "e5", fen: "after-e5" },
  ] };
const message = (id: string, fen: string, content = id): ChatMessage => ({ id, fen, content, role: "user" });
const labels = (entries: ReturnType<typeof coachTimeline>) => entries.map((entry) => entry.kind === "move" ? game.moves[entry.moveIndex].san : entry.message.content);

describe("coaching timeline", () => {
  it("interleaves moves after earlier questions and before later replies", () => {
    expect(labels(coachTimeline(game, [message("before", "start"), message("between", "after-e4"), message("after", "after-e5")]))).toEqual(["before", "e4", "between", "e5", "after"]);
  });
  it("uses persisted ply to distinguish repeated positions", () => {
    const repeated = { ...game, moves: [{ ...game.moves[0], fen: "start" }] };
    const entries = coachTimeline(repeated, [{ ...message("old", "start"), ply: 0 }, { ...message("new", "start"), ply: 1 }]);
    expect(entries.map((entry) => entry.kind === "move" ? "move" : entry.message.content)).toEqual(["old", "move", "new"]);
  });
  it("merges saved history without duplicating completed optimistic turns", () => {
    const saved = [message("server-1", "start", "Why?")];
    expect(mergeConversationMessages([message("pending-1", "start", "Why?"), message("pending-2", "start", "Why?")], saved)).toEqual([...saved, message("pending-2", "start", "Why?")]);
  });
  it("retains both distinct saved messages with identical wording", () => {
    const saved = [message("server-1", "start", "Why?"), message("server-2", "start", "Why?")];
    expect(mergeConversationMessages(saved, saved)).toEqual(saved);
  });
  it("keeps a new question about an earlier position below moves already played", () => {
    expect(labels(coachTimeline(game, [{ ...message("review", "start"), ply: 0, timeline_revision: 2 }]))).toEqual(["e4", "e5", "review"]);
  });
  it("places imported moves before the first conversation", () => {
    const imported = { ...game, revision: 0, moves: game.moves.map((move) => ({ ...move, timeline_revision: 0 })) };
    expect(labels(coachTimeline(imported, [{ ...message("review", "start"), timeline_revision: 0 }]))).toEqual(["e4", "e5", "review"]);
  });
  it("places a redone move below messages sent before the redo", () => {
    const redone = { ...game, revision: 5, moves: [{ ...game.moves[0], timeline_revision: 1 }, { ...game.moves[1], timeline_revision: 5 }] };
    expect(labels(coachTimeline(redone, [{ ...message("before-redo", "after-e4"), timeline_revision: 4 }]))).toEqual(["e4", "before-redo", "e5"]);
  });
});
