// cpu_tb.cpp — strict RV32I simulator harness.
#include "Vcpu.h"
#include "Vcpu___024root.h"
#include "verilated.h"
#include "verilated_vcd_c.h"
#include "verilated_cov.h"
#include <algorithm>
#include <array>
#include <cctype>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace {
enum class RunMode { Tohost, SelfLoop, Snapshot };
struct Reference {
    uint32_t cycles = 0;
    std::optional<uint32_t> stalls;
    std::array<std::optional<uint32_t>, 32> regs;
};

static std::vector<std::string> values_for(int argc, char** argv, const char* prefix) {
    std::vector<std::string> values;
    const size_t length = strlen(prefix);
    for (int i = 1; i < argc; ++i)
        if (strncmp(argv[i], prefix, length) == 0) values.emplace_back(argv[i] + length);
    return values;
}

static bool has_arg(int argc, char** argv, const char* arg) {
    for (int i = 1; i < argc; ++i) if (strcmp(argv[i], arg) == 0) return true;
    return false;
}

static std::string trim(std::string value) {
    size_t first = 0, last = value.size();
    while (first < last && std::isspace(static_cast<unsigned char>(value[first]))) ++first;
    while (last > first && std::isspace(static_cast<unsigned char>(value[last - 1]))) --last;
    return value.substr(first, last - first);
}

static bool parse_u32(const std::string& text, uint32_t& value) {
    if (text.empty() || text[0] == '+' || text[0] == '-') return false;
    int base = 10;
    size_t first = 0;
    if (text.size() >= 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X')) base = 16, first = 2;
    if (first == text.size()) return false;
    for (size_t i = first; i < text.size(); ++i) {
        unsigned char c = static_cast<unsigned char>(text[i]);
        const bool valid = base == 10 ? std::isdigit(c)
                           : std::isdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
        if (!valid) return false;
    }
    try {
        size_t used = 0;
        const unsigned long long parsed = std::stoull(text, &used, base);
        if (used != text.size() || parsed > std::numeric_limits<uint32_t>::max()) return false;
        value = static_cast<uint32_t>(parsed);
        return true;
    } catch (const std::exception&) { return false; }
}

static bool looks_like_unsigned_number(const std::string& text) {
    if (text.empty()) return false;
    if (text[0] == '+' || text[0] == '-') return true;
    const bool hex = text.size() >= 2 && text[0] == '0' && (text[1] == 'x' || text[1] == 'X');
    const size_t first = hex ? 2 : 0;
    if (first == text.size()) return false;
    return std::all_of(text.begin() + first, text.end(), [hex](unsigned char c) {
        return hex ? std::isdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')
                   : std::isdigit(c);
    });
}

static bool load_reference(const std::string& path, Reference& reference) {
    std::ifstream file(path);
    if (!file) { std::cerr << "error: cannot read reference file: " << path << "\n"; return false; }
    bool saw_entry = false, saw_cycles = false, saw_stalls = false;
    std::string line;
    while (std::getline(file, line)) {
        line = trim(line);
        if (line.empty() || line[0] == '#') continue;
        const size_t equal = line.find('=');
        if (equal == std::string::npos || equal == 0 || equal != line.rfind('=')) {
            std::cerr << "error: malformed reference entry: " << line << "\n";
            return false;
        }
        const std::string key = trim(line.substr(0, equal));
        const std::string value_text = trim(line.substr(equal + 1));
        uint32_t value = 0;
        if (key == "cycles" || key == "stalls" || (!key.empty() && key[0] == 'x')) {
            if (!parse_u32(value_text, value)) {
                if (looks_like_unsigned_number(value_text))
                    std::cerr << "error: invalid unsigned reference value: " << value_text << "\n";
                else
                    std::cerr << "error: malformed reference entry: " << line << "\n";
                return false;
            }
        }
        if (key == "cycles") {
            if (saw_cycles) { std::cerr << "error: duplicate reference key: cycles\n"; return false; }
            reference.cycles = value; saw_cycles = true;
        } else if (key == "stalls") {
            if (saw_stalls) { std::cerr << "error: duplicate reference key: stalls\n"; return false; }
            reference.stalls = value; saw_stalls = true;
        } else if (!key.empty() && key[0] == 'x') {
            if (key.size() == 1 || !std::all_of(key.begin() + 1, key.end(), [](unsigned char c) { return std::isdigit(c); })) {
                std::cerr << "error: malformed reference entry: " << line << "\n";
                return false;
            }
            if (key.size() > 2 && key[1] == '0') {
                std::cerr << "error: malformed reference register key: " << key << "\n";
                return false;
            }
            uint32_t reg = 0;
            if (!parse_u32(key.substr(1), reg) || reg > 31) {
                std::cerr << "error: reference register out of range: " << key << "\n";
                return false;
            }
            if (reference.regs[reg].has_value()) {
                std::cerr << "error: duplicate reference key: " << key << "\n";
                return false;
            }
            reference.regs[reg] = value;
        } else {
            std::cerr << "error: unknown reference key: " << key << "\n";
            return false;
        }
        saw_entry = true;
    }
    if (!file.eof()) { std::cerr << "error: cannot read reference file: " << path << "\n"; return false; }
    if (!saw_entry) { std::cerr << "error: empty reference file: " << path << "\n"; return false; }
    return true;
}

static bool parse_run_mode(int argc, char** argv, RunMode& mode, uint32_t& cycles) {
    const auto stops = values_for(argc, argv, "+STOP=");
    const auto snapshots = values_for(argc, argv, "+SNAPSHOT=");
    if (stops.size() > 1 || snapshots.size() > 1) { std::cerr << "error: duplicate run mode\n"; return false; }
    if (!stops.empty() && !snapshots.empty()) { std::cerr << "error: mutually exclusive run modes\n"; return false; }
    if (stops.empty() && snapshots.empty()) { std::cerr << "error: exactly one run mode is required\n"; return false; }
    if (!stops.empty()) {
        if (stops[0] == "tohost") mode = RunMode::Tohost;
        else if (stops[0] == "selfloop") mode = RunMode::SelfLoop;
        else { std::cerr << "error: unknown stop mode: " << stops[0] << "\n"; return false; }
    } else {
        if (snapshots[0] != "1") { std::cerr << "error: unknown snapshot mode: " << snapshots[0] << "\n"; return false; }
        mode = RunMode::Snapshot;
    }
    const auto cycle_args = values_for(argc, argv, "+CYCLES=");
    if (cycle_args.empty()) {
        std::cerr << (mode == RunMode::Snapshot ? "error: snapshot mode requires +CYCLES=N\n"
                                                 : "error: verification mode requires +CYCLES=N\n");
        return false;
    }
    if (cycle_args.size() != 1) { std::cerr << "error: duplicate cycle count\n"; return false; }
    if (!parse_u32(cycle_args[0], cycles) || cycles == 0) {
        std::cerr << "error: invalid cycle count: " << cycle_args[0] << "\n";
        return false;
    }
    return true;
}
}  // namespace

int main(int argc, char** argv) {
    RunMode mode;
    uint32_t cycles = 0;
    if (!parse_run_mode(argc, argv, mode, cycles)) return 1;
    const auto refs = values_for(argc, argv, "+REFFILE=");
    const auto sigs = values_for(argc, argv, "+SIGFILE=");
    const auto rvfis = values_for(argc, argv, "+RVFI_TRACE=");
    if (refs.size() > 1 || sigs.size() > 1 || rvfis.size() > 1) { std::cerr << "error: duplicate result consumer\n"; return 1; }
    const std::string reffile = refs.empty() ? "" : refs[0];
    const std::string sigfile = sigs.empty() ? "" : sigs[0];
    const std::string rvfifile = rvfis.empty() ? "" : rvfis[0];
    const bool verify = mode != RunMode::Snapshot;
    if (verify && reffile.empty() && sigfile.empty() && rvfifile.empty()) {
        std::cerr << "error: verification mode requires a result consumer\n";
        return 1;
    }
    Reference reference;
    if (!reffile.empty() && !load_reference(reffile, reference)) return 1;

    const bool reference_checks = reference.stalls.has_value()
        || std::any_of(reference.regs.begin(), reference.regs.end(),
                       [](const auto& expected) { return expected.has_value(); });

    const auto vcds = values_for(argc, argv, "+VCD=");
    const std::unique_ptr<VerilatedContext> ctx{new VerilatedContext};
    ctx->commandArgs(argc, argv);
    const std::unique_ptr<Vcpu> top{new Vcpu{ctx.get()}};

    uint32_t sigstart = 0, sigend = 0;
    if (!sigfile.empty()) {
        const auto starts = values_for(argc, argv, "+SIGSTART=");
        const auto ends = values_for(argc, argv, "+SIGEND=");
        if (starts.size() != 1 || ends.size() != 1) {
            std::cerr << "error: signature output requires exactly one SIGSTART and SIGEND\n";
            return 1;
        }
        if (!parse_u32(starts[0], sigstart)) {
            std::cerr << "error: invalid signature start: " << starts[0] << "\n";
            return 1;
        }
        if (!parse_u32(ends[0], sigend)) {
            std::cerr << "error: invalid signature end: " << ends[0] << "\n";
            return 1;
        }
        if (sigstart >= sigend) {
            std::cerr << "error: signature range must satisfy start < end\n";
            return 1;
        }
        const size_t dmem_words = top->rootp->cpu__DOT__u_backend__DOT__u_data_mem__DOT__mem_array.size();
        if (sigend > dmem_words) {
            std::cerr << "error: signature end exceeds data memory word count: "
                      << sigend << " > " << dmem_words << "\n";
            return 1;
        }
    }
    if (verify && !reference_checks && sigfile.empty() && rvfifile.empty()) {
        std::cerr << "error: reference file has no register or stalls expectations\n";
        return 1;
    }

    const std::string vcdfile = vcds.empty() ? "cpu.vcd" : vcds.back();
    VerilatedVcdC* tfp = nullptr;
    if (!vcdfile.empty()) { ctx->traceEverOn(true); tfp = new VerilatedVcdC; top->trace(tfp, 99); tfp->open(vcdfile.c_str()); }
    auto tick = [&]() {
        top->clk = 0; top->eval(); ctx->timeInc(1); if (tfp) tfp->dump(ctx->time());
        top->clk = 1; top->eval(); ctx->timeInc(1); if (tfp) tfp->dump(ctx->time());
    };
    top->dbg_flush = 0;
    top->rst = 1; tick(); top->rst = 0;

    std::vector<std::array<uint32_t, 4>> rvfi_log;
    bool terminal = false;
    uint32_t tohost_code = 0;
    uint64_t ran = 0;
    // Existing references supply the workload cycle budget, while verification
    // still needs bounded headroom for pipeline/cache progress to the explicit
    // terminal event.  Snapshot mode instead runs exactly its requested count.
    const uint64_t run_limit = mode == RunMode::Snapshot ? cycles : uint64_t{cycles} * 50 + 1000;
    for (; ran < run_limit; ++ran) {
        tick();
        if (top->rootp->cpu__DOT__u_backend__DOT__rvfi_valid) {
            if (!rvfifile.empty()) rvfi_log.push_back({
                static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__rvfi_pc),
                static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__rvfi_insn),
                static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__rvfi_rd_addr),
                static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__rvfi_rd_wdata)});
            if (mode == RunMode::SelfLoop && static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__rvfi_insn) == 0x0000006f) {
                terminal = true; ++ran; break;
            }
        }
        if (mode == RunMode::Tohost && top->rootp->cpu__DOT__u_backend__DOT__tohost_valid) {
            terminal = true;
            tohost_code = static_cast<uint32_t>(top->rootp->cpu__DOT__u_backend__DOT__tohost_data);
            ++ran;
            break;
        }
    }
    bool failed = false;
    auto fail = [&](const std::string& message) { std::cerr << "error: " << message << "\n"; failed = true; };
    if (verify && !terminal) fail(mode == RunMode::Tohost ? "timeout waiting for tohost completion" : "timeout waiting for retired self-loop sentinel");
    if (mode == RunMode::Tohost && terminal && tohost_code != 1) fail("tohost completion value is not 1");

    struct { uint32_t cyc, instret, stalls, flushes, mispred, branches, memstall, icacc, icmiss, dcacc, dcmiss; } pc_snap = {
        top->perf_cycle_count, top->perf_instr_retired, top->perf_stall_count, top->perf_flush_count,
        top->perf_mispredict_count, top->perf_branch_count, top->perf_mem_stall_count,
        top->perf_icache_access, top->perf_icache_miss, top->perf_dcache_access, top->perf_dcache_miss};
    if (has_arg(argc, argv, "+TEST_FORCE_DCACHE_COUNTER_MISMATCH=1")) {
        pc_snap.dcacc = 1;
        pc_snap.dcmiss = 2;
    }
    if (verify && pc_snap.icmiss > pc_snap.icacc) fail("I-cache misses exceed accesses");
    if (verify && pc_snap.dcmiss > pc_snap.dcacc) fail("D-cache misses exceed accesses");
    top->dbg_flush = 1;
    bool drained = !has_arg(argc, argv, "+TEST_FORCE_CACHE_DRAIN_TIMEOUT=1");
    if (drained) {
        drained = false;
        for (int i = 0; i < 2000000 && !top->dbg_flush_done; ++i) tick();
        drained = top->dbg_flush_done;
    }
    if (!drained && verify) fail("cache drain deadline exhausted");
    top->dbg_flush = 0;
    if (tfp) { tfp->close(); delete tfp; }

    if (!rvfifile.empty()) {
        std::ofstream trace(rvfifile);
        if (!trace) fail("cannot open RVFI output: " + rvfifile);
        else {
            for (const auto& record : rvfi_log) trace << std::hex << std::setfill('0') << std::setw(8) << record[0]
                << " " << std::setw(8) << record[1] << " " << std::dec << record[2]
                << " " << std::hex << std::setw(8) << record[3] << "\n";
            trace.flush();
            if (!trace) fail("failed writing RVFI output: " + rvfifile);
            else std::cout << "RVFI trace: " << rvfi_log.size() << " retirements -> " << rvfifile << "\n";
        }
    }
    if (!sigfile.empty()) {
        std::ofstream signature(sigfile);
        if (!signature) fail("cannot open signature output: " + sigfile);
        else {
            for (uint32_t i = sigstart; i < sigend; ++i) signature << std::hex << std::setw(8) << std::setfill('0')
                << top->rootp->cpu__DOT__u_backend__DOT__u_data_mem__DOT__mem_array[i] << "\n";
            signature.flush();
            if (!signature) fail("failed writing signature output: " + sigfile);
            else std::cout << "Signature dumped: " << (sigend - sigstart) << " words -> " << sigfile << "\n";
        }
    }

    uint32_t regs[32] = {};
    for (int i = 1; i < 32; ++i) regs[i] = top->rootp->cpu__DOT__u_backend__DOT__u_reg_file__DOT__reg_array[i];
    if (mode == RunMode::Snapshot) std::cout << "SNAPSHOT DEBUG RUN (non-verifying) after " << ran << " cycles\n";
    else if (mode == RunMode::Tohost && terminal) std::cout << "Test signalled completion via tohost: code=0x" << std::hex << tohost_code << std::dec << "\n";
    else if (mode == RunMode::SelfLoop && terminal) std::cout << "Test completed via retired self-loop sentinel\n";
    std::cout << "Registers after " << ran << " cycles:\n";
    for (int i = 0; i < 32; ++i) if (regs[i]) std::cout << "  x" << i << " = " << regs[i] << "  (0x" << std::hex << regs[i] << std::dec << ")\n";
    if (!reffile.empty() && verify) {
        for (int reg = 0; reg < 32; ++reg) if (reference.regs[reg].has_value()) {
            const uint32_t expected = *reference.regs[reg];
            if (regs[reg] != expected) { fail("reference mismatch for x" + std::to_string(reg)); std::cout << "  FAIL  x" << reg << "\n"; }
            else std::cout << "  PASS  x" << reg << "\n";
        }
        if (reference.stalls.has_value() && pc_snap.stalls != *reference.stalls) { fail("reference mismatch for stalls"); std::cout << "  FAIL  stalls\n"; }
        else if (reference.stalls.has_value()) std::cout << "  PASS  stalls\n";
    }
    const double cpi = pc_snap.instret ? static_cast<double>(pc_snap.cyc) / pc_snap.instret : 0.0;
    const double accuracy = pc_snap.branches ? 100.0 * static_cast<double>(pc_snap.branches - pc_snap.mispred) / pc_snap.branches : 0.0;
    const double ichr = pc_snap.icacc && pc_snap.icmiss <= pc_snap.icacc
                      ? 100.0 * static_cast<double>(pc_snap.icacc - pc_snap.icmiss) / pc_snap.icacc : 0.0;
    const double dchr = pc_snap.dcacc && pc_snap.dcmiss <= pc_snap.dcacc
                      ? 100.0 * static_cast<double>(pc_snap.dcacc - pc_snap.dcmiss) / pc_snap.dcacc : 0.0;
    std::cout << "  perf: cycles=" << pc_snap.cyc << " instret=" << pc_snap.instret << " stalls=" << pc_snap.stalls
              << " flushes=" << pc_snap.flushes << " memstall=" << pc_snap.memstall << " CPI=" << cpi << "\n"
              << "  bpred: branches=" << pc_snap.branches << " mispredicts=" << pc_snap.mispred << " accuracy=" << accuracy << "%\n"
              << "  icache: accesses=" << pc_snap.icacc << " misses=" << pc_snap.icmiss << " hitrate=" << ichr << "%\n"
              << "  dcache: accesses=" << pc_snap.dcacc << " misses=" << pc_snap.dcmiss << " hitrate=" << dchr << "%\n";
#if VM_COVERAGE
    const auto coverages = values_for(argc, argv, "+COVERAGE=");
    if (!coverages.empty() && !coverages.back().empty()) VerilatedCov::write(coverages.back().c_str());
#endif
    if (mode == RunMode::Snapshot) return failed ? 1 : 0;
    std::cout << (failed ? "FAIL\n" : "PASS\n");
    return failed ? 1 : 0;
}
