`default_nettype none

module hazard_detect_tb;
    logic       mem_read_ex;
    logic [4:0] rd_addr_ex;
    logic [4:0] rs1_addr_id;
    logic [4:0] rs2_addr_id;
    logic       uses_rs1_id;
    logic       uses_rs2_id;
    logic       stall;

    logic [63:0] checks;

    hazard_detect dut (
        .mem_read_ex(mem_read_ex),
        .rd_addr_ex(rd_addr_ex),
        .rs1_addr_id(rs1_addr_id),
        .rs2_addr_id(rs2_addr_id),
        .uses_rs1_id(uses_rs1_id),
        .uses_rs2_id(uses_rs2_id),
        .stall(stall)
    );

    initial begin
        logic expected;

        checks = 0;

        // Start with a live nonzero load and unused raw fields so the legacy
        // raw-field detector reaches the intended RED mismatch immediately.
        for (int load_idx = 1; load_idx >= 0; load_idx--) begin
            for (int rd_idx = 1; rd_idx <= 32; rd_idx++) begin
                for (int rs1_idx = 0; rs1_idx < 32; rs1_idx++) begin
                    for (int rs2_idx = 0; rs2_idx < 32; rs2_idx++) begin
                        for (int use_mask = 0; use_mask < 4; use_mask++) begin
                            mem_read_ex = 1'(load_idx);
                            rd_addr_ex  = 5'(rd_idx);
                            rs1_addr_id = 5'(rs1_idx);
                            rs2_addr_id = 5'(rs2_idx);
                            uses_rs1_id = use_mask[0];
                            uses_rs2_id = use_mask[1];
                            #1;

                            expected = mem_read_ex && rd_addr_ex != 5'd0 &&
                                       ((uses_rs1_id && rd_addr_ex == rs1_addr_id) ||
                                        (uses_rs2_id && rd_addr_ex == rs2_addr_id));
                            checks = checks + 64'd1;

                            if (stall !== expected) begin
                                $display("FAIL hazard check=%0d mem_read_ex=%b rd=%0d rs1=%0d rs2=%0d uses_rs1=%b uses_rs2=%b got=%b want=%b",
                                         checks, mem_read_ex, rd_addr_ex,
                                         rs1_addr_id, rs2_addr_id,
                                         uses_rs1_id, uses_rs2_id,
                                         stall, expected);
                                $fatal(1, "hazard unit stopped at first mismatch");
                            end
                        end
                    end
                end
            end
        end

        $display("PASS hazard: 262144 vectors");
        $finish;
    end
endmodule

`default_nettype wire
