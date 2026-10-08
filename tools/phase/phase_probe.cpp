#include "rules/position.h"
#include "strategy/phase_diagnostics.h"
#include <iostream>
#include <string>

int main() {
    shogi::rules::Position position;
    std::string line, error;
    while(std::getline(std::cin,line)) {
        if(line.empty()) continue;
        if(!position.set_usi(line,error)) {
            std::cerr << "invalid position: " << error << '\n';
            return 1;
        }
        const auto p=shogi::strategy::diagnose_phase(position.snapshot());
        std::cout << "phase development " << p.development
                  << " battle " << p.battle
                  << " invasion " << p.invasion
                  << " king_threat " << p.king_threat
                  << " progress " << p.provisional_progress << '\n';
    }
}
