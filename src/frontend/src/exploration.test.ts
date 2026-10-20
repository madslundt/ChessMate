import { describe, it, expect } from "vitest";
import { Chess } from "chess.js";
import {
  committable,
  legalVariation,
  replayVariation,
  variationCursor,
} from "./exploration";
import type { Game } from "./types";
const game: Game = {
  id: "test",
  fen: new Chess().fen(),
  initial_fen: new Chess().fen(),
  moves: [],
  revision: 2,
  mode: "training",
  player_color: "white",
  difficulty: 2,
  status: "playing",
  result: "*",
};
describe("independent exploration", () => {
  it("replays several hypothetical plies without mutating the saved game", () => {
    const before = JSON.stringify(game);
    const c = replayVariation(game.fen, ["e2e4", "e7e5", "g1f3"]);
    expect(c.history()).toEqual(["e4", "e5", "Nf3"]);
    expect(JSON.stringify(game)).toBe(before);
  });
  it("rejects an illegal line and cannot affect the authoritative position", () => {
    expect(() => replayVariation(game.fen, ["e2e5"])).toThrow();
    expect(game.fen).toBe(new Chess().fen());
  });
  it("allows committing the first move regardless of the last hypothetical side to move", () => {
    expect(
      committable(game, {
        base: game.fen,
        moves: ["e2e4"],
        revision: 2,
        atLatest: true,
      }),
    ).toBe(true);
  });
  it("rejects stale games, historical branches, and branches rooted in the opponent turn", () => {
    expect(
      committable(game, {
        base: game.fen,
        moves: ["e2e4"],
        revision: 1,
        atLatest: true,
      }),
    ).toBe(false);
    expect(
      committable(game, {
        base: game.fen,
        moves: ["e2e4"],
        revision: 2,
        atLatest: false,
      }),
    ).toBe(false);
    expect(
      committable(game, {
        base: replayVariation(game.fen, ["e2e4"]).fen(),
        moves: ["e7e5"],
        revision: 2,
        atLatest: true,
      }),
    ).toBe(false);
  });
});

describe("coaching variation playback", () => {
  it("truncates an invalid external continuation at its last legal position", () => {
    expect(legalVariation(game.fen, ["e2e4", "e7e5", "e4e6", "b8c6"])).toEqual([
      "e2e4",
      "e7e5",
    ]);
  });
  it("supports stepping forward and backward without mutating the saved game", () => {
    const moves = ["e2e4", "e7e5", "g1f3"];
    expect(replayVariation(game.fen, moves.slice(0, 1)).history()).toEqual([
      "e4",
    ]);
    expect(replayVariation(game.fen, moves.slice(0, 3)).history()).toEqual([
      "e4",
      "e5",
      "Nf3",
    ]);
    expect(replayVariation(game.fen, moves.slice(0, 0)).fen()).toBe(game.fen);
    expect(
      variationCursor({
        base: game.fen,
        moves,
        revision: 2,
        atLatest: true,
        cursor: 99,
      }),
    ).toBe(3);
  });
  it("replays castling, en passant, and underpromotion legally", () => {
    expect(
      replayVariation("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", [
        "e1g1",
        "e8c8",
      ]).get("f1")?.type,
    ).toBe("r");
    const enPassant = replayVariation("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 2", [
      "e5d6",
    ]);
    expect(enPassant.get("d5")).toBeUndefined();
    expect(enPassant.get("d6")?.type).toBe("p");
    expect(
      replayVariation("4k3/P7/8/8/8/8/8/4K3 w - - 0 1", ["a7a8n"]).get("a8")
        ?.type,
    ).toBe("n");
  });
  it("keeps demonstration previews noncommittable even at the live position", () => {
    expect(
      committable(game, {
        base: game.fen,
        moves: ["e2e4"],
        revision: 2,
        atLatest: true,
        previewOnly: true,
      }),
    ).toBe(false);
  });
});
