#pragma once

#include "rules/position.h"
#include <algorithm>
#include <string>
#include <vector>

namespace shogi::strategy {

// Playing-policy rule for our own moves only.
// Pawn -> promoted pawn, bishop -> horse, and rook -> dragon strictly add
// movement capability without losing the original moves. If both the promoted
// and non-promoted forms of the same legal move are available, suppress the
// non-promoted form. Silver/knight/lance remain untouched because promotion can
// change rather than strictly extend their useful movement.
class PromotionPolicy {
public:
    static std::vector<std::string> force_monotonic_promotions(
        const rules::Snapshot& snapshot,
        const std::vector<std::string>& moves) {
        std::vector<std::string> result;
        result.reserve(moves.size());
        for (const auto& move : moves) {
            if (!suppress_nonpromotion(snapshot, moves, move))
                result.push_back(move);
        }
        return result;
    }

private:
    static int square_index(char file, char rank) {
        if (file < '1' || file > '9' || rank < 'a' || rank > 'i') return -1;
        return (file - '1') * 9 + (rank - 'a');
    }

    static bool monotonic_promotion_piece(const rules::Piece& piece) {
        return !piece.promoted && (piece.kind == 1 || piece.kind == 5 || piece.kind == 6);
    }

    static bool suppress_nonpromotion(const rules::Snapshot& snapshot,
                                      const std::vector<std::string>& moves,
                                      const std::string& move) {
        // Normal non-drop USI move is exactly four characters, e.g. 5c5b.
        // Promotion is the same move with a trailing '+'.
        if (move.size() != 4 || move[1] == '*') return false;
        const int src = square_index(move[0], move[1]);
        if (src < 0) return false;
        const auto& piece = snapshot.board[src];
        if (piece.kind == 0 || piece.color != snapshot.turn || !monotonic_promotion_piece(piece))
            return false;

        // Only suppress when the promoted twin is present in the current
        // candidate set. This preserves USI searchmoves constraints.
        const std::string promoted = move + "+";
        return std::find(moves.begin(), moves.end(), promoted) != moves.end();
    }
};

} // namespace shogi::strategy
