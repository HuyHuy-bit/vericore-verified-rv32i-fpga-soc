`default_nettype none

import rv32i_pkg::*;

module dcache_counter_tb;
    logic clk = 1'b0;
    logic rst;
    logic req;
    logic advance;
    logic [XLEN-1:0] addr;
    logic [XBYTES-1:0] byte_en;
    logic [XLEN-1:0] write_word;
    logic [XLEN-1:0] read_word;
    logic ready;
    logic [XLEN-1:0] mem_addr;
    logic mem_req;
    logic mem_burst;
    logic [XBYTES-1:0] mem_byte_en;
    logic [XLEN-1:0] mem_write_word;
    logic [XLEN-1:0] mem_read_word;
    logic mem_ready;
    logic flush_req;
    logic flush_done;
    logic access;
    logic miss_pulse;
    int unsigned misses;

    always #1 clk = ~clk;
    always @(posedge clk) if (!rst && miss_pulse) misses++;

    dcache #(
        .BYTES(16),
        .BLOCK_WORDS(1),
        .WAYS(1),
        .WRITE_BACK(0)
    ) dut (
        .clk(clk),
        .rst(rst),
        .req(req),
        .advance(advance),
        .addr(addr),
        .byte_en(byte_en),
        .write_word(write_word),
        .read_word(read_word),
        .ready(ready),
        .mem_addr(mem_addr),
        .mem_req(mem_req),
        .mem_burst(mem_burst),
        .mem_byte_en(mem_byte_en),
        .mem_write_word(mem_write_word),
        .mem_read_word(mem_read_word),
        .mem_ready(mem_ready),
        .flush_req(flush_req),
        .flush_done(flush_done),
        .access(access),
        .miss_pulse(miss_pulse)
    );

    initial begin
        rst = 1'b1;
        req = 1'b0;
        advance = 1'b0;
        addr = '0;
        byte_en = '0;
        write_word = '0;
        mem_read_word = '0;
        mem_ready = 1'b0;
        flush_req = 1'b0;
        misses = 0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        req = 1'b1;
        byte_en = 4'b1111;
        write_word = 32'h12345678;

        repeat (2) @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b1;
        repeat (2) @(posedge clk);

        if (misses != 1) $fatal(1, "miss pulses=%0d want=1", misses);

        @(negedge clk);
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        advance = 1'b0;
        @(posedge clk);
        @(negedge clk);

        if (misses != 2) $fatal(1, "back-to-back miss pulses=%0d want=2", misses);

        req = 1'b0;
        mem_ready = 1'b0;

        @(posedge clk);
        @(negedge clk);
        req = 1'b1;
        addr = 32'd4;
        mem_ready = 1'b1;
        repeat (2) @(posedge clk);
        @(negedge clk);

        if (misses != 3) $fatal(1, "immediate miss pulses=%0d want=3", misses);

        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;

        $display("PASS dcache counter: one pulse per access");
        $finish;
    end
endmodule

`default_nettype wire
