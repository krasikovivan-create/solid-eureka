// Exhaustive self-checking test of the PE datapath: all 65536 (a, w) pairs,
// both multiplier implementations (DSP form and LUT shift-add form), both
// weight banks. Prints "PE_TEST errors=<n> checks=<n>".
`timescale 1ns/1ps
module tb_pe;
  localparam int PW = 20;
  logic clk = 1'b0;
  always #5 clk = ~clk;

  logic [7:0]    a_in, w_data;
  logic          s_in, w_we, w_bank;
  logic [PW-1:0] ps_in;
  logic [7:0]    a_out_d, a_out_l;
  logic          s_out_d, s_out_l;
  logic [PW-1:0] ps_out_d, ps_out_l;

  pe #(.PW(PW), .USE_DSP(1'b1)) u_dsp (
    .clk(clk), .a_in(a_in), .s_in(s_in), .a_out(a_out_d), .s_out(s_out_d),
    .ps_in(ps_in), .ps_out(ps_out_d), .w_data(w_data), .w_we(w_we), .w_bank(w_bank));
  pe #(.PW(PW), .USE_DSP(1'b0)) u_lut (
    .clk(clk), .a_in(a_in), .s_in(s_in), .a_out(a_out_l), .s_out(s_out_l),
    .ps_in(ps_in), .ps_out(ps_out_l), .w_data(w_data), .w_we(w_we), .w_bank(w_bank));

  integer errors = 0, checks = 0;
  integer ai, wi, bank, expected;

  initial begin
    w_we = 1'b0; w_bank = 1'b0; s_in = 1'b0; a_in = 8'd0; ps_in = '0; w_data = 8'd0;
    for (wi = -128; wi < 128; wi = wi + 1) begin
      for (bank = 0; bank < 2; bank = bank + 1) begin
        // load weight wi into this bank, the inverted value into the other bank
        @(negedge clk);
        w_we = 1'b1; w_bank = bank[0]; w_data = wi[7:0];
        @(negedge clk);
        w_bank = ~bank[0]; w_data = ~wi[7:0];
        @(negedge clk);
        w_we = 1'b0;
        for (ai = -128; ai < 128; ai = ai + 1) begin
          a_in  = ai[7:0];
          s_in  = bank[0];
          ps_in = PW'(ai * 37 - wi * 1001);       // arbitrary incoming partial sum
          expected = ai * 37 - wi * 1001 + ai * wi;
          // the PE has two register stages (product, then partial sum): hold inputs 2 cycles
          @(posedge clk);
          @(posedge clk);
          #1;
          checks = checks + 1;
          if ($signed(ps_out_d) !== PW'(expected) || $signed(ps_out_l) !== PW'(expected)
              || a_out_d !== ai[7:0] || a_out_l !== ai[7:0] || s_out_d !== bank[0] || s_out_l !== bank[0]) begin
            errors = errors + 1;
            if (errors < 10)
              $display("MISMATCH a=%0d w=%0d bank=%0d dsp=%0d lut=%0d exp=%0d",
                       ai, wi, bank, $signed(ps_out_d), $signed(ps_out_l), expected);
          end
          @(negedge clk);
        end
      end
    end
    $display("PE_TEST errors=%0d checks=%0d", errors, checks);
    $finish;
  end
endmodule
