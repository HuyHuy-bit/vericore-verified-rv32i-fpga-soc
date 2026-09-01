`default_nettype none

module wb_uart #(
    parameter int unsigned CLOCK_HZ = 100_000_000,
    parameter int unsigned UART_BAUD = 115_200
) (
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
    output var logic tx,
    output var logic tx_ready
);
    localparam logic [31:0] TXDATA_ADDR = 32'h1000_0000;
    localparam logic [31:0] STATUS_ADDR = 32'h1000_0004;

    typedef enum logic [1:0] {IDLE, WAIT_TX, HOLD} state_t;
    state_t state;
    logic [7:0] tx_data;
    logic tx_valid;
    logic unused;

    uart_tx #(
        .CLOCK_HZ(CLOCK_HZ),
        .UART_BAUD(UART_BAUD)
    ) transmitter (
        .clk(clk),
        .rst(rst),
        .valid(tx_valid),
        .data(tx_data),
        .ready(tx_ready),
        .tx(tx)
    );

    assign tx_valid = state == WAIT_TX && tx_ready;
    assign unused = &{1'b0, wb_dat_w[31:8], wb_sel[3:1]};

    always_ff @(posedge clk) begin
        if (rst) begin
            state <= IDLE;
            tx_data <= '0;
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;
        end else begin
            wb_ack <= 1'b0;
            wb_err <= 1'b0;
            wb_dat_r <= '0;
            case (state)
                IDLE: begin
                    if (wb_cyc && wb_stb) begin
                        if (wb_adr[1:0] != 2'b00) begin
                            wb_err <= 1'b1;
                            state <= HOLD;
                        end else if (wb_adr == TXDATA_ADDR) begin
                            if (!wb_we) begin
                                wb_ack <= 1'b1;
                                state <= HOLD;
                            end else if (!wb_sel[0]) begin
                                wb_err <= 1'b1;
                                state <= HOLD;
                            end else begin
                                tx_data <= wb_dat_w[7:0];
                                state <= WAIT_TX;
                            end
                        end else if (wb_adr == STATUS_ADDR) begin
                            if (wb_we) begin
                                wb_err <= 1'b1;
                            end else begin
                                wb_ack <= 1'b1;
                                wb_dat_r <= {31'b0, tx_ready};
                            end
                            state <= HOLD;
                        end else begin
                            wb_err <= 1'b1;
                            state <= HOLD;
                        end
                    end
                end
                WAIT_TX: begin
                    if (tx_ready) begin
                        wb_ack <= 1'b1;
                        state <= HOLD;
                    end
                end
                HOLD: begin
                    if (!(wb_cyc && wb_stb))
                        state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end

`ifndef SYNTHESIS
    a_response_exclusive: assert property (@(posedge clk) disable iff (rst)
        !(wb_ack && wb_err));
`endif
endmodule

`default_nettype wire
