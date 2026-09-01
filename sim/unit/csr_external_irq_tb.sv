`default_nettype none

import rv32i_pkg::*;

module csr_external_irq;
    logic clk = 1'b0;
    logic rst;
    logic csr_access;
    logic [11:0] csr_addr;
    logic [2:0] csr_funct3;
    logic [XLEN-1:0] csr_wdata;
    logic [XLEN-1:0] csr_rdata;
    logic [XLEN-1:0] cycle_count;
    logic [XLEN-1:0] instret_count;
    logic trap_en;
    logic [XLEN-1:0] trap_pc;
    logic [XLEN-1:0] trap_cause;
    logic [XLEN-1:0] trap_val;
    logic [XLEN-1:0] mtvec_out;
    logic mret_en;
    logic [XLEN-1:0] mepc_out;
    logic irq_external;
    logic irq_pending;
    logic [XLEN-1:0] irq_cause;

    always #1 clk = ~clk;

    csr dut (
        .clk(clk),
        .rst(rst),
        .csr_access(csr_access),
        .csr_addr(csr_addr),
        .csr_funct3(csr_funct3),
        .csr_wdata(csr_wdata),
        .csr_rdata(csr_rdata),
        .cycle_count(cycle_count),
        .instret_count(instret_count),
        .trap_en(trap_en),
        .trap_pc(trap_pc),
        .trap_cause(trap_cause),
        .trap_val(trap_val),
        .mtvec_out(mtvec_out),
        .mret_en(mret_en),
        .mepc_out(mepc_out),
        .irq_external(irq_external),
        .irq_pending(irq_pending),
        .irq_cause(irq_cause)
    );

    task automatic write_csr(input logic [11:0] addr,
                             input logic [XLEN-1:0] value);
        begin
            @(negedge clk);
            csr_addr = addr;
            csr_wdata = value;
            csr_access = 1'b1;
            @(posedge clk);
            @(negedge clk);
            csr_access = 1'b0;
        end
    endtask

    task automatic expect_irq(input logic pending,
                              input logic [XLEN-1:0] cause,
                              input string label);
        begin
            #1;
            if (irq_pending !== pending)
                $fatal(1, "%s pending=%b want=%b", label, irq_pending, pending);
            if (pending && irq_cause !== cause)
                $fatal(1, "%s cause=%08x want=%08x", label, irq_cause, cause);
        end
    endtask

    initial begin
        rst = 1'b1;
        csr_access = 1'b0;
        csr_addr = '0;
        csr_funct3 = F3_CSRRW;
        csr_wdata = '0;
        cycle_count = '0;
        instret_count = '0;
        trap_en = 1'b0;
        trap_pc = '0;
        trap_cause = '0;
        trap_val = '0;
        mret_en = 1'b0;
        irq_external = 1'b0;

        repeat (2) @(posedge clk);
        @(negedge clk);
        rst = 1'b0;

        write_csr(CSR_MIE, XLEN'('h888));
        write_csr(CSR_MSTATUS, XLEN'('h8));
        irq_external = 1'b1;
        expect_irq(1'b1, CAUSE_IRQ_EXTERNAL, "external enabled");

        csr_addr = CSR_MIP;
        #1;
        if (!csr_rdata[IRQ_E_BIT]) $fatal(1, "MEIP does not reflect input");

        write_csr(CSR_MSTATUS, XLEN'(0));
        expect_irq(1'b0, '0, "global disabled");
        write_csr(CSR_MSTATUS, XLEN'('h8));
        write_csr(CSR_MIE, XLEN'('h88));
        expect_irq(1'b0, '0, "MEIE disabled");
        write_csr(CSR_MIE, XLEN'('h888));

        write_csr(CSR_MIP, XLEN'('h8));
        write_csr(CSR_MTIMECMP, XLEN'(0));
        repeat (2) @(posedge clk);
        expect_irq(1'b1, CAUSE_IRQ_EXTERNAL, "external priority");
        irq_external = 1'b0;
        expect_irq(1'b1, CAUSE_IRQ_SOFT, "software priority");
        write_csr(CSR_MIP, XLEN'(0));
        expect_irq(1'b1, CAUSE_IRQ_TIMER, "timer priority");

        irq_external = 1'b1;
        write_csr(CSR_MIE, XLEN'(1 << IRQ_E_BIT));
        expect_irq(1'b1, CAUSE_IRQ_EXTERNAL, "external before trap");
        @(negedge clk);
        trap_cause = CAUSE_IRQ_EXTERNAL;
        trap_en = 1'b1;
        @(posedge clk);
        @(negedge clk);
        trap_en = 1'b0;
        expect_irq(1'b0, '0, "trap disables interrupts");

        mret_en = 1'b1;
        @(posedge clk);
        @(negedge clk);
        mret_en = 1'b0;
        expect_irq(1'b1, CAUSE_IRQ_EXTERNAL, "MRET restores interrupts");

        irq_external = 1'b0;
        write_csr(CSR_MIP, XLEN'(1 << IRQ_E_BIT));
        csr_addr = CSR_MIP;
        #1;
        if (csr_rdata[IRQ_E_BIT]) $fatal(1, "MEIP became software writable");

        $display("PASS machine-external interrupt CSR behavior");
        $finish;
    end

    initial begin
        repeat (200) @(posedge clk);
        $fatal(1, "timeout");
    end
endmodule

`default_nettype wire
