#include "rules/position.h"
#include "strategy/opening_book.h"
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {
void require(bool ok, const std::string& message) {
    if (!ok) { std::cerr << "FAIL: " << message << '\n'; std::exit(1); }
}
}

int main() {
    shogi::rules::Position position;
    const auto key = position.hash_key();
    const std::string path = "build/opening-book-test.tsv";
    {
        std::ofstream out(path);
        out << "# shogi-ai opening book v1\n";
        out << key << "\t7g7f\t20\t12\t0\t8\t583\t400\n";
        out << key << "\t2g2f\t10\t5\t0\t5\t500\t200\n";
    }
    shogi::strategy::OpeningBook book;
    require(book.load(path), "valid book should load");
    require(book.positions() == 1 && book.entries() == 2, "book counts");
    const auto legal = position.legal_moves();
    const auto a = book.pick(key, legal, 12345);
    const auto b = book.pick(key, legal, 12345);
    require(a && b && a->move == b->move, "same seed must be deterministic");
    require(a->move == "7g7f" || a->move == "2g2f", "stored legal move expected");
    require(book.pick(key, {"2g2f"}, 999)->move == "2g2f", "restriction must be respected");
    require(!book.pick(key + 1, legal, 1), "unknown position should miss");

    std::ostringstream text;
    text << "# in-memory book\n"
         << key << "\t7g7f\t4\t3\t0\t1\t750\t100\n";
    shogi::strategy::OpeningBook memory_book;
    require(memory_book.load_text(text.str()), "in-memory book should load");
    require(memory_book.positions() == 1 && memory_book.entries() == 1,
            "in-memory book counts");
    const auto in_memory = memory_book.pick(key, legal, 7);
    require(in_memory && in_memory->move == "7g7f", "in-memory book move");

    std::remove(path.c_str());
    std::cout << "opening book tests passed\n";
}
