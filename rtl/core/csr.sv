// csr.sv - minimal M-mode control/status registers.
`default_nettype none

import rv32i_pkg::*;

module csr (
    input  var logic        clk,
    input  var logic        rst,

    // ---- CSR-instruction access (resolved at commit point in MEM) ----
    input  var logic        csr_access,   // 1 = a CSR instruction is committing
    input  var logic [11:0] csr_addr,     // which CSR (instr[31:20])
    input  var logic [2:0]  csr_funct3,   // CSRRW/S/C / immediate variant
    input  var logic [XLEN-1:0] csr_wdata,    // rs1 value or zero-extended uimm
    output var logic [XLEN-1:0] csr_rdata,    // old value -> written back to rd

    // ---- read-only counters, mirrored into mcycle/minstret ----
    input  var logic [XLEN-1:0] cycle_count,
    input  var logic [XLEN-1:0] instret_count,

    // ---- trap entry (asserted for one cycle when a trap commits) ----
    input  var logic        trap_en,
    input  var logic [XLEN-1:0] trap_pc,      // faulting instruction's PC -> mepc
    input  var logic [XLEN-1:0] trap_cause,   // -> mcause
    input  var logic [XLEN-1:0] trap_val,     // -> mtval (faulting addr/instr, if any)
    output var logic [XLEN-1:0] mtvec_out,    // handler base -> PC redirect target

    // ---- MRET (asserted for one cycle when an MRET commits) ----
    input  var logic        mret_en,
    output var logic [XLEN-1:0] mepc_out,     // return address -> PC redirect target

    // ---- interrupts ----
    // irq_pending is the architectural "an interrupt is ready to be taken"
    // condition: enabled globally (mstatus.MIE), enabled individually (mie),
    // and actually asserted (mip). The commit point decides *when* to act on
    // it; this module only says whether it is true.
    // No "acknowledge" input: MTIP is a live comparison cleared by writing
    // mtimecmp, and MSIP is set and cleared by software through mip. Neither
    // needs the commit point to tell it the interrupt was taken.
    output var logic        irq_pending,
    output var logic [XLEN-1:0] irq_cause
);
    logic [XLEN-1:0] mtvec, mepc, mcause, mscratch, mtval;

    // mstatus: only MIE/MPIE/MPP are implemented. MPP is hardwired to M
    // (2'b11) because this core has no U mode to return to.
    logic mstatus_mie, mstatus_mpie;
    logic [XLEN-1:0] mstatus_val;
    always_comb begin
        mstatus_val = XLEN'(0);
        mstatus_val[MSTATUS_MIE_BIT]           = mstatus_mie;
        mstatus_val[MSTATUS_MPIE_BIT]          = mstatus_mpie;
        mstatus_val[MSTATUS_MPP_LSB +: 2]      = 2'b11;   // MPP = M, always
    end

    // mie / mip. Only software and timer are implemented; the external bit
    // reads 0 because nothing drives it.
    logic mie_msie, mie_mtie;
    logic mip_msip;                 // software interrupt: set by software
    logic [XLEN-1:0] mie_val, mip_val;

    // Timer. mtime free-runs; MTIP is a comparison against it, not a stored
    // bit, exactly as the spec defines it - which is why writing mtimecmp is
    // what clears the interrupt, and there is no "acknowledge" path.
    //
    // The comparison itself is registered rather than combinational. A 64-bit
    // magnitude compare recomputed unconditionally every cycle is a full-width
    // carry chain, and left combinational it sat on the same-cycle path all
    // the way through irq_pending/irq_take to the PC redirect mux - measured
    // as the design's actual worst path post-route (~75MHz, dominated by this
    // comparator). Registering it costs one cycle of interrupt-recognition
    // latency, which is free to spend: RISC-V doesn't bound how quickly a
    // pending interrupt must be taken, so this is exactly the registered-mip
    // convention a real timer/CLINT implementation already uses.
    logic [63:0] mtime, mtimecmp;
    logic mip_mtip_next, mip_mtip;
    assign mip_mtip_next = (mtime >= mtimecmp);

    always_comb begin
        mie_val = XLEN'(0);
        mie_val[IRQ_S_BIT] = mie_msie;
        mie_val[IRQ_T_BIT] = mie_mtie;
        mip_val = XLEN'(0);
        mip_val[IRQ_S_BIT] = mip_msip;
        mip_val[IRQ_T_BIT] = mip_mtip;
    end

    // Timer interrupt outranks software when both are ready. Any fixed order
    // is spec-legal; this one matches the usual RISC-V implementation.
    assign irq_pending = mstatus_mie && ((mie_mtie && mip_mtip) || (mie_msie && mip_msip));
    assign irq_cause   = (mie_mtie && mip_mtip) ? CAUSE_IRQ_TIMER : CAUSE_IRQ_SOFT;
    // mcycle/minstret are R/W in M-mode (software may reinitialize them); a
    // write here only offsets the live counter, no separate storage needed,
    // which keeps a write-then-read round trip trivial to reason about.
    logic [XLEN-1:0] mcycle_offset, minstret_offset;
    logic [XLEN-1:0] mcycle_val, minstret_val;
    assign mcycle_val   = cycle_count   + mcycle_offset;
    assign minstret_val = instret_count + minstret_offset;

    assign mtvec_out = mtvec;
    assign mepc_out  = mepc;

    // ---- CSR read (combinational): old value seen by the CSR instruction ----
    always_comb begin
        case (csr_addr)
            CSR_MSTATUS:   csr_rdata = mstatus_val;
            CSR_MIE:       csr_rdata = mie_val;
            CSR_MIP:       csr_rdata = mip_val;
            CSR_MTIME:     csr_rdata = mtime[XLEN-1:0];
            CSR_MTIMECMP:  csr_rdata = mtimecmp[XLEN-1:0];
            CSR_MTVEC:     csr_rdata = mtvec;
            CSR_MEPC:      csr_rdata = mepc;
            CSR_MCAUSE:    csr_rdata = mcause;
            CSR_MSCRATCH:  csr_rdata = mscratch;
            CSR_MTVAL:     csr_rdata = mtval;
            CSR_MISA:      csr_rdata = MISA_VALUE;
            CSR_MVENDORID: csr_rdata = XLEN'(0);
            CSR_MARCHID:   csr_rdata = XLEN'(0);
            CSR_MIMPID:    csr_rdata = XLEN'(0);
            CSR_MHARTID:   csr_rdata = XLEN'(0);
            CSR_MCYCLE:    csr_rdata = mcycle_val;
            CSR_MINSTRET:  csr_rdata = minstret_val;
            CSR_MCYCLEH:   csr_rdata = XLEN'(0); // 32-bit counters: upper half never overflows into
            CSR_MINSTRETH: csr_rdata = XLEN'(0); // in any run this core will see; kept at 0 rather than modeled
            default:       csr_rdata = XLEN'(0); // unimplemented reads trap illegal before this matters
        endcase
    end

    // ---- compute the CSR-instruction write value (RW=swap, RS=set, RC=clear) ----
    logic [XLEN-1:0] csr_new;
    always_comb begin
        unique case (csr_funct3)
            F3_CSRRW, F3_CSRRWI: csr_new = csr_wdata;
            F3_CSRRS, F3_CSRRSI: csr_new = csr_rdata |  csr_wdata;
            F3_CSRRC, F3_CSRRCI: csr_new = csr_rdata & ~csr_wdata;
            default:             csr_new = csr_rdata;
        endcase
    end

    // ---- write path (synchronous) ----
    // Priority: a trap (hardware) takes precedence over a CSR instruction in
    // the same cycle; in practice they never coincide since both resolve at
    // the single commit point one instruction at a time, but the ordering is
    // made explicit for safety.
    always_ff @(posedge clk) begin
        if (rst) begin
            mtvec           <= XLEN'(0);
            mepc            <= XLEN'(0);
            mcause          <= XLEN'(0);
            mscratch        <= XLEN'(0);
            mtval           <= XLEN'(0);
            mcycle_offset   <= XLEN'(0);
            minstret_offset <= XLEN'(0);
            mstatus_mie     <= 1'b0;      // interrupts off out of reset
            mstatus_mpie    <= 1'b0;
            mie_msie        <= 1'b0;
            mie_mtie        <= 1'b0;
            mip_msip        <= 1'b0;
            mtime           <= 64'd0;
            mtimecmp        <= '1;        // never fires until software sets it
            mip_mtip        <= 1'b0;
        end else begin
            // mtime free-runs regardless of everything else below.
            mtime    <= mtime + 64'd1;
            mip_mtip <= mip_mtip_next;

        if (trap_en) begin
            mepc   <= trap_pc;
            mcause <= trap_cause;
            mtval  <= trap_val;
            // Trap entry pushes the interrupt-enable stack: the handler runs
            // with interrupts disabled, and MPIE remembers what MIE was so
            // MRET can restore it. Without this an interrupt handler would be
            // re-entered by its own cause before it could clear it.
            mstatus_mpie <= mstatus_mie;
            mstatus_mie  <= 1'b0;
        end else if (mret_en) begin
            // ...and MRET pops it. MPIE is set to 1 on pop per the spec.
            mstatus_mie  <= mstatus_mpie;
            mstatus_mpie <= 1'b1;
        end else if (csr_access) begin
            // misa/mvendorid/marchid/mimpid/mhartid are WARL-zero (writes
            // silently dropped) or hardware read-only (structural
            // csr_read_only(addr) traps illegal before this ever fires for
            // mvendorid/marchid/mimpid/mhartid — misa alone has no illegal
            // trap since [11:10]!=11, so it needs the explicit no-op here).
            case (csr_addr)
                CSR_MTVEC:    mtvec    <= csr_new;
                CSR_MEPC:     mepc     <= csr_new;
                CSR_MCAUSE:   mcause   <= csr_new;
                CSR_MSCRATCH: mscratch <= csr_new;
                CSR_MTVAL:    mtval    <= csr_new;
                CSR_MCYCLE:   mcycle_offset   <= csr_new - cycle_count;
                CSR_MINSTRET: minstret_offset <= csr_new - instret_count;
                CSR_MSTATUS:  begin
                    mstatus_mie  <= csr_new[MSTATUS_MIE_BIT];
                    mstatus_mpie <= csr_new[MSTATUS_MPIE_BIT];
                end
                CSR_MIE: begin
                    mie_msie <= csr_new[IRQ_S_BIT];
                    mie_mtie <= csr_new[IRQ_T_BIT];
                end
                // MTIP is a comparison and so is read-only; MSIP is the one
                // interrupt software raises and clears directly.
                CSR_MIP:      mip_msip <= csr_new[IRQ_S_BIT];
                // Writing mtimecmp is what acknowledges a timer interrupt.
                CSR_MTIMECMP: mtimecmp <= 64'(csr_new);
                default:      ; // misa, mvendorid/marchid/mimpid/mhartid: read-only
            endcase
        end
        end
    end
endmodule

`default_nettype wire
