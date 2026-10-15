# Profiling and fourth hypothesis

The first three flags did not demonstrate a useful gain in the preliminary 12-position fixed-depth screen. See initial-screening-summary.json; the original raw screen is kept separately locally and its digest is recorded.

A gprof-instrumented research build using mask0 ran the same12 positions at depth2. A roughly1.18s sampled flat profile showed millions of to_usi_string calls (about7.3M). Sampling and instrumentation limit any percentage interpretation; this is a bottleneck hypothesis, not speed evidence.

Inspection of our qsearch found conversion of every legal token to USI before discarding quiet/nonpromotion moves. SelectiveUSI (bit8 of the NEW SearchEfficiencyMask) first uses rules metadata to select captures/promotions, preserving token order and terminal generation. Checked nodes still use every legal evasion. This is separate from the older SearchResearchMask bit8 (experimental qsearch score reuse), which remains OFF in adopted mask23.

The fourth hypothesis and expanded16-mask screen are recorded in PLAN.md before measuring the new build. Production main and evaluation/search decisions are unchanged. Bounded regression currently matches official v2.0.14 exactly, including move, score, depth, nodes, qnodes, cutoffs and PV; metadata/order/history verification covers400 positions and16,386 legal moves.
