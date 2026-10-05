// GPL-3.0. The move formatter is adapted from YaneuraOu usi.cpp at the pinned
// revision. Small runtime helpers keep the full USI/search runtime out.
#include "types.h"
#include "misc.h"
#include <cstdlib>
#include <mutex>
#include <sstream>

#if defined(USE_EVAL) || defined(USE_PIECE_VALUE) || defined(USE_SEE) || \
    defined(USE_MOVE_PICKER) || defined(USE_MATE_1PLY) || defined(USE_MATE_SOLVER) || \
    defined(USE_MATE_DFPN) || defined(YANEURAOU_ENGINE) || defined(ENABLE_QUICK_DRAW)
#error "Rules library must not enable upstream strategy or approximate repetition"
#endif

namespace YaneuraOu {
std::string to_usi_string(Move m) { return to_usi_string(m.to_move16()); }
std::string to_usi_string(Move16 m) {
    std::ostringstream ss;
    if (!m.is_ok()) {
        if (m.to_u16() == MOVE_RESIGN) return "resign";
        if (m.to_u16() == MOVE_WIN) return "win";
        if (m.to_u16() == MOVE_NULL) return "null";
        return "none";
    }
    if (m.is_drop()) ss << m.move_dropped_piece() << '*' << m.to_sq();
    else {
        ss << m.from_sq() << m.to_sq();
        if (m.is_promote()) ss << '+';
    }
    return ss.str();
}
std::ostream& operator<<(std::ostream& os, SyncCout action) {
    static std::mutex mutex;
    if (action == IO_LOCK) mutex.lock();
    else mutex.unlock();
    return os;
}
namespace Tools { void exit() { std::exit(EXIT_FAILURE); } }
} // namespace YaneuraOu
