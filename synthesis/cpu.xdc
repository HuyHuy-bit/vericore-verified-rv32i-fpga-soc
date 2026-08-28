# cpu.xdc - timing constraints for out-of-context synthesis/implementation.
# No physical pin assignments: this is a resource/timing study, not a board
# bring-up. Clock period is set deliberately aggressive (500MHz) so the
# reported worst negative slack, not the constraint itself, is the fmax data
# point: fmax = 1 / (period - WNS).
create_clock -period 2.000 -name clk [get_ports clk]

# Debug/perf ports are not on any cycle-critical path; excluding them keeps
# the timing report focused on the pipeline itself.
set_false_path -from [get_ports rst]
set_false_path -from [get_ports dbg_flush]
set_false_path -to   [get_ports dbg_flush_done]
set_false_path -to   [get_ports {perf_*}]
