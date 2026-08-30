`default_nettype none

module uart_tx #(
    parameter int unsigned CLOCK_HZ = 100_000_000,
    parameter int unsigned UART_BAUD = 115_200
) (
    input  var logic clk,
    input  var logic rst,
    input  var logic valid,
    input  var logic [7:0] data,
    output var logic ready,
    output var logic tx
);
    localparam int unsigned DIVISOR = UART_BAUD == 0 ? 0
        : (CLOCK_HZ + UART_BAUD / 2) / UART_BAUD;
    localparam int DIV_W = DIVISOR <= 1 ? 1 : $clog2(DIVISOR);
    localparam longint unsigned CLOCK_HZ_LONG = longint'(CLOCK_HZ);
    localparam longint unsigned UART_BAUD_LONG = longint'(UART_BAUD);
    localparam longint unsigned DIVISOR_LONG = longint'(DIVISOR);
    localparam longint unsigned TARGET_CLOCKS = UART_BAUD_LONG * DIVISOR_LONG;
    localparam longint unsigned CLOCK_ERROR = CLOCK_HZ_LONG > TARGET_CLOCKS
        ? CLOCK_HZ_LONG - TARGET_CLOCKS : TARGET_CLOCKS - CLOCK_HZ_LONG;
    localparam logic [DIV_W-1:0] DIVISOR_LAST = DIV_W'(DIVISOR - 1);

    logic [9:0] frame;
    logic [3:0] bit_index;
    logic [DIV_W-1:0] divider_count;
    logic busy;

    assign ready = !busy;
    assign tx = busy ? frame[bit_index] : 1'b1;

    initial begin
        if (CLOCK_HZ == 0 || UART_BAUD == 0 || DIVISOR == 0)
            $fatal(1, "uart_tx: invalid clock or baud rate");
        if (CLOCK_ERROR * 100 > TARGET_CLOCKS * 2)
            $fatal(1, "uart_tx: baud-rate error exceeds two percent");
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            frame <= '0;
            bit_index <= '0;
            divider_count <= '0;
            busy <= 1'b0;
        end else if (!busy) begin
            if (valid) begin
                frame <= {1'b1, data, 1'b0};
                bit_index <= '0;
                divider_count <= '0;
                busy <= 1'b1;
            end
        end else if (divider_count == DIVISOR_LAST) begin
            divider_count <= '0;
            if (bit_index == 9) begin
                bit_index <= '0;
                busy <= 1'b0;
            end else begin
                bit_index <= bit_index + 1'b1;
            end
        end else begin
            divider_count <= divider_count + 1'b1;
        end
    end
endmodule

`default_nettype wire
