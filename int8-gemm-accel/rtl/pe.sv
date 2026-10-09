// Processing element of the weight-stationary systolic array.
//
// Two pipeline stages on the vertical path (uniform for every PE, so the
// systolic alignment is preserved; the array latency is 2P):
//   prod_q <= a_in * w[s_in];   ps_out <= ps_in + prod_q;   a_out <= a_in;  s_out <= s_in.
// Two weight registers (banks) let the next weight block be loaded while the
// current one is in use; the bank is selected by s_in, which travels with the data.
// USE_DSP=1 writes the product as a*w (mapped to a DSP multiplier by synthesis),
// USE_DSP=0 uses an explicit shift-add tree so that synthesis keeps it in LUTs.
module pe #(
  parameter int PW      = 20,   // partial-sum width (exact: 16 + log2(P))
  parameter bit USE_DSP = 1'b1
) (
  input  logic          clk,
  // horizontal path (activations)
  input  logic [7:0]    a_in,
  input  logic          s_in,
  output logic [7:0]    a_out,
  output logic          s_out,
  // vertical path (partial sums)
  input  logic [PW-1:0] ps_in,
  output logic [PW-1:0] ps_out,
  // weight load: column bus + per-row write enable
  input  logic [7:0]    w_data,
  input  logic          w_we,
  input  logic          w_bank
);
  logic [7:0]  w0, w1, w;
  logic [15:0] prod, prod_q;

  assign w = s_in ? w1 : w0;

  generate
    if (USE_DSP) begin : g_dsp
      assign prod = 16'($signed(a_in) * $signed(w));
    end else begin : g_lut
      // two's complement: w = -w[7]*2^7 + sum_{i<7} w[i]*2^i
      logic [15:0] ae;
      logic [15:0] pp0, pp1, pp2, pp3, pp4, pp5, pp6, pp7;
      logic [15:0] s0, s1, s2, s3, t0, t1;
      assign ae  = {{8{a_in[7]}}, a_in};
      assign pp0 = w[0] ? ae        : 16'd0;
      assign pp1 = w[1] ? (ae << 1) : 16'd0;
      assign pp2 = w[2] ? (ae << 2) : 16'd0;
      assign pp3 = w[3] ? (ae << 3) : 16'd0;
      assign pp4 = w[4] ? (ae << 4) : 16'd0;
      assign pp5 = w[5] ? (ae << 5) : 16'd0;
      assign pp6 = w[6] ? (ae << 6) : 16'd0;
      assign pp7 = w[7] ? (ae << 7) : 16'd0;
      assign s0 = pp0 + pp1;
      assign s1 = pp2 + pp3;
      assign s2 = pp4 + pp5;
      assign s3 = pp6 - pp7;
      assign t0 = s0 + s1;
      assign t1 = s2 + s3;
      assign prod = t0 + t1;   // exact modulo 2^16; the true product fits in 16 bits
    end
  endgenerate

  always_ff @(posedge clk) begin
    if (w_we && !w_bank) w0 <= w_data;
    if (w_we &&  w_bank) w1 <= w_data;
    a_out  <= a_in;
    s_out  <= s_in;
    prod_q <= prod;
    ps_out <= ps_in + {{(PW-16){prod_q[15]}}, prod_q};
  end
endmodule
