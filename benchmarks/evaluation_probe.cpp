// Test/measurement-only interface. Production USI has only the small `eval` command.
#include "strategy/evaluation.h"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <string>
#include <vector>
using namespace shogi;
int main(int argc,char** argv){try{
    const std::string mode=argc>1?argv[1]:"--inspect";
    const int repeats=argc>2?std::stoi(argv[2]):2000;
    std::vector<rules::Snapshot> samples;std::string line,error;
    while(std::getline(std::cin,line)){
        if(line.empty())continue;
        rules::Position p;if(!p.set(line,{},error))throw std::runtime_error(error+": "+line);
        auto s=p.snapshot();samples.push_back(s);
        if(mode=="--bench")continue;
        const auto b=strategy::evaluate(s);
        std::cout<<"{\"material\":"<<b.material<<",\"safety\":"<<b.terms[0]<<",\"pressure\":"<<b.terms[1]
                 <<",\"activity\":"<<b.terms[2]<<",\"danger\":"<<b.terms[3]<<",\"potential\":"<<b.terms[4]<<",\"clamp\":"<<b.clamp_adjustment<<",\"total\":"<<b.total;
        if(mode=="--attacks"){
            strategy::AttackMap a(s);std::cout<<",\"attacks\":[";
            for(int c=0;c<2;++c){if(c)std::cout<<',';std::cout<<'[';for(int i=0;i<81;++i){if(i)std::cout<<',';std::cout<<a.count[c][i];}std::cout<<']';}std::cout<<']';
        }
        std::cout<<"}\n";
    }
    if(mode=="--bench"){
        if(samples.empty()||repeats<1)throw std::runtime_error("need samples and positive repeat count");
        volatile std::int64_t checksum=0;
        auto measure=[&](auto evaluator){
            auto start=std::chrono::steady_clock::now();
            for(int n=0;n<repeats;++n)for(const auto& s:samples)checksum+=evaluator(s);
            return std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/(repeats*samples.size());
        };
        // Interleave trials and report medians externally; no wall clock in production leaf evals.
        std::cout<<"{\"samples\":"<<samples.size()<<",\"repeats\":"<<repeats<<",\"trials\":[";
        for(int trial=0;trial<5;++trial){if(trial)std::cout<<',';
            double m=0,f=0;
            if(trial%2){f=measure(strategy::FeatureEvaluator{});m=measure(strategy::MaterialEvaluator{});}
            else {m=measure(strategy::MaterialEvaluator{});f=measure(strategy::FeatureEvaluator{});}
            std::cout<<"{\"material_ns\":"<<m<<",\"features_ns\":"<<f<<'}';
        }
        std::cout<<"],\"checksum\":"<<checksum<<"}\n";
    }
}catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}}
