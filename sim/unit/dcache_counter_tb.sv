`default_nettype none

import rv32i_pkg::*;

module dcache_counter_tb;
    logic clk = 1'b0;
    logic rst;
    logic req;
    logic cacheable;
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

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    dcache #(
        .BYTES(16),
        .BLOCK_WORDS(1),
        .WAYS(1),
        .WRITE_BACK(0)
    ) dut (
        .clk(clk),
        .rst(rst),
        .req(req),
        .cacheable(cacheable),
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
        cacheable = 1'b0;
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
        addr = 32'h1000_0004;
        byte_en = 4'b0000;
        mem_read_word = 32'h0000_0001;
        @(posedge clk);
        @(negedge clk);
        repeat (2) begin
            check(mem_req, "uncached load was not forwarded");
            check(mem_addr == 32'h1000_0004, "uncached load address mismatch");
            check(!ready && !access && !miss_pulse,
                  "uncached load affected cache accounting");
            @(posedge clk);
            @(negedge clk);
        end
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        check(ready, "uncached load did not mirror memory ready");
        check(read_word == 32'h0000_0001, "uncached load data mismatch");
        mem_ready = 1'b0;
        mem_read_word = 32'hdead_beef;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "uncached load completion was not held");
        check(read_word == 32'h0000_0001, "uncached load data was not held");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        mem_ready = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        req = 1'b1;
        addr = 32'h1000_0000;
        byte_en = 4'b0001;
        write_word = 32'h0000_0041;
        @(posedge clk);
        @(negedge clk);
        check(mem_req && mem_byte_en == 4'b0001,
              "uncached store byte lane mismatch");
        check(mem_write_word == 32'h0000_0041,
              "uncached store data mismatch");
        check(!access && !miss_pulse, "uncached store affected cache accounting");
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "uncached store completion was reissued");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        req = 1'b1;
        addr = 32'h1000_0000;
        byte_en = 4'b0001;
        write_word = 32'h0000_0043;
        @(posedge clk);
        @(negedge clk);
        check(mem_req, "mid-flight store did not start");
        flush_req = 1'b1;
        repeat (2) begin
            @(posedge clk);
            @(negedge clk);
            check(mem_req && !flush_done,
                  "flush interrupted mid-flight uncached store");
        end
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "mid-flight store completion was not held");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;
        for (int cycle = 0; cycle < 8 && !flush_done; cycle++) begin
            check(!mem_req, "completed mid-flight store was reissued");
            @(posedge clk);
            @(negedge clk);
        end
        check(flush_done, "deferred flush did not finish");
        flush_req = 1'b0;
        @(posedge clk);
        @(negedge clk);

        cacheable = 1'b1;
        req = 1'b1;
        addr = 32'h0000_0040;
        byte_en = 4'b0001;
        write_word = 32'h0000_0044;
        @(posedge clk);
        @(negedge clk);
        check(mem_req, "write-through store did not start");
        flush_req = 1'b1;
        repeat (2) begin
            @(posedge clk);
            @(negedge clk);
            check(mem_req && !flush_done,
                  "flush interrupted mid-flight write-through store");
        end
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "write-through completion was not held");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;
        for (int cycle = 0; cycle < 8 && !flush_done; cycle++) begin
            check(!mem_req, "completed write-through store was reissued");
            @(posedge clk);
            @(negedge clk);
        end
        check(flush_done, "write-through deferred flush did not finish");
        flush_req = 1'b0;
        @(posedge clk);
        @(negedge clk);
        cacheable = 1'b0;
        misses = 0;

        req = 1'b1;
        addr = 32'h1000_0000;
        byte_en = 4'b0001;
        write_word = 32'h0000_0042;
        flush_req = 1'b1;
        @(posedge clk);
        check(!mem_req && !ready, "flush did not block uncached store start");
        @(negedge clk);
        for (int cycle = 0; cycle < 8 && !flush_done; cycle++) begin
            check(!mem_req, "uncached store leaked during flush");
            @(posedge clk);
            @(negedge clk);
        end
        check(flush_done, "flush did not finish");
        flush_req = 1'b0;
        @(posedge clk);
        @(negedge clk);
        repeat (2) begin
            check(mem_req && mem_addr == 32'h1000_0000,
                  "uncached store did not start after flush");
            check(mem_byte_en == 4'b0001 && mem_write_word == 32'h0000_0042,
                  "post-flush uncached store fields changed");
            @(posedge clk);
            @(negedge clk);
        end
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "post-flush store completion was reissued");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        cacheable = 1'b1;
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
        mem_ready = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        req = 1'b1;
        addr = 32'h0000_0020;
        byte_en = 4'b0000;
        mem_read_word = 32'hcafe_babe;
        @(posedge clk);
        @(negedge clk);
        check(misses == 4, "cacheable load miss was not counted once");
        check(mem_req && mem_addr == 32'h0000_0020,
              "cacheable load miss did not refill");
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && read_word == 32'hcafe_babe,
              "cacheable refill did not complete load");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        req = 1'b1;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req, "cacheable second load was not a hit");
        check(read_word == 32'hcafe_babe, "cacheable hit data mismatch");
        check(misses == 4, "cacheable hit raised a miss");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;
        advance = 1'b0;

        @(posedge clk);
        @(negedge clk);
        cacheable = 1'b0;
        req = 1'b1;
        mem_read_word = 32'hface_feed;
        @(posedge clk);
        @(negedge clk);
        check(mem_req && !access && !miss_pulse,
              "uncached alias used the resident cache line");
        mem_ready = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mem_ready = 1'b0;
        @(posedge clk);
        @(negedge clk);
        check(ready && !mem_req && read_word == 32'hface_feed,
              "uncached alias did not return backing data once");
        advance = 1'b1;
        @(posedge clk);
        @(negedge clk);
        req = 1'b0;

        $display("PASS dcache counter: one pulse per access");
        $finish;
    end

    initial begin
        repeat (500) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
