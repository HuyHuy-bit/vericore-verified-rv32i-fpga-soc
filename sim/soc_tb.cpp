#include "Vrv32i_soc.h"
#include "verilated.h"

#include <array>
#include <cstdint>
#include <iostream>
#include <memory>
#include <optional>
#include <string>

namespace {
constexpr uint64_t CycleDeadline = 100000;
constexpr int ClockHz = 80;
constexpr int UartBaud = 10;
constexpr int UartDivisor = ClockHz / UartBaud;

enum class DemoState {
    WaitBoot,
    BouncePress,
    StablePress1,
    WaitIrq1,
    StableRelease,
    StablePress2,
    WaitIrq2,
    Complete,
};

class UartDecoder {
public:
    std::optional<uint8_t> observe(bool level) {
        std::optional<uint8_t> result;
        if (phase_ == Phase::Idle) {
            if (previous_ && !level) {
                phase_ = Phase::Start;
                countdown_ = UartDivisor / 2;
            }
        } else if (--countdown_ == 0) {
            if (phase_ == Phase::Start) {
                if (level)
                    error_ = "UART start bit was high";
                phase_ = Phase::Data;
                countdown_ = UartDivisor;
            } else if (phase_ == Phase::Data) {
                if (level)
                    value_ |= static_cast<uint8_t>(1u << bit_);
                ++bit_;
                countdown_ = UartDivisor;
                if (bit_ == 8)
                    phase_ = Phase::Stop;
            } else {
                if (!level)
                    error_ = "UART stop bit was low";
                result = value_;
                phase_ = Phase::Idle;
                bit_ = 0;
                value_ = 0;
            }
        }
        previous_ = level;
        return result;
    }

    const std::string& error() const { return error_; }

private:
    enum class Phase { Idle, Start, Data, Stop };
    Phase phase_ = Phase::Idle;
    bool previous_ = true;
    int countdown_ = 0;
    int bit_ = 0;
    uint8_t value_ = 0;
    std::string error_;
};

const char* state_name(DemoState state) {
    switch (state) {
        case DemoState::WaitBoot: return "WaitBoot";
        case DemoState::BouncePress: return "BouncePress";
        case DemoState::StablePress1: return "StablePress1";
        case DemoState::WaitIrq1: return "WaitIrq1";
        case DemoState::StableRelease: return "StableRelease";
        case DemoState::StablePress2: return "StablePress2";
        case DemoState::WaitIrq2: return "WaitIrq2";
        case DemoState::Complete: return "Complete";
    }
    return "Unknown";
}
}

int main(int argc, char** argv) {
    const std::unique_ptr<VerilatedContext> context{new VerilatedContext};
    context->commandArgs(argc, argv);
    const std::unique_ptr<Vrv32i_soc> dut{new Vrv32i_soc{context.get()}};

    auto tick = [&]() {
        dut->clk = 0;
        dut->eval();
        context->timeInc(1);
        dut->clk = 1;
        dut->eval();
        context->timeInc(1);
        dut->clk = 0;
        dut->eval();
    };

    dut->clk = 0;
    dut->rst = 1;
    dut->button_irq = 0;
    dut->eval();
    for (int cycle = 0; cycle < 8; ++cycle)
        tick();
    dut->rst = 0;

    const std::array<std::string, 3> expected{
        "rv32i soc ready\n", "external irq\n", "external irq\n"
    };
    UartDecoder decoder;
    DemoState state = DemoState::WaitBoot;
    std::string line;
    size_t line_count = 0;
    uint32_t state_cycles = 0;
    uint32_t resume_mark = 0;
    bool saw_irq_line = false;
    bool track_led = false;
    uint8_t last_led = 0;
    uint32_t led_transitions = 0;

    auto fail = [&](uint64_t cycle, const std::string& message) {
        std::cerr << "SoC integration failure at cycle " << cycle
                  << " in " << state_name(state) << ": " << message << "\n";
        return 1;
    };

    for (uint64_t cycle = 0; cycle < CycleDeadline; ++cycle) {
        switch (state) {
            case DemoState::WaitBoot:
            case DemoState::WaitIrq1:
            case DemoState::WaitIrq2:
                break;
            case DemoState::BouncePress:
                dut->button_irq = state_cycles < 12 && state_cycles % 4 < 2;
                break;
            case DemoState::StablePress1:
            case DemoState::StablePress2:
                dut->button_irq = 1;
                break;
            case DemoState::StableRelease:
                dut->button_irq = 0;
                break;
            case DemoState::Complete:
                break;
        }

        tick();
        if (context->gotFinish())
            return fail(cycle, "RTL stopped before completion");
        if (dut->bus_fault)
            return fail(cycle, "Wishbone bus fault");

        const auto byte = decoder.observe(dut->uart_tx != 0);
        if (!decoder.error().empty())
            return fail(cycle, decoder.error());
        if (byte.has_value()) {
            line.push_back(static_cast<char>(*byte));
            if (line.size() > 64)
                return fail(cycle, "UART line exceeded 64 bytes");
            if (*byte == '\n') {
                if (line_count >= expected.size())
                    return fail(cycle, "duplicate UART line");
                if (line != expected[line_count])
                    return fail(cycle, "wrong UART line: " + line);
                std::cout << line;
                ++line_count;
                line.clear();
            }
        }

        if (track_led && dut->led != last_led) {
            ++led_transitions;
            last_led = dut->led;
            const uint8_t expected_led = led_transitions == 1 ? 2 : 4;
            if (led_transitions > 2 || last_led != expected_led)
                return fail(cycle, "unexpected LED transition "
                    + std::to_string(last_led) + " at transition "
                    + std::to_string(led_transitions));
        }

        switch (state) {
            case DemoState::WaitBoot:
                if (line_count == 1) {
                    if (dut->led != 1)
                        return fail(cycle, "boot LED value was not one");
                    track_led = true;
                    last_led = dut->led;
                    state = DemoState::BouncePress;
                    state_cycles = 0;
                }
                break;
            case DemoState::BouncePress:
                if (line_count != 1 || led_transitions != 0)
                    return fail(cycle, "button bounce created an event");
                if (++state_cycles == 20) {
                    state = DemoState::StablePress1;
                    state_cycles = 0;
                }
                break;
            case DemoState::StablePress1:
                if (++state_cycles == 8) {
                    state = DemoState::WaitIrq1;
                    state_cycles = 0;
                    saw_irq_line = false;
                }
                break;
            case DemoState::WaitIrq1:
                if (!saw_irq_line && line_count == 2) {
                    if (led_transitions != 1 || dut->led != 2)
                        return fail(cycle, "first interrupt LED result was wrong");
                    saw_irq_line = true;
                    resume_mark = dut->progress_debug;
                }
                if (saw_irq_line && dut->progress_debug > resume_mark + 8) {
                    state = DemoState::StableRelease;
                    state_cycles = 0;
                }
                break;
            case DemoState::StableRelease:
                if (line_count != 2 || led_transitions != 1)
                    return fail(cycle, "release created an event");
                if (++state_cycles == 8) {
                    state = DemoState::StablePress2;
                    state_cycles = 0;
                }
                break;
            case DemoState::StablePress2:
                if (++state_cycles == 8) {
                    state = DemoState::WaitIrq2;
                    state_cycles = 0;
                    saw_irq_line = false;
                }
                break;
            case DemoState::WaitIrq2:
                if (!saw_irq_line && line_count == 3) {
                    if (led_transitions != 2 || dut->led != 4)
                        return fail(cycle, "second interrupt LED result was wrong");
                    saw_irq_line = true;
                    resume_mark = dut->progress_debug;
                }
                if (saw_irq_line && dut->progress_debug > resume_mark + 8)
                    state = DemoState::Complete;
                break;
            case DemoState::Complete:
                if (line_count != expected.size() || !line.empty()
                    || led_transitions != 2 || dut->led != 4)
                    return fail(cycle, "completion state was incomplete");
                std::cout << "PASS firmware SoC integration\n";
                return 0;
        }
    }

    return fail(CycleDeadline, "cycle deadline expired");
}
