#include "rules/position.h"
#include <position.h>
#include <movegen.h>
#include <algorithm>
#include <climits>
#include <cctype>
#include <deque>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <unordered_set>

namespace shogi::rules {
namespace yo = YaneuraOu;
namespace {
// Bounds-check untrusted SFEN before passing it to the upstream fast parser.
bool validate_sfen(const std::string& sfen, std::string& error) {
    auto fail = [&] { error = "invalid SFEN"; return false; };
    std::istringstream in(sfen);
    std::string board, side, hand, ply, extra;
    if (!(in >> board >> side >> hand >> ply) || in >> extra) return fail();
    if (side != "b" && side != "w") return fail();
    if (ply.empty() || ply.size() > 8 || ply.find_first_not_of("0123456789") != std::string::npos
        || std::stoul(ply) < 1) return fail();
    const std::string kinds = "PLNSBRGK";
    const int limits[] = {18, 4, 4, 4, 2, 2, 4, 2};
    int totals[8] = {}, kings[2] = {}, rank = 0, file = 0;
    bool promoted = false;
    for (char c : board) {
        if (c == '+') { if (promoted) return fail(); promoted = true; continue; }
        if (c == '/') {
            if (promoted || file != 9 || ++rank > 8) return fail();
            file = 0; continue;
        }
        if (c >= '1' && c <= '9') {
            if (promoted) return fail();
            file += c - '0';
        } else {
            auto upper = char(std::toupper(static_cast<unsigned char>(c)));
            auto k = kinds.find(upper);
            if (k == std::string::npos || (promoted && k >= 6)) return fail();
            if (++totals[k] > limits[k]) return fail();
            if (k == 7) ++kings[c == 'K' ? 0 : 1];
            ++file; promoted = false;
        }
        if (file > 9) return fail();
    }
    if (rank != 8 || file != 9 || promoted || kings[0] != 1 || kings[1] != 1) return fail();
    if (hand != "-") {
        int count = 0;
        bool digits = false;
        std::string seen;
        for (char c : hand) {
            if (c >= '0' && c <= '9') {
                if ((!digits && c == '0') || count > 18) return fail();
                count = count * 10 + c - '0'; digits = true;
                if (count > 18) return fail();
            } else {
                auto k = kinds.find(char(std::toupper(static_cast<unsigned char>(c))));
                if (k >= 7 || seen.find(c) != std::string::npos) return fail();
                seen += c;
                totals[k] += digits ? count : 1;
                if (totals[k] > limits[k]) return fail();
                count = 0; digits = false;
            }
        }
        if (digits) return fail();
    }
    return true;
}
Result win_for(yo::Color side) { return side == yo::BLACK ? Result::BlackWin : Result::WhiteWin; }
std::uint64_t key64(const yo::Key& key) { return static_cast<std::uint64_t>(yo::Key64(key)); }
}

struct Position::Impl {
    yo::Position pos;
    std::deque<yo::StateInfo> states;
    std::vector<yo::Move> moves;
    std::string initial;
    explicit Impl(const std::string& sfen) : initial(sfen) {
        static std::once_flag initialized;
        std::call_once(initialized, [] {
            yo::Bitboards::init();
            yo::Position::init();
            yo::Position configuration;
            configuration.set_max_repetition_ply(INT_MAX);
        });
        std::string error;
        if (!validate_sfen(sfen, error)) throw std::invalid_argument(error);
        states.emplace_back();
        if (auto invalid = pos.set(sfen, &states.back())) throw std::invalid_argument(invalid->what());
        if (!pos.pos_is_ok()) throw std::invalid_argument("inconsistent SFEN (including non-moving king in check)");
        pos.set_ekr(yo::EKR_27_POINT);
    }
};

Position::Position() : impl_(std::make_unique<Impl>(start_sfen())) {}
Position::~Position() = default;
Position::Position(Position&&) noexcept = default;
Position& Position::operator=(Position&&) noexcept = default;
std::string Position::start_sfen() { return yo::StartSFEN; }

bool Position::set(const std::string& sfen, const std::vector<std::string>& moves, std::string& error) {
    try {
        Position next;
        next.impl_ = std::make_unique<Impl>(sfen);
        for (const auto& move : moves) if (!next.play(move, error)) return false;
        impl_.swap(next.impl_);
        error.clear(); return true;
    } catch (const std::invalid_argument& e) { error = e.what(); return false; }
}

bool Position::set_usi(const std::string& command, std::string& error) {
    std::istringstream input(command);
    std::string token, base, part;
    std::vector<std::string> moves;
    auto fail = [&] { error = "invalid position command"; return false; };
    if (!(input >> token) || token != "position" || !(input >> token)) return fail();
    if (token == "startpos") base = start_sfen();
    else if (token == "sfen") {
        for (int i = 0; i < 4; ++i) {
            if (!(input >> part)) return fail();
            if (i) base += ' ';
            base += part;
        }
    } else return fail();
    if (input >> token) {
        if (token != "moves") return fail();
        while (input >> token) moves.push_back(token);
    }
    return set(base, moves, error);
}

std::string Position::sfen() const { return impl_->pos.sfen(); }
std::vector<std::string> Position::played_moves() const {
    std::vector<std::string> out;
    out.reserve(impl_->moves.size());
    for (const auto& m:impl_->moves) out.push_back(yo::to_usi_string(m));
    return out;
}
bool Position::in_check() const { return bool(impl_->pos.checkers()); }
Color Position::turn() const { return impl_->pos.side_to_move() == yo::BLACK ? Color::Black : Color::White; }
std::vector<std::string> Position::legal_moves() const {
    std::vector<std::string> result;
    for (auto move : yo::MoveList<yo::LEGAL_ALL>(impl_->pos)) result.push_back(yo::to_usi_string(move));
    return result;
}
std::vector<std::string> Position::checking_moves() const {
    std::vector<std::string> result;
    for (auto move : yo::MoveList<yo::LEGAL_ALL>(impl_->pos))
        if (impl_->pos.gives_check(move)) result.push_back(yo::to_usi_string(move));
    return result;
}
std::vector<GeneratedMove> Position::legal_generated_moves() const {
    std::vector<GeneratedMove> result;
    const auto source_key = key64(impl_->pos.key());
    for (auto move : yo::MoveList<yo::LEGAL_ALL>(impl_->pos)) {
        GeneratedMove generated;
        generated.encoded_ = move.to_u32();
        generated.source_key_ = source_key;
        result.push_back(generated);
    }
    return result;
}
std::vector<GeneratedMove> Position::checking_generated_moves() const {
    std::vector<GeneratedMove> result;
    const auto source_key = key64(impl_->pos.key());
    auto append = [&](yo::Move move) {
        GeneratedMove generated;
        generated.encoded_ = move.to_u32();
        generated.source_key_ = source_key;
        result.push_back(generated);
    };

    // CHECKS_ALL directly generates checking candidates and also preserves the
    // optional non-promotions required by this project. It is pseudo-legal, so
    // filter with the pinned rule engine's legal() check. If the attacker is
    // itself in check (possible after a checking evasion), retain the exact
    // LEGAL_ALL + gives_check path to make the counter-check case conservative.
    if (impl_->pos.in_check()) {
        for (auto move : yo::MoveList<yo::LEGAL_ALL>(impl_->pos))
            if (impl_->pos.gives_check(move)) append(move);
    } else {
        for (auto move : yo::MoveList<yo::CHECKS_ALL>(impl_->pos))
            if (impl_->pos.legal(move)) append(move);
    }
    return result;
}
std::string Position::generated_move_usi(const GeneratedMove& move) const {
    return yo::to_usi_string(yo::Move(move.encoded_));
}
bool Position::play_generated_move(const GeneratedMove& move, std::string& error) {
    // GeneratedMove is opaque and can only be populated by Position. The key
    // check prevents accidentally playing a token after the position changed.
    if (move.source_key_ != key64(impl_->pos.key())) {
        error = "generated move belongs to a different position";
        return false;
    }
    yo::Move m(move.encoded_);
    if (!m.is_ok()) {
        error = "invalid generated move";
        return false;
    }
    impl_->moves.push_back(m);
    try { impl_->states.emplace_back(); }
    catch (...) { impl_->moves.pop_back(); throw; }
    impl_->pos.do_move(m, impl_->states.back());
    error.clear(); return true;
}
bool Position::play(const std::string& move, std::string& error) {
    if (status().result != Result::Ongoing) { error = "game already ended"; return false; }
    for (yo::Move m : yo::MoveList<yo::LEGAL_ALL>(impl_->pos)) {
        if (yo::to_usi_string(m) != move) continue;
        impl_->moves.push_back(m);
        try { impl_->states.emplace_back(); }
        catch (...) { impl_->moves.pop_back(); throw; }
        impl_->pos.do_move(m, impl_->states.back());
        error.clear(); return true;
    }
    error = "illegal move: " + move; return false;
}
bool Position::play_generated_legal(const std::string& move, std::string& error) {
    // Caller obtained the string from the current legal/checking move list and
    // has already established that the node is ongoing. Keep the usual legal
    // move lookup as a safety net, but skip play()'s duplicate status() scan.
    for (yo::Move m : yo::MoveList<yo::LEGAL_ALL>(impl_->pos)) {
        if (yo::to_usi_string(m) != move) continue;
        impl_->moves.push_back(m);
        try { impl_->states.emplace_back(); }
        catch (...) { impl_->moves.pop_back(); throw; }
        impl_->pos.do_move(m, impl_->states.back());
        error.clear(); return true;
    }
    error = "generated move no longer legal: " + move; return false;
}
bool Position::undo() {
    if (impl_->moves.empty()) return false;
    impl_->pos.undo_move(impl_->moves.back());
    impl_->moves.pop_back(); impl_->states.pop_back(); return true;
}
Status Position::repetition_status() const {
    switch (impl_->pos.is_repetition(0)) {
        case yo::REPETITION_DRAW: return {Result::Draw, "fourfold repetition"};
        case yo::REPETITION_WIN: return {win_for(impl_->pos.side_to_move()), "perpetual check"};
        case yo::REPETITION_LOSE: return {win_for(~impl_->pos.side_to_move()), "perpetual check"};
        default: return {};
    }
}
Status Position::status() const {
    const auto repetition = repetition_status();
    if (repetition.result != Result::Ongoing) return repetition;
    if (yo::MoveList<yo::LEGAL_ALL>(impl_->pos).size() == 0)
        return {win_for(~impl_->pos.side_to_move()), in_check() ? "checkmate" : "no legal moves"};
    return {};
}
std::uint64_t Position::hash_key() const { return key64(impl_->pos.key()); }
std::uint64_t Position::history_key() const {
    std::uint64_t h = 1469598103934665603ULL;
    for (const auto& state : impl_->states)
        h = (h ^ key64(state.key())) * 1099511628211ULL;
    return h;
}
bool Position::has_repeated_history() const {
    std::unordered_set<std::uint64_t> seen;
    seen.reserve(impl_->states.size() * 2 + 1);
    for (const auto& state : impl_->states) {
        if (!seen.insert(key64(state.key())).second) return true;
    }
    return false;
}
bool Position::can_declare_win() const { return impl_->pos.DeclarationWin() == yo::Move::win(); }
Snapshot Position::snapshot() const {
    Snapshot out;
    out.turn = turn();
    for (int i = 0; i < 81; ++i) {
        auto pc = impl_->pos.piece_on(yo::Square(i));
        if (pc == yo::NO_PIECE) continue;
        const int kind = yo::type_of(pc) == yo::KING ? 8 : int(yo::raw_type_of(pc));
        out.board[i] = {kind, yo::color_of(pc) == yo::BLACK ? Color::Black : Color::White,
                        yo::is_promoted(pc)};
    }
    for (int c = 0; c < 2; ++c) for (int k = 1; k <= 7; ++k)
        out.hands[c][k-1] = yo::hand_count(impl_->pos.hand_of(yo::Color(c)), yo::PieceType(k));
    return out;
}
Position Position::clone() const {
    Position result;
    std::vector<std::string> moves;
    for (auto m : impl_->moves) moves.push_back(yo::to_usi_string(m));
    std::string error;
    if (!result.set(impl_->initial, moves, error)) throw std::logic_error(error);
    return result;
}
} // namespace shogi::rules
