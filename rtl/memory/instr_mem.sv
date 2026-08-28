// instr_mem.sv - instruction memory (Harvard). 524288 words (2MB), word-addressed.
//
// The array is combinational; what it costs to read is modelled by mem_timing.
// LATENCY=1 restores the original behaviour exactly (ready every cycle, no
// stall), which is what the directed tests and the compliance suite run under.
`default_nettype none

import rv32i_pkg::*;

module instr_mem #(
    parameter int LATENCY     = 1,
    parameter int DEPTH_WORDS = 524288   // 2MB
) (
    input  var logic        clk,
    input  var logic        rst,
    input  var logic        req,     // an access is being presented this cycle
    input  var logic        burst,   // requester is walking sequential words
    input  var logic [XLEN-1:0] addr,
    output var logic [ILEN-1:0] instr,
    output var logic        ready
);
    localparam int WORDW = $clog2(DEPTH_WORDS);

    logic [ILEN-1:0] mem [0:DEPTH_WORDS-1];

`ifndef SYNTHESIS
    string mem_file;
    initial begin
        if (!$value$plusargs("MEMFILE=%s", mem_file)) begin
            $fatal(1, "instr_mem: no +MEMFILE=<hexfile> supplied");
        end
        $readmemh(mem_file, mem);
    end
`else
    // $value$plusargs/$fatal are simulation-only; synthesis just needs *a*
    // BRAM-inferring initial load, since resource/timing numbers don't
    // depend on content. A real design would load code via a bootloader or
    // a MIF/COE-driven init instead of $readmemh.
    initial $readmemh("blank_instr.hex", mem);
`endif

    // Only the low bits are decoded; see the matching comment in data_mem.sv
    // — this aliasing is relied on by the linker script, not a bug.
    assign instr = mem[addr[WORDW+1:2]];

    mem_timing #(.LATENCY(LATENCY)) u_timing (
        .clk(clk), .rst(rst),
        .req(req), .burst(burst), .addr(addr), .ready(ready)
    );
endmodule

`default_nettype wire
