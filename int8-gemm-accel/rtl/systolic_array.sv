// P x P weight-stationary systolic array with input skew and output de-skew.
//
// PE(i,j) holds weight B[k0+i][j0+j]. A row word a_row = A[m][k0 +: P] enters
// unskewed; byte i is delayed by i cycles so that it meets the partial sum of
// row m at PE(i,0). Column j produces sum_i A[m][k0+i]*B[k0+i][j0+j] at its bottom
// P+j cycles after the row entered; the de-skew aligns all columns, so the
// result row leaves exactly LAT = 2P-1 cycles after the input row. The valid bit
// and an opaque token (accumulator address etc.) travel through a matching
// delay line.
//
// Weight load: w_row_data = B[k0+w_row_idx][j0 +: P] is written into PE row
// w_row_idx, bank w_bank. The sequencer guarantees the bank is not in use.
module systolic_array #(
  parameter int P     = 16,
  parameter int PW    = 16 + $clog2(P),
  parameter int TW    = 10,        // token width
  parameter int N_DSP = P * P      // PEs with linear index < N_DSP use DSP multipliers
) (
  input  logic                 clk,
  input  logic                 rst_n,
  // activation row input
  input  logic [P*8-1:0]       a_row,
  input  logic                 in_valid,
  input  logic                 in_bank,
  input  logic [TW-1:0]        in_tok,
  // weight load
  input  logic [P*8-1:0]       w_row_data,
  input  logic                 w_we,
  input  logic [$clog2(P)-1:0] w_row_idx,
  input  logic                 w_bank,
  // result row output (int32 per column)
  output logic [P*32-1:0]      out_row,
  output logic                 out_valid,
  output logic [TW-1:0]        out_tok
);
  localparam int LAT = 2 * P - 1;

  // ---- input skew: lane i carries {bank, a[i]} ----
  logic [P*9-1:0] lane_in, lane_skewed;
  genvar i, j;
  generate
    for (i = 0; i < P; i = i + 1) begin : g_lane_in
      // invalid rows enter as zeros (no toggling, no X propagation)
      assign lane_in[i*9 +: 9] = {in_bank, in_valid ? a_row[i*8 +: 8] : 8'd0};
    end
  endgenerate

  skew_lines #(.LANES(P), .W(9), .ASCENDING(1'b1)) u_skew_in (
    .clk(clk), .din(lane_in), .dout(lane_skewed));

  // ---- PE grid; flattened interconnect ----
  // a_h/s_h: (P rows) x (P+1 columns), ps_v: (P+1 rows) x (P columns)
  logic [P*(P+1)*8-1:0]  a_h;
  logic [P*(P+1)-1:0]    s_h;
  logic [(P+1)*P*PW-1:0] ps_v;

  generate
    for (i = 0; i < P; i = i + 1) begin : g_row
      assign a_h[(i*(P+1))*8 +: 8] = lane_skewed[i*9 +: 8];
      assign s_h[i*(P+1)]          = lane_skewed[i*9 + 8];
      for (j = 0; j < P; j = j + 1) begin : g_col
        if (i == 0) begin : g_top
          assign ps_v[j*PW +: PW] = '0;
        end
        pe #(.PW(PW), .USE_DSP((i * P + j) < N_DSP)) u_pe (
          .clk   (clk),
          .a_in  (a_h[(i*(P+1)+j)*8 +: 8]),
          .s_in  (s_h[i*(P+1)+j]),
          .a_out (a_h[(i*(P+1)+j+1)*8 +: 8]),
          .s_out (s_h[i*(P+1)+j+1]),
          .ps_in (ps_v[(i*P+j)*PW +: PW]),
          .ps_out(ps_v[((i+1)*P+j)*PW +: PW]),
          .w_data(w_row_data[j*8 +: 8]),
          .w_we  (w_we && (w_row_idx == i)),
          .w_bank(w_bank)
        );
      end
    end
  endgenerate

  // ---- output de-skew: column j delayed by P-1-j ----
  logic [P*PW-1:0] col_out, col_aligned;
  assign col_out = ps_v[P*P*PW +: P*PW];

  skew_lines #(.LANES(P), .W(PW), .ASCENDING(1'b0)) u_skew_out (
    .clk(clk), .din(col_out), .dout(col_aligned));

  generate
    for (j = 0; j < P; j = j + 1) begin : g_sext
      assign out_row[j*32 +: 32] = {{(32-PW){col_aligned[j*PW+PW-1]}}, col_aligned[j*PW +: PW]};
    end
  endgenerate

  // ---- valid/token delay line, LAT cycles ----
  logic [LAT-1:0]    vld_sr;
  logic [LAT*TW-1:0] tok_sr;
  always_ff @(posedge clk) begin
    if (!rst_n) vld_sr <= '0;
    else        vld_sr <= {vld_sr[LAT-2:0], in_valid};
    tok_sr <= {tok_sr[(LAT-1)*TW-1:0], in_tok};
  end
  assign out_valid = vld_sr[LAT-1];
  assign out_tok   = tok_sr[LAT*TW-1 -: TW];
endmodule
