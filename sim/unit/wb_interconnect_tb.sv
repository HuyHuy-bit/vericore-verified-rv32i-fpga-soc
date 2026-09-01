`default_nettype none

module wb_interconnect_tb;
    localparam int IMEM = 0;
    localparam int UART = 1;
    localparam int GPIO = 2;
    localparam int DMEM = 3;
    localparam int NONE = 4;

    logic clk = 1'b0;
    logic rst;
    logic m_cyc, m_stb, m_we, m_instr, m_ack, m_err;
    logic [31:0] m_adr, m_dat_w, m_dat_r;
    logic [3:0] m_sel;

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

    always #1 clk = ~clk;

    wb_interconnect dut (
        .clk(clk), .rst(rst),
        .m_cyc(m_cyc), .m_stb(m_stb), .m_we(m_we), .m_instr(m_instr),
        .m_adr(m_adr), .m_dat_w(m_dat_w), .m_sel(m_sel),
        .m_ack(m_ack), .m_err(m_err), .m_dat_r(m_dat_r),
        .imem_cyc(imem_cyc), .imem_stb(imem_stb), .imem_we(imem_we),
        .imem_adr(imem_adr), .imem_dat_w(imem_dat_w), .imem_sel(imem_sel),
        .imem_ack(imem_ack), .imem_err(imem_err), .imem_dat_r(imem_dat_r),
        .uart_cyc(uart_cyc), .uart_stb(uart_stb), .uart_we(uart_we),
        .uart_adr(uart_adr), .uart_dat_w(uart_dat_w), .uart_sel(uart_sel),
        .uart_ack(uart_ack), .uart_err(uart_err), .uart_dat_r(uart_dat_r),
        .gpio_cyc(gpio_cyc), .gpio_stb(gpio_stb), .gpio_we(gpio_we),
        .gpio_adr(gpio_adr), .gpio_dat_w(gpio_dat_w), .gpio_sel(gpio_sel),
        .gpio_ack(gpio_ack), .gpio_err(gpio_err), .gpio_dat_r(gpio_dat_r),
        .dmem_cyc(dmem_cyc), .dmem_stb(dmem_stb), .dmem_we(dmem_we),
        .dmem_adr(dmem_adr), .dmem_dat_w(dmem_dat_w), .dmem_sel(dmem_sel),
        .dmem_ack(dmem_ack), .dmem_err(dmem_err), .dmem_dat_r(dmem_dat_r)
    );

    task automatic check(input logic condition, input string label);
        if (!condition) $fatal(1, "%s", label);
    endtask

    task automatic clear_responses;
        begin
            imem_ack = 1'b0; imem_err = 1'b0;
            uart_ack = 1'b0; uart_err = 1'b0;
            gpio_ack = 1'b0; gpio_err = 1'b0;
            dmem_ack = 1'b0; dmem_err = 1'b0;
        end
    endtask

    task automatic expect_slave(input int slave, input string label);
        logic [3:0] active;
        begin
            active = {dmem_cyc && dmem_stb, gpio_cyc && gpio_stb,
                      uart_cyc && uart_stb, imem_cyc && imem_stb};
            case (slave)
                IMEM: check(active == 4'b0001, label);
                UART: check(active == 4'b0010, label);
                GPIO: check(active == 4'b0100, label);
                DMEM: check(active == 4'b1000, label);
                default: check(active == 4'b0000, label);
            endcase
        end
    endtask

    task automatic start_request(input logic [31:0] addr,
                                 input logic instr,
                                 input logic we,
                                 input logic [3:0] sel,
                                 input logic [31:0] data);
        begin
            @(negedge clk);
            m_cyc = 1'b1;
            m_stb = 1'b1;
            m_adr = addr;
            m_instr = instr;
            m_we = we;
            m_sel = sel;
            m_dat_w = data;
            @(posedge clk);
            @(negedge clk);
        end
    endtask

    task automatic complete_slave(input int slave,
                                  input logic [31:0] data,
                                  input string label);
        begin
            case (slave)
                IMEM: begin imem_dat_r = data; imem_ack = 1'b1; end
                UART: begin uart_dat_r = data; uart_ack = 1'b1; end
                GPIO: begin gpio_dat_r = data; gpio_ack = 1'b1; end
                DMEM: begin dmem_dat_r = data; dmem_ack = 1'b1; end
                default: $fatal(1, "invalid slave completion");
            endcase
            @(posedge clk);
            check(m_ack && !m_err, label);
            check(m_dat_r == data, "master read data mismatch");
            @(negedge clk);
            clear_responses();
            m_cyc = 1'b0;
            m_stb = 1'b0;
        end
    endtask

    task automatic check_decode(input logic [31:0] addr,
                                input logic instr,
                                input logic we,
                                input int slave,
                                input string label);
        begin
            start_request(addr, instr, we, we ? 4'b0101 : 4'b1111,
                          32'ha5a5_5a5a);
            expect_slave(slave, label);
            case (slave)
                IMEM: begin
                    check(imem_adr == addr && imem_we == we, "IMEM fields wrong");
                    check(imem_sel == (we ? 4'b0101 : 4'b1111), "IMEM select wrong");
                end
                UART: check(uart_adr == addr && uart_we == we, "UART fields wrong");
                GPIO: check(gpio_adr == addr && gpio_we == we, "GPIO fields wrong");
                DMEM: begin
                    check(dmem_adr == addr && dmem_we == we, "DMEM fields wrong");
                    check(dmem_dat_w == 32'ha5a5_5a5a, "DMEM write data wrong");
                end
            endcase
            complete_slave(slave, addr ^ 32'h1357_9bdf, label);
        end
    endtask

    task automatic check_error(input logic [31:0] addr,
                               input logic instr,
                               input string label);
        begin
            start_request(addr, instr, 1'b0, 4'hf, 32'h0);
            expect_slave(NONE, label);
            check(m_err && !m_ack, label);
            check(m_dat_r == 32'h0, "default error data not zero");
            @(posedge clk);
            @(negedge clk);
            m_cyc = 1'b0;
            m_stb = 1'b0;
        end
    endtask

    task automatic check_slave_error(input logic [31:0] addr,
                                     input int slave,
                                     input string label);
        begin
            start_request(addr, 1'b0, 1'b0, 4'hf, 32'h0);
            expect_slave(slave, label);
            case (slave)
                IMEM: begin imem_dat_r = 32'hdead_beef; imem_err = 1'b1; end
                UART: begin uart_dat_r = 32'hdead_beef; uart_err = 1'b1; end
                GPIO: begin gpio_dat_r = 32'hdead_beef; gpio_err = 1'b1; end
                DMEM: begin dmem_dat_r = 32'hdead_beef; dmem_err = 1'b1; end
                default: $fatal(1, "invalid slave error");
            endcase
            @(posedge clk);
            check(m_err && !m_ack, label);
            check(m_dat_r == 32'h0, "mapped error data not zero");
            @(negedge clk);
            clear_responses();
            m_cyc = 1'b0;
            m_stb = 1'b0;
        end
    endtask

    initial begin
        rst = 1'b1;
        m_cyc = 1'b0; m_stb = 1'b0; m_we = 1'b0; m_instr = 1'b0;
        m_adr = '0; m_dat_w = '0; m_sel = '0;
        imem_dat_r = '0; uart_dat_r = '0; gpio_dat_r = '0; dmem_dat_r = '0;
        clear_responses();

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        check_decode(32'h0000_0000, 1'b1, 1'b0, IMEM, "IMEM first instruction");
        check_decode(32'h0000_7fff, 1'b0, 1'b0, IMEM, "IMEM last data read");
        check_decode(32'h0000_0000, 1'b0, 1'b1, IMEM, "IMEM data write route");
        check_decode(32'h1000_0000, 1'b0, 1'b0, UART, "UART first");
        check_decode(32'h1000_000f, 1'b0, 1'b1, UART, "UART last");
        check_decode(32'h1000_1000, 1'b0, 1'b0, GPIO, "GPIO first");
        check_decode(32'h1000_100c, 1'b0, 1'b0, GPIO, "GPIO register");
        check_decode(32'h1000_101f, 1'b0, 1'b1, GPIO, "GPIO last");
        check_decode(32'h2000_0000, 1'b0, 1'b1, DMEM, "DMEM first");
        check_decode(32'h2000_7fff, 1'b0, 1'b0, DMEM, "DMEM last");

        check_error(32'h1000_0000, 1'b1, "instruction UART denied");
        check_error(32'h1000_1000, 1'b1, "instruction GPIO denied");
        check_error(32'h2000_0000, 1'b1, "instruction DMEM denied");
        check_error(32'h0000_8000, 1'b0, "unmapped lower address");
        check_error(32'hffff_ffff, 1'b0, "unmapped upper address");
        check_slave_error(32'h1000_0004, UART, "mapped UART error");

        start_request(32'h1000_0004, 1'b0, 1'b0, 4'hf, 32'h0);
        expect_slave(UART, "latched UART selection missing");
        m_adr = 32'h2000_0000;
        m_instr = 1'b1;
        m_we = 1'b1;
        m_sel = 4'b0001;
        m_dat_w = 32'hffff_ffff;
        repeat (3) begin
            @(posedge clk);
            @(negedge clk);
            expect_slave(UART, "slave selection changed while active");
            check(uart_adr == 32'h1000_0004, "latched address changed");
            check(!uart_we && uart_sel == 4'hf, "latched identity changed");
        end
        complete_slave(UART, 32'h1, "latched UART response");

        $display("PASS Wishbone interconnect");
        $finish;
    end

    initial begin
        repeat (500) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
