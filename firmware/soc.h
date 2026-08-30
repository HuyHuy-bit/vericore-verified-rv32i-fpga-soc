#ifndef RV32I_SOC_H
#define RV32I_SOC_H

#include <stdint.h>

#define MMIO32(address) (*(volatile uint32_t *)(uintptr_t)(address))

#define UART_TXDATA MMIO32(0x10000000u)
#define UART_STATUS MMIO32(0x10000004u)
#define GPIO_LED MMIO32(0x10001000u)
#define GPIO_BUTTON MMIO32(0x10001004u)
#define GPIO_IRQ_PENDING MMIO32(0x10001008u)
#define GPIO_IRQ_ENABLE MMIO32(0x1000100cu)

#define UART_STATUS_TX_READY (1u << 0)
#define MSTATUS_MIE (1u << 3)
#define MIE_MEIE (1u << 11)
#define MCAUSE_INTERRUPT (1u << 31)
#define MCAUSE_EXTERNAL 11u

#define csr_read(csr)                                                        \
    ({                                                                       \
        uint32_t value;                                                      \
        __asm__ volatile("csrr %0, " #csr : "=r"(value));                  \
        value;                                                               \
    })
#define csr_write(csr, value)                                                \
    __asm__ volatile("csrw " #csr ", %0" : : "rK"((uint32_t)(value)) : "memory")
#define csr_set(csr, value)                                                  \
    __asm__ volatile("csrs " #csr ", %0" : : "rK"((uint32_t)(value)) : "memory")
#define csr_clear(csr, value)                                                \
    __asm__ volatile("csrc " #csr ", %0" : : "rK"((uint32_t)(value)) : "memory")

static inline void csrsi_mstatus_mie(void) {
    __asm__ volatile("csrsi mstatus, 8" : : : "memory");
}

void uart_putc(char value);
void uart_puts(const char *text);
void trap_handler_c(uint32_t cause);

#endif
