`default_nettype none

module wb_arbiter_tb;
    logic clk = 1'b0;
    logic rst;
    logic i_cyc, i_stb, i_we, i_ack, i_err;
    logic [31:0] i_adr, i_dat_w, i_dat_r;
    logic [3:0] i_sel;
    logic d_cyc, d_stb, d_we, d_ack, d_err;
    logic [31:0] d_adr, d_dat_w, d_dat_r;
    logic [3:0] d_sel;
    logic s_cyc, s_stb, s_we, s_ack, s_err, s_instr;
    logic [31:0] s_adr, s_dat_w, s_dat_r;
    logic [3:0] s_sel;

    always #1 clk = ~clk;

    wb_arbiter dut (
        .clk(clk), .rst(rst),
        .i_cyc(i_cyc), .i_stb(i_stb), .i_we(i_we), .i_adr(i_adr),
        .i_dat_w(i_dat_w), .i_sel(i_sel), .i_ack(i_ack), .i_err(i_err),
        .i_dat_r(i_dat_r),
        .d_cyc(d_cyc), .d_stb(d_stb), .d_we(d_we), .d_adr(d_adr),
        .d_dat_w(d_dat_w), .d_sel(d_sel), .d_ack(d_ack), .d_err(d_err),
        .d_dat_r(d_dat_r),
        .s_cyc(s_cyc), .s_stb(s_stb), .s_we(s_we), .s_adr(s_adr),
        .s_dat_w(s_dat_w), .s_sel(s_sel), .s_ack(s_ack), .s_err(s_err),
        .s_dat_r(s_dat_r), .s_instr(s_instr)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic grant_wait;
        begin
            @(posedge clk);
            @(negedge clk);
            check(s_cyc && s_stb, "shared request not granted");
        end
    endtask

    initial begin
        rst = 1'b1;
        i_cyc = 1'b0; i_stb = 1'b0; i_we = 1'b0;
        i_adr = '0; i_dat_w = '0; i_sel = 4'hf;
        d_cyc = 1'b0; d_stb = 1'b0; d_we = 1'b0;
        d_adr = '0; d_dat_w = '0; d_sel = 4'hf;
        s_ack = 1'b0; s_err = 1'b0; s_dat_r = '0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        i_cyc = 1'b1;
        i_stb = 1'b1;
        i_adr = 32'h0000_0010;
        grant_wait();
        check(s_instr && s_adr == i_adr, "uncontested instruction grant wrong");
        s_dat_r = 32'h1111_2222;
        s_ack = 1'b1;
        @(posedge clk);
        check(i_ack && !d_ack, "instruction ACK routing wrong");
        check(i_dat_r == s_dat_r, "instruction read data routing wrong");
        @(negedge clk);
        s_ack = 1'b0;
        i_cyc = 1'b0;
        i_stb = 1'b0;

        i_cyc = 1'b1;
        i_stb = 1'b1;
        i_adr = 32'h0000_0020;
        d_cyc = 1'b1;
        d_stb = 1'b1;
        d_we = 1'b1;
        d_adr = 32'h2000_0000;
        d_dat_w = 32'h55aa_55aa;
        d_sel = 4'b1111;
        grant_wait();
        check(s_instr && s_adr == i_adr, "first contested grant was not instruction");
        repeat (4) begin
            d_adr = d_adr + 32'd4;
            @(posedge clk);
            @(negedge clk);
            check(s_instr && s_adr == i_adr, "grant changed while waiting");
            check(!i_ack && !i_err && !d_ack && !d_err, "response leaked while waiting");
        end

        s_ack = 1'b1;
        @(posedge clk);
        check(i_ack && !d_ack, "contested instruction ACK routing wrong");
        @(negedge clk);
        s_ack = 1'b0;
        grant_wait();
        check(!s_instr && s_adr == d_adr, "data did not win next contested grant");
        s_err = 1'b1;
        @(posedge clk);
        check(d_err && !i_err, "shared ERR reached wrong owner");
        check(!d_ack && !i_ack, "ERR also raised ACK");
        @(negedge clk);
        s_err = 1'b0;

        grant_wait();
        check(s_instr && s_adr == i_adr,
              "third contested grant was not instruction");
        s_ack = 1'b1;
        @(posedge clk);
        check(i_ack && !d_ack, "third contested ACK routing wrong");
        @(negedge clk);
        s_ack = 1'b0;

        i_cyc = 1'b0;
        i_stb = 1'b0;
        grant_wait();
        check(!s_instr && s_adr == d_adr, "uncontested data grant wrong");
        s_ack = 1'b1;
        @(posedge clk);
        check(d_ack && !i_ack, "uncontested data ACK routing wrong");
        @(negedge clk);
        s_ack = 1'b0;

        i_cyc = 1'b1;
        i_stb = 1'b1;
        grant_wait();
        check(!s_instr && s_adr == d_adr,
              "fourth contested grant did not preserve alternation");
        s_ack = 1'b1;
        @(posedge clk);
        check(d_ack && !i_ack, "fourth contested ACK routing wrong");
        @(negedge clk);
        s_ack = 1'b0;

        i_cyc = 1'b0;
        i_stb = 1'b0;
        d_cyc = 1'b0;
        d_stb = 1'b0;

        @(posedge clk);
        @(negedge clk);
        check(!s_cyc && !s_stb, "shared request remained active");
        check(!i_ack && !i_err && !d_ack && !d_err, "idle response asserted");

        $display("PASS Wishbone arbiter");
        $finish;
    end

    initial begin
        repeat (200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
