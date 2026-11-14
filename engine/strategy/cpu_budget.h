#pragma once
// Number of CPU cores this process may actually use. Used only to cap the
// number of search threads; 0 means "unknown" (callers then do not cap).
#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <thread>
#ifdef __linux__
#include <sched.h>
#endif

namespace shogi::strategy {
// cgroup CPU quota ("max 100000" or "150000 100000") -> whole cores, 0 = no limit/unknown.
inline unsigned cores_from_quota(const std::string& quota, const std::string& period) {
    if (quota.empty() || quota == "max" || quota == "-1") return 0;
    try {
        const double q = std::stod(quota), p = std::stod(period);
        if (q <= 0 || p <= 0) return 0;
        // A second thread only pays off with (nearly) two full cores.
        return std::max(1u, static_cast<unsigned>(std::floor(q / p + 0.05)));
    } catch (...) { return 0; }
}
inline unsigned available_cores() {
    unsigned cores = std::thread::hardware_concurrency();
#ifdef __linux__
    cpu_set_t set;
    CPU_ZERO(&set);
    if (sched_getaffinity(0, sizeof(set), &set) == 0) {
        const int allowed = CPU_COUNT(&set);
        if (allowed > 0) cores = cores ? std::min(cores, static_cast<unsigned>(allowed))
                                       : static_cast<unsigned>(allowed);
    }
    unsigned quota_cores = 0;
    if (std::ifstream v2("/sys/fs/cgroup/cpu.max"); v2) {
        std::string quota, period;
        if (v2 >> quota >> period) quota_cores = cores_from_quota(quota, period);
    } else {
        std::ifstream q("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), p("/sys/fs/cgroup/cpu/cpu.cfs_period_us");
        std::string quota, period;
        if (q && p && (q >> quota) && (p >> period)) quota_cores = cores_from_quota(quota, period);
    }
    if (quota_cores) cores = cores ? std::min(cores, quota_cores) : quota_cores;
#endif
    return cores;
}
// Threads to really use: the requested count, capped by usable cores when known.
inline unsigned effective_threads(unsigned requested, unsigned cores, bool auto_cap) {
    if (!auto_cap || cores == 0) return requested;
    return std::max(1u, std::min(requested, cores));
}
}
