if {[llength $argv] != 1} {
    error "expected one absolute bitstream path"
}

set bitstream [lindex $argv 0]
if {[file pathtype $bitstream] ne "absolute" || ![file isfile $bitstream]} {
    error "bitstream path must be absolute and exist"
}

open_hw_manager
try {
    connect_hw_server
    set targets [get_hw_targets]
    if {[llength $targets] != 1} {
        error "expected exactly one hardware target"
    }
    current_hw_target [lindex $targets 0]
    open_hw_target
    set devices [get_hw_devices]
    if {[llength $devices] != 1} {
        error "expected exactly one FPGA device"
    }
    set device [lindex $devices 0]
    if {[string tolower [get_property PART $device]] ne "xc7a35t"} {
        error "connected FPGA part is not xc7a35t"
    }
    set_property PROGRAM.FILE $bitstream $device
    program_hw_devices $device
    refresh_hw_device $device
    if {[get_property REGISTER.IR.BIT5_DONE $device] != 1} {
        error "FPGA configuration did not complete"
    }
    puts "===SOC_PROGRAM_DONE==="
} finally {
    close_hw_manager
}
