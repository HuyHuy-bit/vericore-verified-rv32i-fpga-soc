`default_nettype none

module wb_gpio_irq (
    input  var logic clk,
    input  var logic rst,
    input  var logic wb_cyc,
    input  var logic wb_stb,
    input  var logic wb_we,
    input  var logic [31:0] wb_adr,
    input  var logic [31:0] wb_dat_w,
    input  var logic [3:0] wb_sel,
    output var logic wb_ack,
    output var logic wb_err,
    output var logic [31:0] wb_dat_r,
    input  var logic button_state,
    input  var logic button_rise,
    output var logic [3:0] led,
    output var logic irq_external
);
    localparam logic [31:0] LED_ADDR = 32'h1000_1000;
    localparam logic [31:0] BUTTON_ADDR = 32'h1000_1004;
    localparam logic [31:0] PENDING_ADDR = 32'h1000_1008;
    localparam logic [31:0] ENABLE_ADDR = 32'h1000_100c;

    typedef enum logic {IDLE, HOLD} state_t;
    state_t state;
    logic irq_pending;
    logic irq_enable;
    logic clear_pending;
    logic unused;

    assign irq_external = irq_pending && irq_enable;
    assign clear_pending = state == IDLE && wb_cyc && wb_stb && wb_we
        && wb_adr == PENDING_ADDR && wb_adr[1:0] == 2'b00
        && wb_sel[0] && wb_dat_w[0];
    assign unused = &{1'b0, wb_dat_w[31:4], wb_sel[3:1]};

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            led <= '0;
            irq_pending <= 1'b0;
            irq_enable <= 1'b0;
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;
        end else begin
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;

            if (button_rise)
                irq_pending <= 1'b1;
            else if (clear_pending)
                irq_pending <= 1'b0;

            case (state)
                IDLE: begin
                    if (wb_cyc && wb_stb) begin
                        state <= HOLD;
                        if (wb_adr[1:0] != 2'b00) begin
                            wb_err <= 1'b1;
                        end else begin
                            case (wb_adr)
                                LED_ADDR: begin
                                    wb_ack <= 1'b1;
                                    if (wb_we && wb_sel[0])
                                        led <= wb_dat_w[3:0];
                                    else if (!wb_we)
                                        wb_dat_r <= {28'b0, led};
                                end
                                BUTTON_ADDR: begin
                                    if (wb_we) begin
                                        wb_err <= 1'b1;
                                    end else begin
                                        wb_ack <= 1'b1;
                                        wb_dat_r <= {31'b0, button_state};
                                    end
                                end
                                PENDING_ADDR: begin
                                    wb_ack <= 1'b1;
                                    if (!wb_we)
                                        wb_dat_r <= {31'b0, irq_pending};
                                end
                                ENABLE_ADDR: begin
                                    wb_ack <= 1'b1;
                                    if (wb_we && wb_sel[0])
                                        irq_enable <= wb_dat_w[0];
                                    else if (!wb_we)
                                        wb_dat_r <= {31'b0, irq_enable};
                                end
                                default: wb_err <= 1'b1;
                            endcase
                        end
                    end
                end
                HOLD: begin
                    if (!(wb_cyc && wb_stb))
                        state <= IDLE;
                end
            endcase
        end
    end

`ifndef SYNTHESIS
    a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
        !(wb_ack && wb_err));
    a_irq_gated: assert property (@(posedge clk) disable iff (rst)
        irq_external |-> irq_enable);
`endif
endmodule

`default_nettype wire
