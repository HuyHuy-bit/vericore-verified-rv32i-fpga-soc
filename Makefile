# ---- RV32I 5-stage pipelined CPU: Verilator build + multi-test suite ----
TOP      = cpu
TB       = cpu_tb.cpp

CPU_SRCS = rtl/rv32i_pkg.sv \
           rtl/cpu.sv rtl/frontend.sv rtl/backend.sv rtl/pc.sv rtl/instr_mem.sv rtl/reg_file.sv rtl/imm_gen.sv \
           rtl/alu.sv rtl/control.sv rtl/data_mem.sv rtl/branch_unit.sv \
           rtl/if_id_reg.sv rtl/id_ex_reg.sv rtl/ex_mem_reg.sv rtl/mem_wb_reg.sv \
           rtl/forwarding_unit.sv rtl/hazard_detect.sv rtl/branch_predictor.sv rtl/ras.sv rtl/csr.sv \
           rtl/mem_timing.sv rtl/icache.sv rtl/lsu.sv rtl/dcache.sv rtl/perf_counters.sv

# Cache/latency configuration. Defaults match the plain no-cache build so
# `make all` with no arguments behaves exactly as before.
IC_BYTES ?= 0
IC_BLOCK ?= 4
IC_WAYS  ?= 1
DC_BYTES ?= 0
DC_BLOCK ?= 4
DC_WAYS  ?= 1
DC_WB    ?= 0
IMEM_LAT ?= 1
DMEM_LAT ?= 1

GPARAMS  = -GIMEM_LATENCY=$(IMEM_LAT) -GDMEM_LATENCY=$(DMEM_LAT) \
           -GICACHE_BYTES=$(IC_BYTES) -GICACHE_BLOCK_WORDS=$(IC_BLOCK) -GICACHE_WAYS=$(IC_WAYS) \
           -GDCACHE_BYTES=$(DC_BYTES) -GDCACHE_BLOCK_WORDS=$(DC_BLOCK) -GDCACHE_WAYS=$(DC_WAYS) \
           -GDCACHE_WRITE_BACK=$(DC_WB)

VFLAGS   = --cc --exe --build --trace --assert --timing -j 0
# The all-defaults config keeps the plain "obj_dir" name other scripts (e.g.
# bench/run_bench.sh) already expect; any non-default config gets its own dir
# so configs don't clobber each other's cached build.
ifeq ($(IC_BYTES)$(IC_BLOCK)$(IC_WAYS)$(DC_BYTES)$(DC_BLOCK)$(DC_WAYS)$(DC_WB)$(IMEM_LAT)$(DMEM_LAT),041041011)
OBJDIR   = obj_dir
else
OBJDIR   = obj_dir_ic$(IC_BYTES)_$(IC_BLOCK)_$(IC_WAYS)_dc$(DC_BYTES)_$(DC_BLOCK)_$(DC_WAYS)_$(DC_WB)_L$(IMEM_LAT)_$(DMEM_LAT)
endif
SIM      = $(OBJDIR)/V$(TOP)
ASM      = python3 tools/asm.py

TESTS    = t01_rtype t02_itype t03_memory t04_branch t05_jump t06_lui_auipc t07_load_use t08_loop t09_trap_illegal t10_misaligned t11_mret t12_misaligned_fetch t13_csr_ext t14_csr_illegal t15_csr_unimpl t16_irq_timer t17_irq_mret t18_trap_causes t19_dcache_evict t20_ras_multi_caller t21_gshare_correlated t22_fencei t23_decode_illegal t24_misaligned_control_flow t25_operand_use_hazards
ifneq ($(origin TESTS),command line)
ifneq ($(words $(TESTS)),25)
$(error directed TESTS must contain exactly 25 programs)
endif
endif
HEXFILES = $(patsubst %,tests/%.hex,$(TESTS))

.PHONY: all sim assemble test unit harness-test evidence-check check memtiming bench lint wave clean coverage soak soak-lockstep lockstep lockstep-sim compliance synth-matrix synth-summary

# Default: build, assemble, run the full suite.
all: sim assemble test

# Build the simulator binary.
sim: $(SIM)
$(SIM): $(CPU_SRCS) $(TB)
	verilator $(VFLAGS) $(GPARAMS) --Mdir $(OBJDIR) --top-module $(TOP) $(CPU_SRCS) $(TB)

# Assemble every test program that is out of date.
assemble: $(HEXFILES)
tests/%.hex: tests/%.s tools/asm.py
	$(ASM) $< $@

# Unit-check the memory access-cost model. Every CPI number the project
# reports is scaled by this, and an off-by-one here would bias results
# silently rather than failing anything.
memtiming:
	@verilator --cc --exe --build -j 0 --top-module mem_timing -GLATENCY=10 \
	    --Mdir obj_dir_memtiming rtl/rv32i_pkg.sv rtl/mem_timing.sv tb/mem_timing_tb.cpp > /dev/null
	@./obj_dir_memtiming/Vmem_timing

# Dependency-free SystemVerilog unit checks, each isolated in an ignored
# obj_dir_unit_* build directory by tools/run_unit.sh.
unit:
	@tools/run_unit.sh control_tb rtl/rv32i_pkg.sv rtl/control.sv unit/control_tb.sv
	@tools/run_unit.sh hazard_detect_tb rtl/hazard_detect.sv unit/hazard_detect_tb.sv
	@tools/run_unit.sh dcache_counter_tb rtl/rv32i_pkg.sv rtl/dcache.sv unit/dcache_counter_tb.sv

# Run every test and print a summary.
test: sim assemble memtiming
	@echo "========== RV32I test suite =========="
	@PASS=0; FAIL=0; \
	for t in $(TESTS); do \
	    printf "\n--- $$t ---\n"; \
	    CYCS=$$(grep '^cycles=' tests/$$t.ref 2>/dev/null | cut -d= -f2); \
	    CYCS=$${CYCS:-25}; \
	    if ./$(SIM) +MEMFILE=tests/$$t.hex +REFFILE=tests/$$t.ref \
	               +STOP=tohost +CYCLES=$$CYCS +VCD=tests/$$t.vcd; then \
	        PASS=$$((PASS+1)); \
	    else \
	        FAIL=$$((FAIL+1)); \
	    fi; \
	done; \
	echo ""; \
	echo "========== $$PASS/$$((PASS+FAIL)) tests passed =========="; \
	[ $$FAIL -eq 0 ]

# Dependency-free black-box checks for simulator argument, completion, and
# result-consumer contracts.  The target builds the simulator first because
# the fixtures invoke the real binary.
harness-test: sim
	python3 tools/test_harness.py
	@$(MAKE) --no-print-directory sim IC_BYTES=0 DC_BYTES=4096 DC_WAYS=4 DC_WB=0 IMEM_LAT=1 DMEM_LAT=10
	SIM="$(CURDIR)/obj_dir_ic0_4_1_dc4096_4_4_0_L1_10/Vcpu" \
		python3 -m unittest -v tools.test_harness.HarnessTest.test_tohost_bypasses_dcache

evidence-check:
	python3 -m unittest -v tools.test_evidence_check
	python3 tools/evidence_check.py

check: unit harness-test lint evidence-check

# Run the C benchmark kernels and print the CPI table.
bench: sim
	@./bench/run_bench.sh

# Lint only — quick syntax/structure check, -Wall with a documented waiver file.
lint:
	verilator --lint-only -Wall --top-module $(TOP) rtl/verilator.vlt $(CPU_SRCS)

# Open a specific test waveform: make wave TEST=t04_branch
TEST ?= t01_rtype
wave: sim assemble
	./$(SIM) +MEMFILE=tests/$(TEST).hex +REFFILE=tests/$(TEST).ref \
	         +STOP=tohost +CYCLES=$$(grep '^cycles=' tests/$(TEST).ref | cut -d= -f2) \
	         +VCD=tests/$(TEST).vcd
	gtkwave tests/$(TEST).vcd &

# Functional coverage: build with --coverage against a cache-enabled config
# (so the D-cache FSM points are reachable), run the directed suite, merge
# and annotate. Report: docs/coverage.md.
COVDIR = obj_dir_cov
coverage: assemble
	verilator --cc --exe --build --trace --assert --timing --coverage \
	    -GIMEM_LATENCY=10 -GDMEM_LATENCY=10 \
	    -GICACHE_BYTES=1024 -GICACHE_BLOCK_WORDS=4 -GICACHE_WAYS=4 \
	    -GDCACHE_BYTES=4096 -GDCACHE_BLOCK_WORDS=4 -GDCACHE_WAYS=4 -GDCACHE_WRITE_BACK=1 \
	    --Mdir $(COVDIR) --top-module $(TOP) $(CPU_SRCS) $(TB)
	@rm -rf coverage && mkdir -p coverage
	@FAIL=0; \
	for t in $(TESTS); do \
	    CYCS=$$(grep '^cycles=' tests/$$t.ref 2>/dev/null | cut -d= -f2); CYCS=$${CYCS:-25}; \
	    COVFILE=coverage/$$t.dat; rm -f "$$COVFILE"; \
	    if ! ./$(COVDIR)/V$(TOP) +MEMFILE=tests/$$t.hex +REFFILE=tests/$$t.ref \
	        +STOP=tohost +CYCLES=$$CYCS +VCD= +COVERAGE="$$COVFILE" > /dev/null; then \
	        echo "coverage simulation failed: $$t" >&2; FAIL=1; \
	    elif [ ! -s "$$COVFILE" ]; then \
	        echo "coverage artifact missing or empty: $$t" >&2; FAIL=1; \
	    fi; \
	done; \
	[ $$FAIL -eq 0 ]
	verilator_coverage --write coverage/merged.dat coverage/*.dat
	verilator_coverage --annotate coverage/annotated coverage/merged.dat
	python3 tools/coverage_report.py coverage/merged.dat > docs/coverage.md
	@echo "wrote docs/coverage.md"

# Spike co-simulation. Built separately because it needs RESET_PC=0x80000000
# to match the memory map Spike forces programs to link at — see
# compliance/link/spike-lockstep.ld.
LOCKSTEP_DIR = obj_dir_lockstep
LOCKSTEP_TIMEOUT ?= 300
lockstep-sim:
	verilator $(VFLAGS) -GRESET_PC=0x80000000 --Mdir $(LOCKSTEP_DIR) \
	    --top-module $(TOP) $(CPU_SRCS) $(TB)

lockstep: lockstep-sim
	LOCKSTEP_TIMEOUT=$(LOCKSTEP_TIMEOUT) ./tools/run_lockstep.sh

# Constrained-random regression: SEEDS random programs against the Python
# golden model (tools/rv32i_model.py). make soak SEEDS=1000
SEEDS ?= 100
soak: sim
	SIM="$(CURDIR)/$(SIM)" ./tools/soak.sh $(SEEDS)

# Pinned RV32I architecture-test signature suite.
compliance: sim
	./compliance/run_compliance.sh

# Random programs compared against Spike instead of the Python model, which
# is what lets them contain branches and jumps (see tools/soak_lockstep.sh).
soak-lockstep: lockstep-sim
	LOCKSTEP_TIMEOUT=$(LOCKSTEP_TIMEOUT) ./tools/soak_lockstep.sh $(SEEDS)

REPORT_DIR ?= syn/reports
RTL_COMMIT ?= 87378e281435056fd1bd3dfb57f9c212dca82bb7
synth-matrix:
	VIVADO="$(VIVADO)" python3 syn/run_synth.py --report-dir "$(REPORT_DIR)" --rtl-commit "$(RTL_COMMIT)"

synth-summary:
	python3 syn/summarize_reports.py --report-dir "$(REPORT_DIR)"

clean:
	rm -rf obj_dir obj_dir_L* obj_dir_ic* obj_dir_memtiming obj_dir_cov obj_dir_lockstep coverage tests/*.hex tests/*.vcd cpu.vcd
