`default_nettype none

module wb_interconnect (
    input  var logic clk,
    input  var logic rst,
    input  var logic m_cyc,
    input  var logic m_stb,
    input  var logic m_we,
    input  var logic m_instr,
    input  var logic [31:0] m_adr,
    input  var logic [31:0] m_dat_w,
    input  var logic [3:0] m_sel,
    output var logic m_ack,
    output var logic m_err,
    output var logic [31:0] m_dat_r,
    output var logic imem_cyc,
    output var logic imem_stb,
    output var logic imem_we,
    output var logic [31:0] imem_adr,
    output var logic [31:0] imem_dat_w,
    output var logic [3:0] imem_sel,
    input  var logic imem_ack,
    input  var logic imem_err,
    input  var logic [31:0] imem_dat_r,
    output var logic uart_cyc,
    output var logic uart_stb,
    output var logic uart_we,
    output var logic [31:0] uart_adr,
    output var logic [31:0] uart_dat_w,
    output var logic [3:0] uart_sel,
    input  var logic uart_ack,
    input  var logic uart_err,
    input  var logic [31:0] uart_dat_r,
    output var logic gpio_cyc,
    output var logic gpio_stb,
    output var logic gpio_we,
    output var logic [31:0] gpio_adr,
    output var logic [31:0] gpio_dat_w,
    output var logic [3:0] gpio_sel,
    input  var logic gpio_ack,
    input  var logic gpio_err,
    input  var logic [31:0] gpio_dat_r,
    output var logic dmem_cyc,
    output var logic dmem_stb,
    output var logic dmem_we,
    output var logic [31:0] dmem_adr,
    output var logic [31:0] dmem_dat_w,
    output var logic [3:0] dmem_sel,
    input  var logic dmem_ack,
    input  var logic dmem_err,
    input  var logic [31:0] dmem_dat_r
);
    localparam logic [31:0] IMEM_BASE = 32'h0000_0000;
    localparam logic [31:0] IMEM_LAST = 32'h0000_7fff;
    localparam logic [31:0] UART_BASE = 32'h1000_0000;
    localparam logic [31:0] UART_LAST = 32'h1000_000f;
    localparam logic [31:0] GPIO_BASE = 32'h1000_1000;
    localparam logic [31:0] GPIO_LAST = 32'h1000_101f;
    localparam logic [31:0] DMEM_BASE = 32'h2000_0000;
    localparam logic [31:0] DMEM_LAST = 32'h2000_7fff;

    typedef enum logic [2:0] {SEL_IMEM, SEL_UART, SEL_GPIO,
                              SEL_DMEM, SEL_DEFAULT} slave_t;
    slave_t selection, decoded_selection;
    logic active;
    logic instr_q, we_q;
    logic [31:0] adr_q, dat_w_q;
    logic [3:0] sel_q;
    logic response;

    always_comb begin
        if (m_adr <= IMEM_LAST)
            decoded_selection = SEL_IMEM;
        else if (!m_instr && m_adr >= UART_BASE && m_adr <= UART_LAST)
            decoded_selection = SEL_UART;
        else if (!m_instr && m_adr >= GPIO_BASE && m_adr <= GPIO_LAST)
            decoded_selection = SEL_GPIO;
        else if (!m_instr && m_adr >= DMEM_BASE && m_adr <= DMEM_LAST)
            decoded_selection = SEL_DMEM;
        else
            decoded_selection = SEL_DEFAULT;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            active <= 1'b0;
            selection <= SEL_DEFAULT;
            instr_q <= 1'b0;
            we_q <= 1'b0;
            adr_q <= '0;
            dat_w_q <= '0;
            sel_q <= '0;
        end else if (!active) begin
            if (m_cyc && m_stb) begin
                active <= 1'b1;
                selection <= decoded_selection;
                instr_q <= m_instr;
                we_q <= m_we;
                adr_q <= m_adr;
                dat_w_q <= m_dat_w;
                sel_q <= m_sel;
            end
        end else if (response) begin
            active <= 1'b0;
        end
    end

    always_comb begin
        imem_cyc = 1'b0; imem_stb = 1'b0;
        uart_cyc = 1'b0; uart_stb = 1'b0;
        gpio_cyc = 1'b0; gpio_stb = 1'b0;
        dmem_cyc = 1'b0; dmem_stb = 1'b0;
        imem_we = we_q; uart_we = we_q; gpio_we = we_q; dmem_we = we_q;
        imem_adr = adr_q; uart_adr = adr_q; gpio_adr = adr_q; dmem_adr = adr_q;
        imem_dat_w = dat_w_q; uart_dat_w = dat_w_q;
        gpio_dat_w = dat_w_q; dmem_dat_w = dat_w_q;
        imem_sel = sel_q; uart_sel = sel_q; gpio_sel = sel_q; dmem_sel = sel_q;
        m_ack = 1'b0;
        m_err = 1'b0;
        m_dat_r = '0;

        if (active) begin
            case (selection)
                SEL_IMEM: begin
                    imem_cyc = 1'b1; imem_stb = 1'b1;
                    m_ack = imem_ack; m_err = imem_err; m_dat_r = imem_dat_r;
                end
                SEL_UART: begin
                    uart_cyc = 1'b1; uart_stb = 1'b1;
                    m_ack = uart_ack; m_err = uart_err; m_dat_r = uart_dat_r;
                end
                SEL_GPIO: begin
                    gpio_cyc = 1'b1; gpio_stb = 1'b1;
                    m_ack = gpio_ack; m_err = gpio_err; m_dat_r = gpio_dat_r;
                end
                SEL_DMEM: begin
                    dmem_cyc = 1'b1; dmem_stb = 1'b1;
                    m_ack = dmem_ack; m_err = dmem_err; m_dat_r = dmem_dat_r;
                end
                default: m_err = 1'b1;
            endcase
        end

        if (m_err)
            m_dat_r = '0;
    end

    assign response = m_ack || m_err;

    initial begin
        if (!(IMEM_BASE <= IMEM_LAST && UART_BASE <= UART_LAST
              && GPIO_BASE <= GPIO_LAST && DMEM_BASE <= DMEM_LAST
              && IMEM_LAST < UART_BASE && UART_LAST < GPIO_BASE
              && GPIO_LAST < DMEM_BASE))
            $fatal(1, "Wishbone address regions overlap");
    end

`ifndef SYNTHESIS
    a_slave_onehot: assert property (@(posedge clk) disable iff (rst)
        $onehot0({imem_cyc, uart_cyc, gpio_cyc, dmem_cyc}));
    a_instruction_permission: assert property (@(posedge clk) disable iff (rst)
        active && instr_q |-> !(uart_cyc || gpio_cyc || dmem_cyc));
    a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
        !(m_ack && m_err));
    a_request_stable: assert property (@(posedge clk) disable iff (rst)
        active && !response
        |=> $stable({selection, instr_q, adr_q, we_q, sel_q, dat_w_q}));
`endif
endmodule

`default_nettype wire
