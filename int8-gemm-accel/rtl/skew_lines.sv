// Triangular bank of delay lines.
// ASCENDING=1: lane l is delayed by l cycles (input skew of the systolic array).
// ASCENDING=0: lane l is delayed by LANES-1-l cycles (output de-skew).
module skew_lines #(
  parameter int LANES     = 16,
  parameter int W         = 8,
  parameter bit ASCENDING = 1'b1
) (
  input  logic               clk,
  input  logic [LANES*W-1:0] din,
  output logic [LANES*W-1:0] dout
);
  genvar l;
  generate
    for (l = 0; l < LANES; l = l + 1) begin : g_lane
      localparam int D = ASCENDING ? l : (LANES - 1 - l);
      if (D == 0) begin : g_pass
        assign dout[l*W +: W] = din[l*W +: W];
      end else if (D == 1) begin : g_d1
        logic [W-1:0] sr;
        always_ff @(posedge clk) sr <= din[l*W +: W];
        assign dout[l*W +: W] = sr;
      end else begin : g_dn
        logic [D*W-1:0] sr;   // sr[W-1:0] is the newest stage
        always_ff @(posedge clk) sr <= {sr[(D-1)*W-1:0], din[l*W +: W]};
        assign dout[l*W +: W] = sr[D*W-1 -: W];
      end
    end
  endgenerate
endmodule
