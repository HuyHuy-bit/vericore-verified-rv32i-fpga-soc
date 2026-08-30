`default_nettype none

module wb_memory_tb;
    logic clk = 1'b0;
    logic rst;
    logic i_cyc, i_stb, i_we, i_ack, i_err;
    logic [31:0] i_adr, i_dat_w, i_dat_r;
    logic [3:0] i_sel;
    logic d_cyc, d_stb, d_we, d_ack, d_err;
    logic [31:0] d_adr, d_dat_w, d_dat_r;
    logic [3:0] d_sel;
    logic [31:0] value;

    always #1 clk = ~clk;

    wb_imem #(
        .DEPTH_WORDS(8),
        .INIT_FILE("sim/fixtures/wb_memory.hex")
    ) u_imem (
        .clk(clk), .rst(rst),
        .wb_cyc(i_cyc), .wb_stb(i_stb), .wb_we(i_we), .wb_adr(i_adr),
        .wb_dat_w(i_dat_w), .wb_sel(i_sel),
        .wb_ack(i_ack), .wb_err(i_err), .wb_dat_r(i_dat_r)
    );

    wb_dmem #(
        .DEPTH_WORDS(8),
        .INIT_FILE("sim/fixtures/wb_memory.hex")
    ) u_dmem (
        .clk(clk), .rst(rst),
        .wb_cyc(d_cyc), .wb_stb(d_stb), .wb_we(d_we), .wb_adr(d_adr),
        .wb_dat_w(d_dat_w), .wb_sel(d_sel),
        .wb_ack(d_ack), .wb_err(d_err), .wb_dat_r(d_dat_r)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic imem_access(input logic [31:0] addr,
                               input logic we,
                               input logic expected_error,
                               output logic [31:0] data);
        begin
            @(negedge clk);
            i_cyc = 1'b1;
            i_stb = 1'b1;
            i_we = we;
            i_adr = addr;
            i_dat_w = 32'hdead_beef;
            i_sel = 4'hf;
            check(!i_ack && !i_err, "IMEM response was combinational");
            @(posedge clk);
            @(negedge clk);
            check(i_err == expected_error, "IMEM error response mismatch");
            check(i_ack == !expected_error, "IMEM ACK response mismatch");
            data = i_dat_r;
            @(posedge clk);
            @(negedge clk);
            check(!i_ack && !i_err, "IMEM repeated response");
            i_cyc = 1'b0;
            i_stb = 1'b0;
            @(posedge clk);
        end
    endtask

    task automatic dmem_access(input logic [31:0] addr,
                               input logic we,
                               input logic [3:0] sel,
                               input logic [31:0] write_data,
                               input logic expected_error,
                               output logic [31:0] data);
        begin
            @(negedge clk);
            d_cyc = 1'b1;
            d_stb = 1'b1;
            d_we = we;
            d_adr = addr;
            d_dat_w = write_data;
            d_sel = sel;
            check(!d_ack && !d_err, "DMEM response was combinational");
            @(posedge clk);
            @(negedge clk);
            check(d_err == expected_error, "DMEM error response mismatch");
            check(d_ack == !expected_error, "DMEM ACK response mismatch");
            data = d_dat_r;
            @(posedge clk);
            @(negedge clk);
            check(!d_ack && !d_err, "DMEM repeated response");
            d_cyc = 1'b0;
            d_stb = 1'b0;
            @(posedge clk);
        end
    endtask

    initial begin
        rst = 1'b1;
        i_cyc = 1'b0; i_stb = 1'b0; i_we = 1'b0;
        i_adr = '0; i_dat_w = '0; i_sel = '0;
        d_cyc = 1'b0; d_stb = 1'b0; d_we = 1'b0;
        d_adr = '0; d_dat_w = '0; d_sel = '0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        imem_access(32'h0000_0000, 1'b0, 1'b0, value);
        check(value == 32'h0000_0013, "first instruction mismatch");
        imem_access(32'h0000_001c, 1'b0, 1'b0, value);
        check(value == 32'h0000_006f, "last instruction mismatch");
        imem_access(32'h0000_0000, 1'b1, 1'b1, value);
        check(value == 32'h0, "IMEM write error data not zero");
        imem_access(32'h0000_0002, 1'b0, 1'b1, value);
        imem_access(32'h0000_0020, 1'b0, 1'b1, value);

        dmem_access(32'h2000_0000, 1'b1, 4'b0100,
                    32'h00aa_0000, 1'b0, value);
        dmem_access(32'h2000_0000, 1'b0, 4'hf, 32'h0, 1'b0, value);
        check(value == 32'h00aa_0013, "DMEM byte write mismatch");
        dmem_access(32'h2000_001c, 1'b0, 4'hf, 32'h0, 1'b0, value);
        check(value == 32'h0000_006f, "DMEM last word mismatch");
        dmem_access(32'h1fff_fffc, 1'b0, 4'hf, 32'h0, 1'b1, value);
        dmem_access(32'h2000_0002, 1'b0, 4'hf, 32'h0, 1'b1, value);
        dmem_access(32'h2000_0020, 1'b0, 4'hf, 32'h0, 1'b1, value);

        $display("PASS Wishbone memories");
        $finish;
    end

    initial begin
        repeat (300) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
