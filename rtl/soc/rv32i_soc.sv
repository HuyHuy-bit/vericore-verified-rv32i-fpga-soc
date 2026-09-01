`default_nettype none

import rv32i_pkg::*;

module rv32i_soc #(
    parameter int CLOCK_HZ = 100_000_000,
    parameter int UART_BAUD = 115_200,
    parameter int DEBOUNCE_CYCLES = 1_000_000,
    parameter int ICACHE_BYTES = 1024,
    parameter int ICACHE_BLOCK_WORDS = 4,
    parameter int ICACHE_WAYS = 4,
    parameter int DCACHE_BYTES = 4096,
    parameter int DCACHE_BLOCK_WORDS = 4,
    parameter int DCACHE_WAYS = 4,
    parameter int DCACHE_WRITE_BACK = 1,
    parameter int IMEM_DEPTH_WORDS = 8192,
    parameter int DMEM_DEPTH_WORDS = 8192,
    parameter string IMEM_INIT_FILE = "",
    parameter string DMEM_INIT_FILE = ""
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic button_irq,
    output var logic [3:0] led,
    output var logic uart_tx,
    output var logic bus_fault,
    output var logic retired_debug,
    output var logic [31:0] progress_debug
);
    logic core_imem_req, core_imem_burst, core_imem_ready;
    logic [31:0] core_imem_addr, core_imem_rdata;
    logic core_dmem_req, core_dmem_burst, core_dmem_ready;
    logic [31:0] core_dmem_addr, core_dmem_wdata, core_dmem_rdata;
    logic [3:0] core_dmem_wstrb;
    logic [31:0] perf_cycle_count, perf_instr_retired;
    logic [31:0] perf_stall_count, perf_flush_count;
    logic [31:0] perf_mispredict_count, perf_branch_count;
    logic [31:0] perf_mem_stall_count, perf_icache_access;
    logic [31:0] perf_icache_miss, perf_dcache_access, perf_dcache_miss;
    logic dbg_flush_done;

    logic i_fault_pulse;
    logic i_wb_cyc, i_wb_stb, i_wb_we, i_wb_ack, i_wb_err;
    logic [31:0] i_wb_adr, i_wb_dat_w, i_wb_dat_r;
    logic [3:0] i_wb_sel;
    logic d_fault_pulse;
    logic d_wb_cyc, d_wb_stb, d_wb_we, d_wb_ack, d_wb_err;
    logic [31:0] d_wb_adr, d_wb_dat_w, d_wb_dat_r;
    logic [3:0] d_wb_sel;

    logic s_wb_cyc, s_wb_stb, s_wb_we, s_wb_ack, s_wb_err, s_wb_instr;
    logic [31:0] s_wb_adr, s_wb_dat_w, s_wb_dat_r;
    logic [3:0] s_wb_sel;

    logic imem_cyc, imem_stb, imem_we, imem_ack, imem_err;
    logic [31:0] imem_adr, imem_dat_w, imem_dat_r;
    logic [3:0] imem_sel;
    logic uart_cyc, uart_stb, uart_we, uart_ack, uart_err;
    logic [31:0] uart_adr, uart_dat_w, uart_dat_r;
    logic [3:0] uart_sel;
    logic gpio_cyc, gpio_stb, gpio_we, gpio_ack, gpio_err;
    logic [31:0] gpio_adr, gpio_dat_w, gpio_dat_r;
    logic [3:0] gpio_sel;
    logic dmem_cyc, dmem_stb, dmem_we, dmem_ack, dmem_err;
    logic [31:0] dmem_adr, dmem_dat_w, dmem_dat_r;
    logic [3:0] dmem_sel;

    logic button_state, button_rise;
    logic [3:0] gpio_led;
    logic irq_external;
    logic uart_ready;
    logic unused;

    assign led = bus_fault ? 4'hf : gpio_led;
    assign progress_debug = perf_instr_retired;
    assign unused = &{1'b0, core_imem_burst, core_dmem_burst,
        perf_cycle_count, perf_stall_count, perf_flush_count,
        perf_mispredict_count, perf_branch_count, perf_mem_stall_count,
        perf_icache_access, perf_icache_miss, perf_dcache_access,
        perf_dcache_miss, dbg_flush_done, uart_ready};

    always_ff @(posedge clk) begin
        if (rst)
            bus_fault <= 1'b0;
        else if (i_fault_pulse || d_fault_pulse)
            bus_fault <= 1'b1;
    end

    rv32i_core #(
        .ICACHE_BYTES(ICACHE_BYTES),
        .ICACHE_BLOCK_WORDS(ICACHE_BLOCK_WORDS),
        .ICACHE_WAYS(ICACHE_WAYS),
        .DCACHE_BYTES(DCACHE_BYTES),
        .DCACHE_BLOCK_WORDS(DCACHE_BLOCK_WORDS),
        .DCACHE_WAYS(DCACHE_WAYS),
        .DCACHE_WRITE_BACK(DCACHE_WRITE_BACK),
        .DCACHEABLE_BASE(32'h2000_0000),
        .DCACHEABLE_MASK(32'hffff_8000)
    ) u_core (
        .clk(clk),
        .rst(rst),
        .irq_external(irq_external),
        .imem_req(core_imem_req),
        .imem_burst(core_imem_burst),
        .imem_addr(core_imem_addr),
        .imem_rdata(core_imem_rdata),
        .imem_ready(core_imem_ready),
        .dmem_req(core_dmem_req),
        .dmem_burst(core_dmem_burst),
        .dmem_addr(core_dmem_addr),
        .dmem_wstrb(core_dmem_wstrb),
        .dmem_wdata(core_dmem_wdata),
        .dmem_rdata(core_dmem_rdata),
        .dmem_ready(core_dmem_ready),
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
        .dbg_flush(1'b0),
        .dbg_flush_done(dbg_flush_done),
        .retired_debug(retired_debug)
    );

    wb_master_adapter i_adapter (
        .clk(clk),
        .rst(rst),
        .src_req(core_imem_req),
        .src_addr(core_imem_addr),
        .src_wstrb(4'b0000),
        .src_wdata(32'b0),
        .src_rdata(core_imem_rdata),
        .src_ready(core_imem_ready),
        .fault_pulse(i_fault_pulse),
        .wb_cyc(i_wb_cyc),
        .wb_stb(i_wb_stb),
        .wb_we(i_wb_we),
        .wb_adr(i_wb_adr),
        .wb_dat_w(i_wb_dat_w),
        .wb_sel(i_wb_sel),
        .wb_ack(i_wb_ack),
        .wb_err(i_wb_err),
        .wb_dat_r(i_wb_dat_r)
    );

    wb_master_adapter d_adapter (
        .clk(clk),
        .rst(rst),
        .src_req(core_dmem_req),
        .src_addr(core_dmem_addr),
        .src_wstrb(core_dmem_wstrb),
        .src_wdata(core_dmem_wdata),
        .src_rdata(core_dmem_rdata),
        .src_ready(core_dmem_ready),
        .fault_pulse(d_fault_pulse),
        .wb_cyc(d_wb_cyc),
        .wb_stb(d_wb_stb),
        .wb_we(d_wb_we),
        .wb_adr(d_wb_adr),
        .wb_dat_w(d_wb_dat_w),
        .wb_sel(d_wb_sel),
        .wb_ack(d_wb_ack),
        .wb_err(d_wb_err),
        .wb_dat_r(d_wb_dat_r)
    );

    wb_arbiter arbiter (
        .clk(clk),
        .rst(rst),
        .i_cyc(i_wb_cyc),
        .i_stb(i_wb_stb),
        .i_we(i_wb_we),
        .i_adr(i_wb_adr),
        .i_dat_w(i_wb_dat_w),
        .i_sel(i_wb_sel),
        .i_ack(i_wb_ack),
        .i_err(i_wb_err),
        .i_dat_r(i_wb_dat_r),
        .d_cyc(d_wb_cyc),
        .d_stb(d_wb_stb),
        .d_we(d_wb_we),
        .d_adr(d_wb_adr),
        .d_dat_w(d_wb_dat_w),
        .d_sel(d_wb_sel),
        .d_ack(d_wb_ack),
        .d_err(d_wb_err),
        .d_dat_r(d_wb_dat_r),
        .s_cyc(s_wb_cyc),
        .s_stb(s_wb_stb),
        .s_we(s_wb_we),
        .s_adr(s_wb_adr),
        .s_dat_w(s_wb_dat_w),
        .s_sel(s_wb_sel),
        .s_ack(s_wb_ack),
        .s_err(s_wb_err),
        .s_dat_r(s_wb_dat_r),
        .s_instr(s_wb_instr)
    );

    wb_interconnect u_interconnect (
        .clk(clk),
        .rst(rst),
        .m_cyc(s_wb_cyc),
        .m_stb(s_wb_stb),
        .m_we(s_wb_we),
        .m_instr(s_wb_instr),
        .m_adr(s_wb_adr),
        .m_dat_w(s_wb_dat_w),
        .m_sel(s_wb_sel),
        .m_ack(s_wb_ack),
        .m_err(s_wb_err),
        .m_dat_r(s_wb_dat_r),
        .imem_cyc(imem_cyc),
        .imem_stb(imem_stb),
        .imem_we(imem_we),
        .imem_adr(imem_adr),
        .imem_dat_w(imem_dat_w),
        .imem_sel(imem_sel),
        .imem_ack(imem_ack),
        .imem_err(imem_err),
        .imem_dat_r(imem_dat_r),
        .uart_cyc(uart_cyc),
        .uart_stb(uart_stb),
        .uart_we(uart_we),
        .uart_adr(uart_adr),
        .uart_dat_w(uart_dat_w),
        .uart_sel(uart_sel),
        .uart_ack(uart_ack),
        .uart_err(uart_err),
        .uart_dat_r(uart_dat_r),
        .gpio_cyc(gpio_cyc),
        .gpio_stb(gpio_stb),
        .gpio_we(gpio_we),
        .gpio_adr(gpio_adr),
        .gpio_dat_w(gpio_dat_w),
        .gpio_sel(gpio_sel),
        .gpio_ack(gpio_ack),
        .gpio_err(gpio_err),
        .gpio_dat_r(gpio_dat_r),
        .dmem_cyc(dmem_cyc),
        .dmem_stb(dmem_stb),
        .dmem_we(dmem_we),
        .dmem_adr(dmem_adr),
        .dmem_dat_w(dmem_dat_w),
        .dmem_sel(dmem_sel),
        .dmem_ack(dmem_ack),
        .dmem_err(dmem_err),
        .dmem_dat_r(dmem_dat_r)
    );

    wb_imem #(
        .DEPTH_WORDS(IMEM_DEPTH_WORDS),
        .INIT_FILE(IMEM_INIT_FILE)
    ) instruction_memory (
        .clk(clk),
        .rst(rst),
        .wb_cyc(imem_cyc),
        .wb_stb(imem_stb),
        .wb_we(imem_we),
        .wb_adr(imem_adr),
        .wb_dat_w(imem_dat_w),
        .wb_sel(imem_sel),
        .wb_ack(imem_ack),
        .wb_err(imem_err),
        .wb_dat_r(imem_dat_r)
    );

    wb_dmem #(
        .DEPTH_WORDS(DMEM_DEPTH_WORDS),
        .INIT_FILE(DMEM_INIT_FILE)
    ) data_memory (
        .clk(clk),
        .rst(rst),
        .wb_cyc(dmem_cyc),
        .wb_stb(dmem_stb),
        .wb_we(dmem_we),
        .wb_adr(dmem_adr),
        .wb_dat_w(dmem_dat_w),
        .wb_sel(dmem_sel),
        .wb_ack(dmem_ack),
        .wb_err(dmem_err),
        .wb_dat_r(dmem_dat_r)
    );

    wb_uart #(
        .CLOCK_HZ(CLOCK_HZ),
        .UART_BAUD(UART_BAUD)
    ) uart (
        .clk(clk),
        .rst(rst),
        .wb_cyc(uart_cyc),
        .wb_stb(uart_stb),
        .wb_we(uart_we),
        .wb_adr(uart_adr),
        .wb_dat_w(uart_dat_w),
        .wb_sel(uart_sel),
        .wb_ack(uart_ack),
        .wb_err(uart_err),
        .wb_dat_r(uart_dat_r),
        .tx(uart_tx),
        .tx_ready(uart_ready)
    );

    button_debounce #(
        .STABLE_CYCLES(DEBOUNCE_CYCLES)
    ) debounce (
        .clk(clk),
        .rst(rst),
        .async_in(button_irq),
        .state(button_state),
        .rise(button_rise)
    );

    wb_gpio_irq gpio (
        .clk(clk),
        .rst(rst),
        .wb_cyc(gpio_cyc),
        .wb_stb(gpio_stb),
        .wb_we(gpio_we),
        .wb_adr(gpio_adr),
        .wb_dat_w(gpio_dat_w),
        .wb_sel(gpio_sel),
        .wb_ack(gpio_ack),
        .wb_err(gpio_err),
        .wb_dat_r(gpio_dat_r),
        .button_state(button_state),
        .button_rise(button_rise),
        .led(gpio_led),
        .irq_external(irq_external)
    );

`ifndef SYNTHESIS
    a_slave_response_onehot: assert property (@(posedge clk) disable iff (rst)
        $onehot0({imem_ack, imem_err, uart_ack, uart_err,
                  gpio_ack, gpio_err, dmem_ack, dmem_err}));
    a_master_response_onehot: assert property (@(posedge clk) disable iff (rst)
        $onehot0({i_wb_ack, i_wb_err, d_wb_ack, d_wb_err}));
    a_uncached_not_counted: assert property (@(posedge clk) disable iff (rst)
        core_dmem_req
        && (core_dmem_addr & 32'hffff_8000) != 32'h2000_0000
        |-> !u_core.u_backend.dcache_access);
    a_bus_fault_sticky: assert property (@(posedge clk) disable iff (rst)
        bus_fault |=> bus_fault);
`endif
endmodule

`default_nettype wire
