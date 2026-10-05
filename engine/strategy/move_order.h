#pragma once

#include "strategy/attack_map.h"
#include <algorithm>
#include <cmath>
#include <string>
#include <utility>
#include <vector>

namespace shogi::strategy {

// Lightweight tactical move-ordering heuristics for alpha-beta search.
// This changes only the order in which legal moves are searched; it does not
// change the evaluation function or the final minimax/alpha-beta score.
class MoveOrder {
public:
    struct OrderedMove {
        std::string move;
        int score = 0;
        std::size_t original_index = 0;
    };

    static std::vector<OrderedMove> order_scored(const rules::Snapshot& snapshot,
                                                 const std::vector<std::string>& moves) {
        // Source-square danger is the same for every candidate. Build it once
        // per position instead of rescanning the board for every move.
        const AttackMap before_attacks(snapshot);
        std::vector<OrderedMove> scored;
        scored.reserve(moves.size());
        for (std::size_t i = 0; i < moves.size(); ++i)
            scored.push_back({moves[i], score_move(snapshot, moves[i], before_attacks), i});

        std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
            return a.score > b.score;
        });
        return scored;
    }

    static std::vector<std::string> order(const rules::Snapshot& snapshot,
                                          const std::vector<std::string>& moves) {
        auto scored = order_scored(snapshot, moves);
        std::vector<std::string> ordered;
        ordered.reserve(scored.size());
        for (const auto& item : scored) ordered.push_back(item.move);
        return ordered;
    }

    // Public diagnostic/test entry point. The search path uses order(), which
    // reuses one AttackMap across all candidate moves.
    static int score_move(const rules::Snapshot& snapshot, const std::string& move) {
        const AttackMap before_attacks(snapshot);
        return score_move(snapshot, move, before_attacks);
    }

private:
    struct ParsedMove {
        bool valid = false;
        bool has_source = false;
        bool promoted_now = false;
        int source_index = -1;
        int destination_index = -1;
        rules::Piece moving{};
        rules::Piece captured{};
    };

    struct AfterTactics {
        bool gives_check = false;
        bool destination_attacked = false;
        int pressured_value = 0;
    };

    static int score_move(const rules::Snapshot& snapshot,
                          const std::string& move,
                          const AttackMap& before_attacks) {
        const auto mover = snapshot.turn;
        const auto enemy = other(mover);
        int score = 0;

        rules::Snapshot after = snapshot;
        const auto parsed = apply_to_snapshot(after, move, mover);
        if (!parsed.valid) return score;

        const bool endangered = parsed.has_source && parsed.moving.kind != 8
            && before_attacks.count[static_cast<int>(enemy)][parsed.source_index] > 0;
        const int enemy_king = before_attacks.kings[static_cast<int>(enemy)];
        const auto tactics = analyze_after(after, parsed.destination_index, mover,
                                           enemy_king, endangered);

        // 1. Checks remain the strongest ordinary ordering signal.
        // TT/Experience hints are handled outside this heuristic.
        if (tactics.gives_check) score += 100000000;

        // 2. Read contested pieces immediately after checks.
        // Captures, saving a currently attacked piece, and creating an immediate
        // attack on an enemy piece all belong to the same tactical cluster.
        if (parsed.captured.kind != 0 && parsed.captured.kind != 8) {
            score += 8000000
                  + 5000 * piece_value(parsed.captured.kind, parsed.captured.promoted);
        }

        if (endangered) {
            const int moving_value = piece_value(parsed.moving.kind, parsed.moving.promoted);
            // A clean escape is most useful, but even a counter-capture/exchange
            // by an endangered piece should be searched before quiet moves.
            score += (tactics.destination_attacked ? 3000000 : 7000000)
                  + 3000 * moving_value;
        }

        if (tactics.pressured_value > 0)
            score += 4000000 + 2000 * tactics.pressured_value;

        // 3. Promotion is useful but comes after immediate piece contact.
        if (parsed.promoted_now)
            score += 100 * std::max(0,
                piece_value(parsed.moving.kind, true) - piece_value(parsed.moving.kind, false));

        return score;
    }

    static rules::Color other(rules::Color color) {
        return color == rules::Color::Black ? rules::Color::White : rules::Color::Black;
    }

    static int square_index(char file, char rank) {
        if (file < '1' || file > '9' || rank < 'a' || rank > 'i') return -1;
        return (file - '1') * 9 + (rank - 'a');
    }

    static int file_of(int index) { return index / 9 + 1; }
    static int rank_of(int index) { return index % 9; }

    static int drop_kind(char c) {
        switch (c) {
            case 'P': return 1;
            case 'L': return 2;
            case 'N': return 3;
            case 'S': return 4;
            case 'B': return 5;
            case 'R': return 6;
            case 'G': return 7;
            default: return 0;
        }
    }

    static ParsedMove apply_to_snapshot(rules::Snapshot& snapshot,
                                        const std::string& move,
                                        rules::Color mover) {
        ParsedMove parsed;
        if (move.size() >= 4 && move[1] == '*') {
            const int dst = square_index(move[2], move[3]);
            const int kind = drop_kind(move[0]);
            if (dst < 0 || kind == 0) return parsed;
            parsed.valid = true;
            parsed.destination_index = dst;
            parsed.moving.kind = kind;
            parsed.moving.color = mover;
            parsed.moving.promoted = false;
            parsed.captured = snapshot.board[dst];
            snapshot.board[dst] = parsed.moving;
            snapshot.turn = other(mover);
            return parsed;
        }

        if (move.size() < 4) return parsed;
        const int src = square_index(move[0], move[1]);
        const int dst = square_index(move[2], move[3]);
        if (src < 0 || dst < 0) return parsed;
        const auto moving = snapshot.board[src];
        if (moving.kind == 0 || moving.color != mover) return parsed;

        parsed.valid = true;
        parsed.has_source = true;
        parsed.source_index = src;
        parsed.destination_index = dst;
        parsed.moving = moving;
        parsed.captured = snapshot.board[dst];
        parsed.promoted_now = move.size() >= 5 && move[4] == '+' && !moving.promoted;

        auto placed = moving;
        if (move.size() >= 5 && move[4] == '+') placed.promoted = true;
        snapshot.board[src] = rules::Piece{};
        snapshot.board[dst] = placed;
        snapshot.turn = other(mover);
        return parsed;
    }

    static bool path_clear(const rules::Snapshot& snapshot,
                           int from, int to, int step_file, int step_rank) {
        int file = file_of(from) + step_file;
        int rank = rank_of(from) + step_rank;
        const int to_file = file_of(to);
        const int to_rank = rank_of(to);
        while (file != to_file || rank != to_rank) {
            if (file < 1 || file > 9 || rank < 0 || rank > 8) return false;
            const int index = (file - 1) * 9 + rank;
            if (snapshot.board[index].kind != 0) return false;
            file += step_file;
            rank += step_rank;
        }
        return true;
    }

    static bool piece_attacks(const rules::Snapshot& snapshot,
                              int from, const rules::Piece& piece, int to) {
        if (piece.kind == 0 || from == to) return false;
        const int df = file_of(to) - file_of(from);
        const int dr = rank_of(to) - rank_of(from);
        const int adf = std::abs(df);
        const int adr = std::abs(dr);
        const int forward = piece.color == rules::Color::Black ? -1 : 1;

        if (piece.kind >= 1 && piece.kind <= 4 && piece.promoted) {
            return (dr == forward && adf <= 1)
                || (dr == 0 && adf == 1)
                || (dr == -forward && df == 0);
        }

        switch (piece.kind) {
            case 1: // pawn
                return df == 0 && dr == forward;
            case 2: { // lance
                if (df != 0 || dr == 0 || (dr > 0 ? 1 : -1) != forward) return false;
                return path_clear(snapshot, from, to, 0, forward);
            }
            case 3: // knight
                return adf == 1 && dr == 2 * forward;
            case 4: // silver
                return (dr == forward && adf <= 1) || (dr == -forward && adf == 1);
            case 5: { // bishop / horse
                if (adf == adr && adf > 0) {
                    const int sf = df > 0 ? 1 : -1;
                    const int sr = dr > 0 ? 1 : -1;
                    if (path_clear(snapshot, from, to, sf, sr)) return true;
                }
                return piece.promoted && ((adf == 1 && dr == 0) || (adr == 1 && df == 0));
            }
            case 6: { // rook / dragon
                if ((df == 0) != (dr == 0)) {
                    const int sf = df == 0 ? 0 : (df > 0 ? 1 : -1);
                    const int sr = dr == 0 ? 0 : (dr > 0 ? 1 : -1);
                    if (path_clear(snapshot, from, to, sf, sr)) return true;
                }
                return piece.promoted && adf == 1 && adr == 1;
            }
            case 7: // gold
                return (dr == forward && adf <= 1)
                    || (dr == 0 && adf == 1)
                    || (dr == -forward && df == 0);
            case 8: // king
                return std::max(adf, adr) == 1;
            default:
                return false;
        }
    }

    // One pass over the child position answers all three post-move questions:
    // does the move give check, is the moved endangered piece still attacked,
    // and what is the most valuable enemy piece the moved piece attacks next?
    static AfterTactics analyze_after(const rules::Snapshot& snapshot,
                                      int destination,
                                      rules::Color mover,
                                      int enemy_king,
                                      bool need_destination_attack) {
        AfterTactics out;
        if (destination < 0 || destination >= static_cast<int>(snapshot.board.size()))
            return out;
        const auto enemy = other(mover);
        const auto& moved = snapshot.board[destination];

        for (int i = 0; i < static_cast<int>(snapshot.board.size()); ++i) {
            const auto& piece = snapshot.board[i];
            if (piece.kind == 0) continue;
            if (piece.color == mover) {
                if (!out.gives_check && enemy_king >= 0
                    && piece_attacks(snapshot, i, piece, enemy_king))
                    out.gives_check = true;
                continue;
            }

            if (need_destination_attack && !out.destination_attacked
                && piece_attacks(snapshot, i, piece, destination))
                out.destination_attacked = true;

            if (piece.kind != 8 && moved.kind != 0
                && piece_attacks(snapshot, destination, moved, i))
                out.pressured_value = std::max(
                    out.pressured_value, piece_value(piece.kind, piece.promoted));
        }
        return out;
    }
};

} // namespace shogi::strategy
