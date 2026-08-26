# Usage: vivado -mode batch -source build.tcl -tclargs <name> \
#            <ic_bytes> <ic_block> <ic_ways> <dc_bytes> <dc_block> <dc_ways> <dc_wb> \
#            <imem_depth> <dmem_depth>

if {[llength $argv] != 10} {
    error "expected 10 synthesis arguments"
}

set cfg_name    [lindex $argv 0]
set ic_bytes    [lindex $argv 1]
set ic_block    [lindex $argv 2]
set ic_ways     [lindex $argv 3]
set dc_bytes    [lindex $argv 4]
set dc_block    [lindex $argv 5]
set dc_ways     [lindex $argv 6]
set dc_wb       [lindex $argv 7]
set imem_depth  [lindex $argv 8]
set dmem_depth  [lindex $argv 9]

set part xc7a35ticsg324-1L
set outdir "out_$cfg_name"
file mkdir $outdir

create_project -in_memory -part $part

read_verilog -sv [glob rtl/*.sv]
read_xdc cpu.xdc

synth_design -mode out_of_context -top cpu -part $part \
    -verilog_define SYNTHESIS \
    -generic ICACHE_BYTES=$ic_bytes -generic ICACHE_BLOCK_WORDS=$ic_block -generic ICACHE_WAYS=$ic_ways \
    -generic DCACHE_BYTES=$dc_bytes -generic DCACHE_BLOCK_WORDS=$dc_block -generic DCACHE_WAYS=$dc_ways \
    -generic DCACHE_WRITE_BACK=$dc_wb \
    -generic IMEM_DEPTH_WORDS=$imem_depth -generic DMEM_DEPTH_WORDS=$dmem_depth

write_checkpoint -force "$outdir/post_synth.dcp"
report_utilization -file "$outdir/utilization_synth.rpt"

opt_design
place_design
route_design

write_checkpoint -force "$outdir/post_route.dcp"
report_utilization -file "$outdir/utilization.rpt"
report_timing_summary -delay_type min_max -report_unconstrained -file "$outdir/timing_summary.rpt"
report_timing -delay_type max -max_paths 5 -sort_by group -file "$outdir/critical_paths.rpt"

set applied_part [get_property PART [current_project]]
set clocks [get_clocks clk]
if {[llength $clocks] != 1} {
    error "expected one clk constraint"
}
set applied_period [get_property PERIOD $clocks]
set meta [open "$outdir/build_meta.txt" w]
puts $meta "config=$cfg_name"
puts $meta "part=$applied_part"
puts $meta "clock_period_ns=$applied_period"
close $meta

puts "===BUILD_DONE:$cfg_name==="
