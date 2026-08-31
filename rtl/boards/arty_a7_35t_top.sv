`default_nettype none

module arty_a7_35t_top #(
    parameter string IMEM_INIT_FILE = "firmware-imem.hex",
    parameter string DMEM_INIT_FILE = "firmware-dmem.hex"
) (
    input  var logic       clk100,
    input  var logic [1:0] btn,
    output var logic [3:0] led,
    output var logic       uart_tx
);
    logic rst;
    logic bus_fault;
    logic retired_debug;
    logic [31:0] progress_debug;
    logic reset_button;
    logic irq_button;

    assign reset_button = btn[0];
    assign irq_button = btn[1];

    reset_controller #(
        .POWER_ON_CYCLES(16)
    ) reset (
        .clk(clk100),
        .async_reset(reset_button),
        .rst(rst)
    );

    rv32i_soc #(
        .CLOCK_HZ(100_000_000),
        .UART_BAUD(115_200),
        .DEBOUNCE_CYCLES(1_000_000),
        .ICACHE_BYTES(1024),
        .ICACHE_BLOCK_WORDS(4),
        .ICACHE_WAYS(4),
        .DCACHE_BYTES(4096),
        .DCACHE_BLOCK_WORDS(4),
        .DCACHE_WAYS(4),
        .DCACHE_WRITE_BACK(1),
        .IMEM_DEPTH_WORDS(8192),
        .DMEM_DEPTH_WORDS(8192),
        .IMEM_INIT_FILE(IMEM_INIT_FILE),
        .DMEM_INIT_FILE(DMEM_INIT_FILE)
    ) soc (
        .clk(clk100),
        .rst(rst),
        .button_irq(irq_button),
        .led(led),
        .uart_tx(uart_tx),
        .bus_fault(bus_fault),
        .retired_debug(retired_debug),
        .progress_debug(progress_debug)
    );

    logic unused;
    assign unused = &{1'b0, bus_fault, retired_debug, progress_debug};
endmodule

`default_nettype wire
