`default_nettype none

module hazard_detect (
    input  var logic       mem_read_ex,   // instruction currently in EX is a load
    input  var logic [4:0] rd_addr_ex,    // its destination register

    input  var logic [4:0] rs1_addr_id,   // instruction currently in ID's operands
    input  var logic [4:0] rs2_addr_id,
    input  var logic       uses_rs1_id,
    input  var logic       uses_rs2_id,

    output var logic       stall          // 1 = insert one bubble
);
    always_comb begin
        stall = mem_read_ex &&
                (rd_addr_ex != 5'd0) &&
                ((uses_rs1_id && (rd_addr_ex == rs1_addr_id)) ||
                 (uses_rs2_id && (rd_addr_ex == rs2_addr_id)));
    end

`ifndef SYNTHESIS
    // The pipeline registers clear mem_read_ex on reset and bubble insertion,
    // so it remains the producer-valid qualification. Ignore unknown startup
    // inputs here; every fully binary state must satisfy both directions.
    always_comb begin
        if (!$isunknown({mem_read_ex, rd_addr_ex, rs1_addr_id, rs2_addr_id,
                         uses_rs1_id, uses_rs2_id, stall})) begin
            a_stall_sound: assert (!stall ||
                (mem_read_ex && (rd_addr_ex != 5'd0) &&
                 ((uses_rs1_id && (rd_addr_ex == rs1_addr_id)) ||
                  (uses_rs2_id && (rd_addr_ex == rs2_addr_id)))));
            a_stall_complete: assert (
                !(mem_read_ex && (rd_addr_ex != 5'd0) &&
                  ((uses_rs1_id && (rd_addr_ex == rs1_addr_id)) ||
                   (uses_rs2_id && (rd_addr_ex == rs2_addr_id)))) || stall);
        end
    end
`endif
endmodule

`default_nettype wire
