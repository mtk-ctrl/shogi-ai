from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected 1 match, got {n}")
    return text.replace(old, new, 1)

p = Path('engine/strategy/iterative_search.h')
s = p.read_text()
s = replace_once(s,
'''    void set_dynamic_ordering_enabled(bool enabled) { dynamic_ordering_enabled_ = enabled; }''',
'''    void set_dynamic_ordering_enabled(bool enabled) {
        killer_ordering_enabled_ = enabled;
        history_ordering_enabled_ = enabled;
    }
    void set_killer_ordering_enabled(bool enabled) { killer_ordering_enabled_ = enabled; }
    void set_history_ordering_enabled(bool enabled) { history_ordering_enabled_ = enabled; }''',
'setters')
s = replace_once(s,
'''        const int index = history_index(move, snapshot.turn);
        if (index >= 0) score += history_scores_[index];
        if (ply >= 0 && ply < MaxPly) {
            if (killers_[ply][0] == move) score += 2000000;
            else if (killers_[ply][1] == move) score += 1000000;
        }''',
'''        const int index = history_index(move, snapshot.turn);
        if (history_ordering_enabled_ && index >= 0) score += history_scores_[index];
        if (killer_ordering_enabled_ && ply >= 0 && ply < MaxPly) {
            if (killers_[ply][0] == move) score += 2000000;
            else if (killers_[ply][1] == move) score += 1000000;
        }''',
'score gates')
s = replace_once(s,
'''        if (!dynamic_ordering_enabled_) return;
        const auto snapshot = p.snapshot();
        if (!quiet_move(snapshot, move)) return;
        if (ply >= 0 && ply < MaxPly) {''',
'''        if (!killer_ordering_enabled_ && !history_ordering_enabled_) return;
        const auto snapshot = p.snapshot();
        if (!quiet_move(snapshot, move)) return;
        if (killer_ordering_enabled_ && ply >= 0 && ply < MaxPly) {''',
'cutoff killer gate')
s = replace_once(s,
'''        const int index = history_index(move, snapshot.turn);
        if (index >= 0) {''',
'''        const int index = history_index(move, snapshot.turn);
        if (history_ordering_enabled_ && index >= 0) {''',
'cutoff history gate')
s = replace_once(s,
'''        if (dynamic_ordering_enabled_ && ply >= 0) {''',
'''        if ((killer_ordering_enabled_ || history_ordering_enabled_) && ply >= 0) {''',
'ordering gate')
s = replace_once(s,
'''    bool experience_enabled_ = false;
    bool quiescence_enabled_ = true;
    bool dynamic_ordering_enabled_ = true;
    bool experience_allowed_ = false;''',
'''    bool experience_enabled_ = false;
    bool quiescence_enabled_ = true;
    bool killer_ordering_enabled_ = true;
    bool history_ordering_enabled_ = true;
    bool experience_allowed_ = false;''',
'members')
p.write_text(s)

p = Path('engine/main.cpp')
s = p.read_text()
s = replace_once(s,
'''    bool mate_assist_enabled = true;
    bool opening_book_enabled = true;''',
'''    bool mate_assist_enabled = true;
    bool killer_ordering_enabled = true;
    bool history_ordering_enabled = true;
    bool opening_book_enabled = true;''',
'main vars')
s = replace_once(s,
'''                      << "option name MateAssist type check default true\\n"
                      << "option name OpeningBook type check default true\\n"''',
'''                      << "option name MateAssist type check default true\\n"
                      << "option name KillerOrdering type check default true\\n"
                      << "option name HistoryOrdering type check default true\\n"
                      << "option name OpeningBook type check default true\\n"''',
'usi options')
s = replace_once(s,
'''                } else if (name == "MateAssist") {
                    if (value == "true" || value == "false") mate_assist_enabled = value == "true";
                } else if (name == "OpeningBook") {''',
'''                } else if (name == "MateAssist") {
                    if (value == "true" || value == "false") mate_assist_enabled = value == "true";
                } else if (name == "KillerOrdering") {
                    if (value == "true" || value == "false") {
                        killer_ordering_enabled = value == "true";
                        strategy.set_killer_ordering_enabled(killer_ordering_enabled);
                    }
                } else if (name == "HistoryOrdering") {
                    if (value == "true" || value == "false") {
                        history_ordering_enabled = value == "true";
                        strategy.set_history_ordering_enabled(history_ordering_enabled);
                    }
                } else if (name == "OpeningBook") {''',
'setoption split')
p.write_text(s)
