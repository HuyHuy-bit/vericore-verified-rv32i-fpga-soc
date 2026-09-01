`default_nettype none

module wb_master_adapter_tb;
    logic clk = 1'b0;
    logic rst;
    logic src_req;
    logic [31:0] src_addr;
    logic [3:0] src_wstrb;
    logic [31:0] src_wdata;
    logic [31:0] src_rdata;
    logic src_ready;
    logic fault_pulse;
    logic wb_cyc;
    logic wb_stb;
    logic wb_we;
    logic [31:0] wb_adr;
    logic [31:0] wb_dat_w;
    logic [3:0] wb_sel;
    logic wb_ack;
    logic wb_err;
    logic [31:0] wb_dat_r;

    always #1 clk = ~clk;

    wb_master_adapter dut (
        .clk(clk), .rst(rst),
        .src_req(src_req), .src_addr(src_addr), .src_wstrb(src_wstrb),
        .src_wdata(src_wdata), .src_rdata(src_rdata), .src_ready(src_ready),
        .fault_pulse(fault_pulse),
        .wb_cyc(wb_cyc), .wb_stb(wb_stb), .wb_we(wb_we),
        .wb_adr(wb_adr), .wb_dat_w(wb_dat_w), .wb_sel(wb_sel),
        .wb_ack(wb_ack), .wb_err(wb_err), .wb_dat_r(wb_dat_r)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic start_request(input logic [31:0] addr,
                                 input logic [3:0] wstrb,
                                 input logic [31:0] wdata);
        begin
            @(negedge clk);
            src_req = 1'b1;
            src_addr = addr;
            src_wstrb = wstrb;
            src_wdata = wdata;
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    task automatic finish_ack(input logic [31:0] data);
        begin
            wb_dat_r = data;
            wb_ack = 1'b1;
            @(posedge clk);
            check(src_ready, "ACK did not complete source request");
            check(!fault_pulse, "ACK raised fault");
            check(src_rdata == data, "ACK read data mismatch");
            @(negedge clk);
            wb_ack = 1'b0;
            src_req = 1'b0;
            #1;
            check(src_ready, "idle source not ready after ACK");
            check(!fault_pulse, "fault pulse lasted beyond response");
        end
    endtask

    initial begin
        rst = 1'b1;
        src_req = 1'b0;
        src_addr = '0;
        src_wstrb = '0;
        src_wdata = '0;
        wb_ack = 1'b0;
        wb_err = 1'b0;
        wb_dat_r = '0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        check(src_ready, "idle source not ready");
        check(!wb_cyc && !wb_stb, "idle Wishbone request asserted");

        start_request(32'h2000_0010, 4'b0000, 32'hdead_beef);
        check(wb_cyc && wb_stb, "read did not start Wishbone cycle");
        check(!wb_we && wb_sel == 4'b1111, "read controls incorrect");
        check(wb_adr == 32'h2000_0010, "read address mismatch");
        repeat (3) begin
            @(posedge clk);
            @(negedge clk);
            check(wb_cyc && wb_stb, "delayed read request dropped");
            check(wb_adr == 32'h2000_0010, "delayed read address changed");
            check(!src_ready, "source completed without response");
        end
        finish_ack(32'h1234_5678);

        start_request(32'h0000_0241, 4'b0000, 32'h0);
        check(wb_adr == 32'h0000_0240,
              "subword read did not align the Wishbone word address");
        finish_ack(32'h3233_7672);

        start_request(32'h1000_0000, 4'b0100, 32'h00aa_0000);
        check(wb_we && wb_sel == 4'b0100, "byte write controls incorrect");
        check(wb_dat_w == 32'h00aa_0000, "byte write data mismatch");
        wb_ack = 1'b1;
        @(posedge clk);
        check(src_ready, "write ACK did not complete source request");
        @(negedge clk);
        wb_ack = 1'b0;
        src_addr = 32'h0000_0040;
        src_wstrb = 4'b0000;
        src_wdata = 32'h0;
        @(posedge clk);
        @(negedge clk);
        check(wb_cyc && wb_adr == 32'h0000_0040,
              "back-to-back request was not accepted");
        finish_ack(32'h0000_006f);

        start_request(32'hffff_ffff, 4'b0000, 32'h0);
        wb_err = 1'b1;
        wb_dat_r = 32'hffff_ffff;
        @(posedge clk);
        check(src_ready, "ERR did not complete source request");
        check(src_rdata == 32'h0, "ERR did not return zero data");
        @(negedge clk);
        wb_err = 1'b0;
        src_req = 1'b0;
        #1;
        check(fault_pulse, "ERR did not raise fault pulse");
        @(posedge clk);
        @(negedge clk);
        check(!fault_pulse, "fault pulse did not clear");

        $display("PASS Wishbone request adapter");
        $finish;
    end

    initial begin
        repeat (200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
