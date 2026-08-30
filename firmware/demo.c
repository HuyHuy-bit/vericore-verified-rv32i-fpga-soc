#include "soc.h"

volatile uint32_t main_loop_progress;
volatile uint32_t irq_count;

void uart_putc(char value) {
    while ((UART_STATUS & UART_STATUS_TX_READY) == 0u) {
    }
    UART_TXDATA = (uint32_t)(uint8_t)value;
}

void uart_puts(const char *text) {
    while (*text != '\0') {
        uart_putc(*text);
        ++text;
    }
}

void trap_handler_c(uint32_t cause) {
    if ((cause & 0x8000000fu) == (MCAUSE_INTERRUPT | MCAUSE_EXTERNAL)) {
        uint32_t value;
        GPIO_IRQ_PENDING = 1u;
        value = GPIO_LED & 0xfu;
        value = value == 0u ? 1u : ((value << 1) | (value >> 3)) & 0xfu;
        GPIO_LED = value;
        ++irq_count;
        uart_puts("external irq\n");
        return;
    }

    csr_clear(mstatus, MSTATUS_MIE);
    GPIO_LED = 0xfu;
    uart_puts("unexpected trap\n");
    for (;;) {
    }
}

int main(void) {
    GPIO_IRQ_PENDING = 1u;
    GPIO_LED = 1u;
    GPIO_IRQ_ENABLE = 1u;
    csr_set(mie, MIE_MEIE);
    csrsi_mstatus_mie();
    uart_puts("rv32i soc ready\n");
    for (;;) {
        ++main_loop_progress;
    }
}
