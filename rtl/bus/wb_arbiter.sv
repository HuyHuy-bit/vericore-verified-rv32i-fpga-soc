`default_nettype none

module wb_arbiter (
    input  var logic clk,
    input  var logic rst,
    input  var logic i_cyc,
    input  var logic i_stb,
    input  var logic i_we,
    input  var logic [31:0] i_adr,
    input  var logic [31:0] i_dat_w,
    input  var logic [3:0] i_sel,
    output var logic i_ack,
    output var logic i_err,
    output var logic [31:0] i_dat_r,
    input  var logic d_cyc,
    input  var logic d_stb,
    input  var logic d_we,
    input  var logic [31:0] d_adr,
    input  var logic [31:0] d_dat_w,
    input  var logic [3:0] d_sel,
    output var logic d_ack,
    output var logic d_err,
    output var logic [31:0] d_dat_r,
    output var logic s_cyc,
    output var logic s_stb,
    output var logic s_we,
    output var logic [31:0] s_adr,
    output var logic [31:0] s_dat_w,
    output var logic [3:0] s_sel,
    input  var logic s_ack,
    input  var logic s_err,
    input  var logic [31:0] s_dat_r,
    output var logic s_instr
);
    typedef enum logic [1:0] {NONE, INSTR, DATA} owner_t;
    owner_t owner, next_owner, last_contested;

    always_comb begin
        if (i_cyc && d_cyc)
            next_owner = last_contested == INSTR ? DATA : INSTR;
        else if (d_cyc)
            next_owner = DATA;
        else if (i_cyc)
            next_owner = INSTR;
        else
            next_owner = NONE;
    end

    always_ff @(posedge clk) begin
        if (rst) begin
            owner <= NONE;
            last_contested <= DATA;
        end else if (owner == NONE) begin
            owner <= next_owner;
            if (i_cyc && d_cyc)
                last_contested <= next_owner;
        end else if (s_ack || s_err) begin
            owner <= NONE;
        end
    end

    always_comb begin
        s_cyc = 1'b0;
        s_stb = 1'b0;
        s_we = 1'b0;
        s_adr = '0;
        s_dat_w = '0;
        s_sel = '0;
        s_instr = 1'b0;
        i_ack = 1'b0;
        i_err = 1'b0;
        i_dat_r = '0;
        d_ack = 1'b0;
        d_err = 1'b0;
        d_dat_r = '0;

        case (owner)
            INSTR: begin
                s_cyc = i_cyc;
                s_stb = i_stb;
                s_we = i_we;
                s_adr = i_adr;
                s_dat_w = i_dat_w;
                s_sel = i_sel;
                s_instr = 1'b1;
                i_ack = s_ack;
                i_err = s_err;
                i_dat_r = s_dat_r;
            end
            DATA: begin
                s_cyc = d_cyc;
                s_stb = d_stb;
                s_we = d_we;
                s_adr = d_adr;
                s_dat_w = d_dat_w;
                s_sel = d_sel;
                d_ack = s_ack;
                d_err = s_err;
                d_dat_r = s_dat_r;
            end
            default: ;
        endcase
    end

`ifndef SYNTHESIS
    a_owner_stable: assert property (@(posedge clk) disable iff (rst)
        owner != NONE && !(s_ack || s_err) |=> $stable(owner));
    a_response_onehot: assert property (@(posedge clk) disable iff (rst)
        $onehot0({i_ack, i_err, d_ack, d_err}));
    a_instr_contested_fair: assert property (@(posedge clk) disable iff (rst)
        owner == NONE && i_cyc && d_cyc && last_contested == DATA |=> owner == INSTR);
    a_data_contested_fair: assert property (@(posedge clk) disable iff (rst)
        owner == NONE && i_cyc && d_cyc && last_contested == INSTR |=> owner == DATA);
    a_contested_history: assert property (@(posedge clk) disable iff (rst)
        owner == NONE && i_cyc && d_cyc
        |=> last_contested == $past(next_owner));
    a_uncontested_history: assert property (@(posedge clk) disable iff (rst)
        owner == NONE && !(i_cyc && d_cyc) |=> $stable(last_contested));
`endif
endmodule

`default_nettype wire
