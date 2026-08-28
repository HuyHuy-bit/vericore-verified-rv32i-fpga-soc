// lsu.sv - subword load/store handling.
//
// The boundary between two vocabularies. Above it: RISC-V lb/lh/lw/lbu/lhu and
// sb/sh/sw, with sign extension and unaligned-within-a-word offsets. Below it:
// whole words plus a 4-bit byte enable, which is all a memory or a cache needs
// to understand.
//
// This used to live inside data_mem, which was fine while data_mem was the only
// thing loads and stores could reach. A cache in front of it would have needed
// its own copy of exactly this logic, so it moved out here instead.
`default_nettype none

import rv32i_pkg::*;

module lsu (
    input  var logic [2:0]  funct3,       // access size + signedness
    input  var logic [XOFFW-1:0] byte_off, // low address bits within a data word
    input  var logic        mem_write,
    input  var logic        mem_read,
    input  var logic [XLEN-1:0] store_data,   // rs2, not yet shifted into its lane
    input  var logic [XLEN-1:0] mem_word,     // word coming back from cache/memory

    output var logic [XBYTES-1:0] byte_en,      // which lanes a store touches
    output var logic [XLEN-1:0] store_word,   // store_data shifted into its lane
    output var logic [XLEN-1:0] load_data     // extracted and extended
);
    // funct3 size encodings (F3_LB/F3_LH/F3_LW/F3_LBU/F3_LHU) live in
    // rv32i_pkg.sv now — was a local copy, same duplication problem the
    // package exists to solve.

    // STORE: byte-enable generation.
    // byte_en[i] = 1 means lane i (bits [8i+7 : 8i]) gets written.
    always_comb begin
        byte_en = '0;
        if (mem_write) begin
            // Lane masks are built from the access width, not written out as
            // 4-bit literals: at XLEN=64 a word store covers 4 of 8 lanes and
            // must be positioned by byte_off, which a constant 4'b1111 can't
            // express.
            case (funct3)
                F3_LB:   byte_en = XBYTES'(1)  << byte_off;   // sb:  one lane
                F3_LH:   byte_en = XBYTES'(3)  << byte_off;   // sh:  two lanes
                F3_LW:   byte_en = XBYTES'(15) << byte_off;   // sw:  four lanes
                default: byte_en = '0;
            endcase
        end
    end

    // Align the store value so its low byte/half lands in the addressed lane.
    assign store_word = store_data << (8 * byte_off);

    // LOAD: extract the addressed lane and extend.
    // Each lane is selected by masking byte_off down to that width's
    // alignment, rather than by an explicit mux over 32 bits.
    logic [7:0]  sel_byte;
    logic [15:0] sel_half;
    logic [31:0] sel_word;   // deliberately 32: a "word" is 32 bits at any XLEN
    // 32'() casts keep the shifts at a defined width; byte_off is only
    // XOFFW bits (2 at XLEN=32) and would otherwise self-determine.
    assign sel_byte = mem_word[8  * 32'(byte_off)        +: 8];
    assign sel_half = mem_word[16 * (32'(byte_off) >> 1) +: 16];
    assign sel_word = mem_word[32 * (32'(byte_off) >> 2) +: 32];

    always_comb begin
        if (mem_read) begin
            case (funct3)
                // Signed casts rather than {{24{...}}, ...} replication: the
                // replication count is a function of XLEN, and spelling it as
                // a literal is exactly what pins a datapath to one width.
                // Note LW sign-extends, which is identity at XLEN=32 and the
                // architecturally correct behaviour at XLEN=64.
                F3_LB:   load_data = XLEN'($signed(sel_byte));
                F3_LH:   load_data = XLEN'($signed(sel_half));
                F3_LW:   load_data = XLEN'($signed(sel_word));
                F3_LBU:  load_data = XLEN'($unsigned(sel_byte));
                F3_LHU:  load_data = XLEN'($unsigned(sel_half));
                default: load_data = mem_word;
            endcase
        end else begin
            load_data = XLEN'(0);
        end
    end
endmodule

`default_nettype wire
