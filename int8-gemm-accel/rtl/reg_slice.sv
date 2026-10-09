// Valid/ready register slice with a skid buffer: full throughput, registered
// outputs and registered s_ready (breaks combinational paths at the memory port).
module reg_slice #(
  parameter int W = 32
) (
  input  logic         clk,
  input  logic         rst_n,
  input  logic         s_valid,
  output logic         s_ready,
  input  logic [W-1:0] s_data,
  output logic         m_valid,
  input  logic         m_ready,
  output logic [W-1:0] m_data
);
  logic [W-1:0] data_q, skid_q;
  logic         valid_q, skid_valid;

  assign s_ready = !skid_valid;
  assign m_valid = valid_q;
  assign m_data  = data_q;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      valid_q    <= 1'b0;
      skid_valid <= 1'b0;
    end else if (m_ready || !valid_q) begin
      if (skid_valid) begin
        data_q     <= skid_q;
        valid_q    <= 1'b1;
        skid_valid <= 1'b0;
      end else begin
        data_q  <= s_data;
        valid_q <= s_valid;
      end
    end else if (s_valid && s_ready) begin
      skid_q     <= s_data;
      skid_valid <= 1'b1;
    end
  end
endmodule
