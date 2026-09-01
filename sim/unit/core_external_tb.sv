`default_nettype none

import rv32i_pkg::*;

module core_external;
    logic clk = 1'b0;
    logic rst;
    logic irq_external;
    logic imem_req;
    logic imem_burst;
    logic [XLEN-1:0] imem_addr;
    logic [ILEN-1:0] imem_rdata;
    logic imem_ready;
    logic dmem_req;
    logic dmem_burst;
    logic [XLEN-1:0] dmem_addr;
    logic [XBYTES-1:0] dmem_wstrb;
    logic [XLEN-1:0] dmem_wdata;
    logic [XLEN-1:0] dmem_rdata;
    logic dmem_ready;
    logic [XLEN-1:0] perf_cycle_count;
    logic [XLEN-1:0] perf_instr_retired;
    logic [XLEN-1:0] perf_stall_count;
    logic [XLEN-1:0] perf_flush_count;
    logic [XLEN-1:0] perf_mispredict_count;
    logic [XLEN-1:0] perf_branch_count;
    logic [XLEN-1:0] perf_mem_stall_count;
    logic [XLEN-1:0] perf_icache_access;
    logic [XLEN-1:0] perf_icache_miss;
    logic [XLEN-1:0] perf_dcache_access;
    logic [XLEN-1:0] perf_dcache_miss;
    logic dbg_flush;
    logic dbg_flush_done;
    logic retired_debug;
    logic saw_retirement;

    always #1 clk = ~clk;
    always @(posedge clk) if (!rst && retired_debug) saw_retirement <= 1'b1;

    rv32i_core dut (
        .clk(clk),
        .rst(rst),
        .irq_external(irq_external),
        .imem_req(imem_req),
        .imem_burst(imem_burst),
        .imem_addr(imem_addr),
        .imem_rdata(imem_rdata),
        .imem_ready(imem_ready),
        .dmem_req(dmem_req),
        .dmem_burst(dmem_burst),
        .dmem_addr(dmem_addr),
        .dmem_wstrb(dmem_wstrb),
        .dmem_wdata(dmem_wdata),
        .dmem_rdata(dmem_rdata),
        .dmem_ready(dmem_ready),
        .perf_cycle_count(perf_cycle_count),
        .perf_instr_retired(perf_instr_retired),
        .perf_stall_count(perf_stall_count),
        .perf_flush_count(perf_flush_count),
        .perf_mispredict_count(perf_mispredict_count),
        .perf_branch_count(perf_branch_count),
        .perf_mem_stall_count(perf_mem_stall_count),
        .perf_icache_access(perf_icache_access),
        .perf_icache_miss(perf_icache_miss),
        .perf_dcache_access(perf_dcache_access),
        .perf_dcache_miss(perf_dcache_miss),
        .dbg_flush(dbg_flush),
        .dbg_flush_done(dbg_flush_done),
        .retired_debug(retired_debug)
    );

    initial begin
        rst = 1'b1;
        irq_external = 1'b0;
        imem_rdata = 32'h0000006f;
        imem_ready = 1'b1;
        dmem_rdata = '0;
        dmem_ready = 1'b1;
        dbg_flush = 1'b0;
        saw_retirement = 1'b0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        repeat (16) begin
            @(posedge clk);
            if (!imem_req) $fatal(1, "instruction request dropped");
            if (imem_addr[1:0] != 2'b00) $fatal(1, "unaligned instruction address");
            if (dmem_req) $fatal(1, "unexpected data request");
            if ($isunknown({imem_req, imem_burst, imem_addr, dmem_req,
                            dmem_burst, dmem_addr, dmem_wstrb, dmem_wdata}))
                $fatal(1, "unknown external-memory signal");
        end

        if (!saw_retirement) $fatal(1, "no instruction retired");
        $display("PASS external-memory core boundary");
        $finish;
    end

    initial begin
        repeat (100) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
