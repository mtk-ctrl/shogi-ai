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

    struct Diagnostics {
        std::uint64_t geometric_candidates = 0;
        std::uint64_t effective_candidates = 0;
        std::uint64_t reply_checks = 0;
    };

    static std::vector<std::string> order(const rules::Snapshot& snapshot,
                                          const std::vector<std::string>& moves,
                                          bool hand_drop_tactics = false) {
        // Source-square danger is the same for every candidate. Build it once
        // per position instead of rescanning the board for every move.
        const AttackMap before_attacks(snapshot);
        std::vector<OrderedMove> scored;
        scored.reserve(moves.size());
        for (std::size_t i = 0; i < moves.size(); ++i)
            scored.push_back({moves[i], score_move(snapshot, moves[i], before_attacks,
                                                    hand_drop_tactics), i});

        std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
            return a.score > b.score;
        });

        std::vector<std::string> ordered;
        ordered.reserve(scored.size());
        for (const auto& item : scored) ordered.push_back(item.move);
        return ordered;
    }

    // Optional second-stage validation for geometric hand-drop tactics. Only
    // candidate drops pay the cost of looking at the opponent's legal replies.
    // A tactic survives only when every legal reply leaves an immediate legal
    // material capture (or a non-losing recapture on the drop square).
    static std::vector<std::string> order(const rules::Position& position,
                                          const std::vector<std::string>& moves,
                                          bool hand_drop_tactics,
                                          bool response_check,
                                          Diagnostics* diagnostics = nullptr) {
        if (!response_check)
            return order(position.snapshot(), moves, hand_drop_tactics);

        const auto snapshot = position.snapshot();
        const AttackMap before_attacks(snapshot);
        std::vector<OrderedMove> scored;
        scored.reserve(moves.size());
        for (std::size_t i = 0; i < moves.size(); ++i) {
            const int ordinary = score_move(snapshot, moves[i], before_attacks, false);
            const int geometric = score_move(snapshot, moves[i], before_attacks, hand_drop_tactics);
            int score = geometric;
            if (hand_drop_tactics && geometric > ordinary
                && eligible_hand_drop_move(moves[i])) {
                if (diagnostics) ++diagnostics->geometric_candidates;
                std::uint64_t replies = 0;
                const int gain = effective_hand_drop_gain(position, moves[i], replies);
                if (diagnostics) diagnostics->reply_checks += replies;
                // In response-check mode the geometric bonus is replaced, not
                // stacked. Failed apparent forks/skewers fall back to the
                // ordinary ordering signals (check, first target, etc.).
                score = ordinary;
                if (gain > 0) {
                    if (diagnostics) ++diagnostics->effective_candidates;
                    score += 2000000 + 1000 * gain;
                }
            }
            scored.push_back({moves[i], score, i});
        }

        std::stable_sort(scored.begin(), scored.end(), [](const auto& a, const auto& b) {
            return a.score > b.score;
        });
        std::vector<std::string> ordered;
        ordered.reserve(scored.size());
        for (const auto& item : scored) ordered.push_back(item.move);
        return ordered;
    }

    // Public diagnostic/test entry point. The search path uses order(), which
    // reuses one AttackMap across all candidate moves.
    static int score_move(const rules::Snapshot& snapshot, const std::string& move,
                          bool hand_drop_tactics = false) {
        const AttackMap before_attacks(snapshot);
        return score_move(snapshot, move, before_attacks, hand_drop_tactics);
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
        bool destination_supported = false;
        int pressured_value = 0;
        int primary_pressured_gain = 0;
        int secondary_pressured_gain = 0;
        int skewer_gain = 0;
        int worst_exchange = 0;
    };

    static int score_move(const rules::Snapshot& snapshot,
                          const std::string& move,
                          const AttackMap& before_attacks,
                          bool hand_drop_tactics) {
        const auto mover = snapshot.turn;
        const auto enemy = other(mover);
        int score = 0;

        rules::Snapshot after = snapshot;
        const auto parsed = apply_to_snapshot(after, move, mover);
        if (!parsed.valid) return score;

        const bool endangered = parsed.has_source && parsed.moving.kind != 8
            && before_attacks.count[static_cast<int>(enemy)][parsed.source_index] > 0;
        const bool hand_drop_candidate = hand_drop_tactics && !parsed.has_source
            && parsed.moving.kind >= 2 && parsed.moving.kind <= 7;
        const int enemy_king = before_attacks.kings[static_cast<int>(enemy)];
        const auto tactics = analyze_after(after, parsed.destination_index, mover,
                                           enemy_king, endangered || hand_drop_candidate,
                                           hand_drop_candidate);

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

        // Hand-piece tactics are a compressed geometric rule, not a lookup table.
        // Reward only a second direct target (fork) or a second enemy behind the
        // first target on a lance/bishop/rook ray (skewer). If the dropped piece
        // can be captured immediately, require one defender and a non-losing
        // same-square exchange under our material values.
        if (hand_drop_candidate) {
            const bool exchange_safe = !tactics.destination_attacked
                || (tactics.destination_supported && tactics.worst_exchange >= 0);
            if (exchange_safe) {
                if (tactics.secondary_pressured_gain > 0)
                    score += 2000000 + 1000 * tactics.secondary_pressured_gain;
                if (tactics.skewer_gain > 0)
                    score += 1000000 + 500 * tactics.skewer_gain;
            }
        }

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

    static bool eligible_hand_drop_move(const std::string& move) {
        if (move.size() < 4 || move[1] != '*') return false;
        const int kind = drop_kind(move[0]);
        return kind >= 2 && kind <= 7;
    }

    static int effective_hand_drop_gain(const rules::Position& position,
                                        const std::string& move,
                                        std::uint64_t& reply_checks) {
        if (!eligible_hand_drop_move(move)) return 0;
        const int destination = square_index(move[2], move[3]);
        const int dropped_kind = drop_kind(move[0]);
        if (destination < 0) return 0;
        const auto mover = position.turn();
        const auto enemy = other(mover);

        auto child = position.clone();
        std::string error;
        if (!child.play_generated_legal(move, error)) return 0;
        const auto replies = child.legal_moves();
        // Checkmate/check terminality is already handled by the much stronger
        // ordinary check ordering signal; no extra material bonus is needed.
        if (replies.empty()) return 0;

        int guaranteed_gain = -1;
        for (const auto& reply : replies) {
            ++reply_checks;
            if (!child.play_generated_legal(reply, error)) return 0;
            int best_gain = 0;
            if (child.repetition_status().result == rules::Result::Ongoing) {
                const auto after_reply = child.snapshot();
                const auto& occupant = after_reply.board[destination];
                const auto followups = child.legal_moves();

                if (occupant.kind == dropped_kind && occupant.color == mover) {
                    // The dropped piece survived. Count only its immediate legal
                    // captures, so pins and forcing counter-checks are respected
                    // automatically by the rule layer.
                    for (const auto& follow : followups) {
                        if (follow.size() < 4 || follow[1] == '*') continue;
                        if (square_index(follow[0], follow[1]) != destination) continue;
                        const int to = square_index(follow[2], follow[3]);
                        if (to < 0) continue;
                        const auto& target = after_reply.board[to];
                        if (target.kind != 0 && target.kind != 8 && target.color == enemy)
                            best_gain = std::max(best_gain, capture_gain(target));
                    }
                } else if (occupant.kind != 0 && occupant.color == enemy) {
                    // The reply captured the dropped piece. Preserve the old
                    // exchange-safety idea: a legal immediate recapture counts
                    // only when the three-ply same-square exchange is non-losing.
                    const int exchange = capture_gain(occupant)
                        - 2 * piece_value(dropped_kind, false);
                    if (exchange > 0) {
                        for (const auto& follow : followups) {
                            if (follow.size() < 4 || follow[1] == '*') continue;
                            if (square_index(follow[2], follow[3]) == destination) {
                                best_gain = exchange;
                                break;
                            }
                        }
                    }
                }
            }
            child.undo();

            if (guaranteed_gain < 0 || best_gain < guaranteed_gain)
                guaranteed_gain = best_gain;
            // One refutation is enough: this geometric tactic is not a forced
            // immediate material threat after the opponent's best reply.
            if (guaranteed_gain == 0) break;
        }
        return std::max(0, guaranteed_gain);
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

    static int capture_gain(const rules::Piece& piece) {
        if (piece.kind == 0 || piece.kind == 8) return 0;
        // Capturing removes the board value and adds the unpromoted piece to hand.
        return piece_value(piece.kind, piece.promoted) + piece_value(piece.kind, false);
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

    static int skewer_gain(const rules::Snapshot& snapshot,
                           int destination, const rules::Piece& moved) {
        if (moved.kind != 2 && moved.kind != 5 && moved.kind != 6) return 0;
        const auto mover = moved.color;
        auto scan = [&](int df, int dr) {
            bool first_enemy = false;
            for (int file = file_of(destination) + df, rank = rank_of(destination) + dr;
                 file >= 1 && file <= 9 && rank >= 0 && rank <= 8;
                 file += df, rank += dr) {
                const auto& piece = snapshot.board[(file - 1) * 9 + rank];
                if (piece.kind == 0) continue;
                if (piece.color == mover || piece.kind == 8) return 0;
                if (!first_enemy) { first_enemy = true; continue; }
                return capture_gain(piece);
            }
            return 0;
        };
        const int forward = mover == rules::Color::Black ? -1 : 1;
        if (moved.kind == 2) return scan(0, forward);
        if (moved.kind == 5)
            return std::max({scan(-1,-1), scan(-1,1), scan(1,-1), scan(1,1)});
        return std::max({scan(-1,0), scan(1,0), scan(0,-1), scan(0,1)});
    }

    // One pass over the child position answers checks, destination safety and
    // direct multi-target pressure. Slider skewers add at most four short rays.
    static AfterTactics analyze_after(const rules::Snapshot& snapshot,
                                      int destination,
                                      rules::Color mover,
                                      int enemy_king,
                                      bool need_destination_attack,
                                      bool hand_drop_tactics) {
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
                if (hand_drop_tactics && i != destination && !out.destination_supported
                    && piece_attacks(snapshot, i, piece, destination))
                    out.destination_supported = true;
                continue;
            }

            if (need_destination_attack
                && (!out.destination_attacked || hand_drop_tactics)
                && piece_attacks(snapshot, i, piece, destination)) {
                const int exchange = capture_gain(piece) - 2 * piece_value(moved.kind, false);
                if (!out.destination_attacked) {
                    out.destination_attacked = true;
                    out.worst_exchange = exchange;
                } else if (hand_drop_tactics) {
                    out.worst_exchange = std::min(out.worst_exchange, exchange);
                }
            }

            if (piece.kind != 8 && moved.kind != 0
                && piece_attacks(snapshot, destination, moved, i)) {
                out.pressured_value = std::max(
                    out.pressured_value, piece_value(piece.kind, piece.promoted));
                if (hand_drop_tactics) {
                    const int gain = capture_gain(piece);
                    if (gain > out.primary_pressured_gain) {
                        out.secondary_pressured_gain = out.primary_pressured_gain;
                        out.primary_pressured_gain = gain;
                    } else if (gain > out.secondary_pressured_gain) {
                        out.secondary_pressured_gain = gain;
                    }
                }
            }
        }
        if (hand_drop_tactics) out.skewer_gain = skewer_gain(snapshot, destination, moved);
        return out;
    }
};

} // namespace shogi::strategy
