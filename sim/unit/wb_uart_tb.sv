`default_nettype none

module wb_uart_tb;
    logic clk = 1'b0;
    logic rst;
    logic wb_cyc, wb_stb, wb_we, wb_ack, wb_err;
    logic [31:0] wb_adr, wb_dat_w, wb_dat_r;
    logic [3:0] wb_sel;
    logic tx, tx_ready;
    int unsigned accepted;

    always #1 clk = ~clk;
    always @(posedge clk) if (!rst && dut.tx_valid && tx_ready) accepted++;

    wb_uart #(.CLOCK_HZ(80), .UART_BAUD(10)) dut (
        .clk(clk), .rst(rst),
        .wb_cyc(wb_cyc), .wb_stb(wb_stb), .wb_we(wb_we),
        .wb_adr(wb_adr), .wb_dat_w(wb_dat_w), .wb_sel(wb_sel),
        .wb_ack(wb_ack), .wb_err(wb_err), .wb_dat_r(wb_dat_r),
        .tx(tx), .tx_ready(tx_ready)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic wb_access(input logic [31:0] addr,
                             input logic we,
                             input logic [3:0] sel,
                             input logic [31:0] write_data,
                             input logic expected_error,
                             output logic [31:0] read_data,
                             output int cycles);
        begin
            @(negedge clk);
            wb_cyc = 1'b1;
            wb_stb = 1'b1;
            wb_we = we;
            wb_adr = addr;
            wb_sel = sel;
            wb_dat_w = write_data;
            cycles = 0;
            while (!(wb_ack || wb_err) && cycles < 150) begin
                @(posedge clk);
                @(negedge clk);
                cycles++;
            end
            check(cycles < 150, "Wishbone UART timeout");
            check(wb_err == expected_error, "Wishbone UART ERR mismatch");
            check(wb_ack == !expected_error, "Wishbone UART ACK mismatch");
            read_data = wb_dat_r;
            wb_cyc = 1'b0;
            wb_stb = 1'b0;
            @(posedge clk);
            @(negedge clk);
            check(!wb_ack && !wb_err, "Wishbone UART repeated response");
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    logic [31:0] value;
    int cycles;

    initial begin
        rst = 1'b1;
        wb_cyc = 1'b0; wb_stb = 1'b0; wb_we = 1'b0;
        wb_adr = '0; wb_dat_w = '0; wb_sel = '0;
        accepted = 0;
        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;
        check(tx && tx_ready, "Wishbone UART reset state wrong");

        wb_access(32'h1000_0004, 1'b0, 4'hf, '0, 1'b0, value, cycles);
        check(value == 32'h1, "ready STATUS mismatch");

        wb_access(32'h1000_0000, 1'b1, 4'h1, 32'h0000_00a5,
                  1'b0, value, cycles);
        check(accepted == 1 && !tx_ready, "first TXDATA was not accepted once");

        wb_access(32'h1000_0004, 1'b0, 4'hf, '0, 1'b0, value, cycles);
        check(value == 32'h0, "busy STATUS mismatch");
        wb_access(32'h1000_0000, 1'b0, 4'hf, '0, 1'b0, value, cycles);
        check(value == 32'h0, "TXDATA read mismatch");

        wb_access(32'h1000_0000, 1'b1, 4'h1, 32'h0000_003c,
                  1'b0, value, cycles);
        check(cycles > 1, "busy TXDATA was not backpressured");
        check(accepted == 2, "second TXDATA acceptance count mismatch");

        wb_access(32'h1000_0004, 1'b1, 4'hf, 32'h1,
                  1'b1, value, cycles);
        wb_access(32'h1000_0008, 1'b0, 4'hf, '0,
                  1'b1, value, cycles);
        wb_access(32'h1000_0002, 1'b0, 4'hf, '0,
                  1'b1, value, cycles);
        wb_access(32'h1000_0000, 1'b1, 4'h2, 32'h0000_0041,
                  1'b1, value, cycles);
        check(accepted == 2, "invalid access transmitted data");

        $display("PASS Wishbone UART");
        $finish;
    end

    initial begin
        repeat (500) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
