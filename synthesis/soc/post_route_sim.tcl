if {[llength $argv] != 3} {
    error "expected output_dir, imem_file, and dmem_file"
}

set output_dir [file normalize [lindex $argv 0]]
set imem_file [file normalize [lindex $argv 1]]
set dmem_file [file normalize [lindex $argv 2]]
set part xc7a35ticsg324-1L
file mkdir $output_dir

create_project -force post_route_sim "$output_dir/project" -part $part
set design_sources [concat [list rtl/rv32i_pkg.sv] [glob rtl/core/*.sv] \
    [glob rtl/memory/*.sv] [glob rtl/bus/*.sv] [glob rtl/soc/*.sv] \
    [glob rtl/boards/*.sv]]
add_files $design_sources
set_property file_type SystemVerilog [get_files $design_sources]
add_files -fileset constrs_1 boards/arty_a7_35t.xdc
add_files -fileset sim_1 sim/arty_post_route_tb.sv
set_property top arty_a7_35t_top [get_filesets sources_1]
set_property top arty_post_route_tb [get_filesets sim_1]
set_property generic [list IMEM_INIT_FILE=$imem_file DMEM_INIT_FILE=$dmem_file] \
    [get_filesets sources_1]
set_property verilog_define SYNTHESIS [get_filesets sources_1]
set_property target_simulator XSim [current_project]
set_property xsim.simulate.runtime all [get_filesets sim_1]
update_compile_order -fileset sources_1
update_compile_order -fileset sim_1

launch_runs synth_1 -jobs 8
wait_on_run synth_1
launch_runs impl_1 -to_step route_design -jobs 8
wait_on_run impl_1
open_run impl_1

report_timing_summary -delay_type min_max -report_unconstrained \
    -file "$output_dir/timing_summary.rpt"
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
puts $timing_checks
if {![regexp -nocase {checking no_clock \(([0-9]+)\)} \
        $timing_checks unused no_clock_count]
    || ![regexp -nocase {checking unconstrained_internal_endpoints \(([0-9]+)\)} \
        $timing_checks unused unconstrained_count]} {
    error "timing constraint checks are missing"
}
if {$no_clock_count != 0 || $unconstrained_count != 0} {
    error "unconstrained timing endpoint found"
}

set sdf_file "$output_dir/arty_a7_35t_top.sdf"
set netlist_file "$output_dir/arty_a7_35t_top_timesim.v"
set input_clocks [get_clocks clk100]
set input_period [get_property PERIOD $input_clocks]
set soc_clocks {}
foreach candidate [get_clocks -quiet] {
    set candidate_period [get_property PERIOD $candidate]
    if {abs($candidate_period - 20.0) <= 0.0001} {
        lappend soc_clocks $candidate
    }
}
if {[llength $input_clocks] != 1 || abs($input_period - 10.0) > 0.0001} {
    error "input clock constraint is invalid"
}
if {[llength $soc_clocks] != 1} {
    error "generated SoC clock constraint is invalid"
}
set meta [open "$output_dir/post_route_sim_meta.txt" w]
puts $meta "part=$part"
puts $meta "input_clock_period_ns=$input_period"
puts $meta "soc_clock_period_ns=[get_property PERIOD $soc_clocks]"
puts $meta "wns_ns=$wns"
puts $meta "top=arty_a7_35t_top"
puts $meta "testbench=arty_post_route_tb"
puts $meta "mode=post-implementation"
puts $meta "type=timing"
close $meta
write_sdf -force $sdf_file
write_verilog -force -mode timesim -sdf_anno true -sdf_file $sdf_file \
    $netlist_file
launch_simulation -mode post-implementation -type timing
puts "===SOC_POST_ROUTE_SIM_DONE==="
