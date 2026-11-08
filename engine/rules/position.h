#pragma once

#include <array>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace shogi::rules {

enum class Color { Black, White };
enum class Result { Ongoing, Draw, BlackWin, WhiteWin };
struct Status {
    Result result = Result::Ongoing;
    std::string reason;
};
struct Piece {
    // Empty, Pawn, Lance, Knight, Silver, Bishop, Rook, Gold, King.
    int kind = 0;
    Color color = Color::Black;
    bool promoted = false;
};
struct Snapshot {
    // Index = (file - 1) * 9 + (rank - 'a').
    std::array<Piece, 81> board{};
    // [color][kind - 1], Pawn/Lance/Knight/Silver/Bishop/Rook/Gold.
    std::array<std::array<int, 7>, 2> hands{};
    Color turn = Color::Black;
};

// Opaque rule-layer token for a move generated from one exact position.
// The strategy layer can keep and play it without importing YaneuraOu Move.
class GeneratedMove {
public:
    GeneratedMove() = default;

private:
    friend class Position;
    std::uint32_t encoded_ = 0;
    std::uint64_t source_key_ = 0;
};

// Owns all historical states. No upstream types leak into the strategy API.
// A Position is used on one thread; separate Positions can be used concurrently.
class Position {
public:
    Position();
    ~Position();
    Position(Position&&) noexcept;
    Position& operator=(Position&&) noexcept;
    Position(const Position&) = delete;
    Position& operator=(const Position&) = delete;

    // Transactional: on error the previous position and its history survive.
    bool set(const std::string& sfen, const std::vector<std::string>& moves,
             std::string& error);
    bool set_usi(const std::string& command, std::string& error);
    static std::string start_sfen();
    std::string sfen() const;
    Snapshot snapshot() const;
    Color turn() const;
    std::vector<std::string> legal_moves() const;
    // Rule-layer filtering only: every returned move is legal and gives check.
    // Strategy can use this without importing upstream Move types or search code.
    std::vector<std::string> checking_moves() const;
    // Search fast paths. The token is opaque outside the rules layer, carries
    // the source-position key, and avoids converting every candidate to USI
    // and then regenerating all legal moves merely to play it.
    std::vector<GeneratedMove> legal_generated_moves() const;
    std::vector<GeneratedMove> checking_generated_moves() const;
    // Research (TacticalGen): legal captures and promotions only, for a position
    // that is NOT in check (falls back to the full legal list when it is). The
    // pseudo-legal list is filtered by capture/promotion BEFORE the costly legality
    // test, so quiet moves and drops are never legality-checked. The order is the
    // LEGAL_ALL order restricted to those moves (apart from upstream's
    // swap-with-last removal of illegal moves). When the result is empty,
    // `no_legal_moves` tells whether the side to move has no legal move at all.
    std::vector<GeneratedMove> tactical_generated_moves(bool& no_legal_moves) const;
    std::string generated_move_usi(const GeneratedMove& move) const;
    // A rule-layer check query for a legal token from this exact position.
    bool generated_move_gives_check(const GeneratedMove& move) const;
    // Pure move metadata; filtering choices remain in our strategy layer.
    bool generated_move_is_capture_or_promotion(const GeneratedMove& move) const;
    bool play_generated_move(const GeneratedMove& move, std::string& error);
    bool play(const std::string& move, std::string& error);
    // Fast path for a move obtained from this Position's current legal_moves()
    // or checking_moves(). It still matches the USI move through the pinned
    // rules engine, but skips the redundant terminal scan in play().
    bool play_generated_legal(const std::string& move, std::string& error);
    bool undo();
    bool in_check() const;
    // Research (null-move search): a fresh Position with the same board and
    // hands but the opponent to move, as if the side to move had passed. Built
    // only from this Position's SFEN with the turn field flipped through our
    // own set path; no upstream null-move routine is used. No game history is
    // carried over, so repetition rules do not apply across the pass. Fails
    // (returns false) while in check, because a pass is then not a legal state.
    // When to pass is a search-policy decision that stays in the strategy layer.
    bool pass_position(Position& out, std::string& error) const;
    // Repetition/perpetual-check adjudication only; unlike status(), this does
    // not generate legal moves to test checkmate/stalemate.
    Status repetition_status() const;
    Status status() const;
    // Stable 64-bit position hash (board, hands and side to move). This exposes
    // no upstream search type and is intended for our own caches/diagnostics.
    std::uint64_t hash_key() const;
    // Ordered position history, for score caches whose result can depend on
    // repetition/perpetual check. Board-only keys remain suitable for move hints.
    std::uint64_t history_key() const;
    // True when any exact position hash already appears twice in the owned
    // history. A shallow TT is disabled in this case so repetition semantics
    // cannot be changed by reusing a value reached through a different path.
    bool has_repeated_history() const;
    // CSA 27-point declaration conditions; clock is the GUI's responsibility.
    bool can_declare_win() const;
    Position clone() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
} // namespace shogi::rules
