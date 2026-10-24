// Deterministic arithmetic / differential update test for the research NNUE.
// No external weights, no search dependency, no comparison games.
#include "strategy/nnue_eval.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <string>

static void u16(std::ofstream& f, unsigned value) {
    f.put(static_cast<char>(value & 255));
    f.put(static_cast<char>((value >> 8) & 255));
}
static void u32(std::ofstream& f, std::uint32_t value) {
    u16(f, value & 65535);
    u16(f, value >> 16);
}
int main() {
    using shogi::strategy::NnueModel;
    using namespace shogi::rules;
    const std::string path = "build/nnue-arithmetic-fixture.bin";
    {
        std::ofstream f(path, std::ios::binary);
        f.write("KMNNUE01", 8);
        u32(f, 16);
        u32(f, NnueModel::Features);
        for (int i = 0; i < 16; ++i) u32(f, 0);
        for (std::uint32_t feature = 0; feature < NnueModel::Features; ++feature)
            for (int neuron = 0; neuron < 16; ++neuron)
                u16(f, feature == 0 && neuron == 0 ? 128 : 0);
        for (int i = 0; i < 16; ++i) u16(f, i == 0 ? 256 : 0);
        u32(f, 0);
    }
    NnueModel model;
    assert(model.load(path) && model.width() == 16);
    Snapshot a;
    a.board[0] = {1, Color::Black, false};
    Snapshot b = a;
    b.board[0] = {};
    b.board[9] = {1, Color::Black, false};
    assert(model.evaluate(a) == 500);
    assert(model.evaluate(b) == 0);
    assert(model.score(model.update(a, b, model.accumulate(a))) == model.evaluate(b));
    assert(model.score(model.update(b, a, model.accumulate(b))) == model.evaluate(a));
    Snapshot c = a;
    c.board[0] = {};
    c.hands[0][0] = 1;
    c.turn = Color::White;
    assert(model.score(model.update(a, c, model.accumulate(a))) == model.evaluate(c));
    { std::ofstream f(path, std::ios::binary | std::ios::trunc); f << "bad"; }
    assert(!model.load(path)); // Bad replacement does not destroy a loaded model.
    assert(model.evaluate(a) == 500);
    std::remove(path.c_str());
}
