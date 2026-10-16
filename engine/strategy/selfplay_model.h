#pragma once
// Small self-written outcome-trained residual. No external engine evaluator.
#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <istream>
#include <sstream>
#include <string>
#include <string_view>

namespace shogi::strategy {
class SelfPlayModel {
public:
    static constexpr int Inputs=12, MaxHidden=8;
    using Features=std::array<double,Inputs>;

    bool load(std::istream& in) {
        *this=SelfPlayModel{};
        SelfPlayModel next;
        std::string magic, end, extra;
        int inputs=0;
        if(!(in>>magic>>inputs>>next.hidden_>>next.cap_)
           || magic!="KUMOJI_SELFPLAY_RESIDUAL_V1" || inputs!=Inputs
           || next.hidden_<1 || next.hidden_>MaxHidden || next.cap_<1 || next.cap_>1000)
            return false;
        auto weight=[&](double& x) {
            return bool(in>>x) && std::isfinite(x) && std::abs(x)<=32.0;
        };
        for(int j=0;j<next.hidden_;++j)
            for(auto& w:next.w1_[j]) if(!weight(w)) return false;
        for(int j=0;j<next.hidden_;++j) if(!weight(next.w2_[j])) return false;
        if(!(in>>end) || end!="END" || (in>>extra)) return false;
        next.valid_=true;
        *this=next;
        return true;
    }
    bool load_file(const std::string& path) {
        std::ifstream in(path);
        return load(in);
    }
    bool load_text(std::string_view text) {
        std::istringstream in{std::string(text)};
        return load(in);
    }
    bool valid() const {return valid_;}
    int correction(const Features& x) const {
        if(!valid_) return 0;
        double out=0;
        for(int j=0;j<hidden_;++j) {
            double z=0;
            for(int i=0;i<Inputs;++i) {
                if(!std::isfinite(x[i])) return 0;
                z+=std::clamp(x[i],-4.0,4.0)*w1_[j][i];
            }
            out+=w2_[j]*std::tanh(z);
        }
        return int(std::lround(cap_*std::tanh(out)));
    }
private:
    std::array<std::array<double,Inputs>,MaxHidden> w1_{};
    std::array<double,MaxHidden> w2_{};
    int hidden_=0,cap_=0;
    bool valid_=false;
};
}
