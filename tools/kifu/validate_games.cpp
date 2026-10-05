#include "rules/position.h"

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {
std::vector<std::string> split_tabs(const std::string& line) {
    std::vector<std::string> fields;
    std::size_t start = 0;
    while (true) {
        const auto pos = line.find('\t', start);
        if (pos == std::string::npos) {
            fields.push_back(line.substr(start));
            return fields;
        }
        fields.push_back(line.substr(start, pos - start));
        start = pos + 1;
    }
}

std::vector<std::string> split_moves(const std::string& text) {
    std::istringstream input(text);
    std::vector<std::string> moves;
    std::string move;
    while (input >> move) moves.push_back(move);
    return moves;
}

int outcome_for_turn(const std::string& winner, shogi::rules::Color turn) {
    if (winner == "draw") return 0;
    if (winner != "black" && winner != "white") return 2; // unknown
    const bool black_won = winner == "black";
    const bool black_to_move = turn == shogi::rules::Color::Black;
    return black_won == black_to_move ? 1 : -1;
}
} // namespace

int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);

    std::string line;
    std::size_t input_line = 0;
    while (std::getline(std::cin, line)) {
        ++input_line;
        if (line.empty()) continue;
        const auto fields = split_tabs(line);
        if (fields.size() != 5) {
            std::cerr << "line " << input_line << ": expected 5 tab-separated fields, got "
                      << fields.size() << '\n';
            return 2;
        }
        const auto& game_id = fields[0];
        const auto& split = fields[1];
        const auto& winner = fields[2];
        const auto& start_sfen = fields[3];
        const auto moves = split_moves(fields[4]);

        shogi::rules::Position position;
        std::string error;
        if (!position.set(start_sfen, {}, error)) {
            std::cerr << "line " << input_line << " game " << game_id
                      << ": invalid start SFEN: " << error << '\n';
            return 3;
        }

        for (std::size_t ply = 0; ply < moves.size(); ++ply) {
            const auto legal = position.legal_moves();
            if (std::find(legal.begin(), legal.end(), moves[ply]) == legal.end()) {
                std::cerr << "line " << input_line << " game " << game_id << " ply "
                          << (ply + 1) << ": illegal move " << moves[ply] << '\n';
                return 4;
            }

            // One row per supervised policy/value sample. SFEN is the position
            // before the expert move. Hash comes from the pinned rule layer.
            std::cout << game_id << '\t' << split << '\t' << (ply + 1) << '\t'
                      << position.hash_key() << '\t' << position.sfen() << '\t'
                      << moves[ply] << '\t' << outcome_for_turn(winner, position.turn()) << '\n';

            if (!position.play_generated_legal(moves[ply], error)) {
                std::cerr << "line " << input_line << " game " << game_id << " ply "
                          << (ply + 1) << ": rule-layer play failed: " << error << '\n';
                return 5;
            }
        }
    }
    return 0;
}
