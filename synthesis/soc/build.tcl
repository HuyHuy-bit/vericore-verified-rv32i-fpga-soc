if {[llength $argv] != 3} {
    error "expected output_dir, imem_file, and dmem_file"
}

set output_dir [file normalize [lindex $argv 0]]
set imem_file [file normalize [lindex $argv 1]]
set dmem_file [file normalize [lindex $argv 2]]
set part xc7a35ticsg324-1L
file mkdir $output_dir

create_project -in_memory -part $part
read_verilog -sv rtl/rv32i_pkg.sv
read_verilog -sv [concat [glob rtl/core/*.sv] [glob rtl/memory/*.sv] \
    [glob rtl/bus/*.sv] [glob rtl/soc/*.sv] [glob rtl/boards/*.sv]]
read_xdc boards/arty_a7_35t.xdc
synth_design -top arty_a7_35t_top -part $part \
    -verilog_define SYNTHESIS \
    -generic IMEM_INIT_FILE=$imem_file -generic DMEM_INIT_FILE=$dmem_file
opt_design
place_design
route_design

report_utilization -file "$output_dir/utilization.rpt"
report_timing_summary -delay_type min_max -report_unconstrained \
    -file "$output_dir/timing_summary.rpt"
report_drc -file "$output_dir/drc.rpt"

set clocks [get_clocks clk100]
if {[llength $clocks] != 1} {
    error "expected exactly one clk100 clock"
}
set period [get_property PERIOD $clocks]
if {abs($period - 10.0) > 0.0001} {
    error "clk100 period is not 10 ns"
}
set setup_path [get_timing_paths -setup -max_paths 1]
if {[llength $setup_path] != 1} {
    error "no setup timing path was reported"
}
set wns [get_property SLACK $setup_path]
if {$wns < 0.0} {
    error "setup timing failed with WNS $wns"
}
set timing_checks [check_timing -return_string \
    -override_defaults {no_clock unconstrained_internal_endpoints}]
if {[regexp -nocase {There are [1-9][0-9]* [^\n]*no clock} $timing_checks]
    || [regexp -nocase {There are [1-9][0-9]* [^\n]*unconstrained} $timing_checks]} {
    error "unconstrained timing endpoint found"
}
set severe_drc [get_drc_violations -quiet \
    -filter {SEVERITY == "Error" || SEVERITY == "Critical Warning"}]
if {[llength $severe_drc] != 0} {
    error "DRC contains a critical warning or error"
}

write_bitstream -force "$output_dir/rv32i-soc-arty-a7-35t.bit"
set meta [open "$output_dir/build_meta.txt" w]
puts $meta "part=[get_property PART [current_project]]"
puts $meta "clock_period_ns=$period"
puts $meta "wns_ns=$wns"
puts $meta "top=arty_a7_35t_top"
close $meta
puts "===SOC_BUILD_DONE==="
