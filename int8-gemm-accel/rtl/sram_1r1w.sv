// Simple dual-port synchronous SRAM: one write port, one read port.
// Read data appears one cycle after re and holds until the next read.
// Coded for block-RAM inference (ECP5 DP16KD/PDPW16KD).
module sram_1r1w #(
  parameter int W = 128,
  parameter int D = 1024
) (
  input  logic                 clk,
  input  logic                 we,
  input  logic [$clog2(D)-1:0] waddr,
  input  logic [W-1:0]         wdata,
  input  logic                 re,
  input  logic [$clog2(D)-1:0] raddr,
  output logic [W-1:0]         rdata
);
  logic [W-1:0] mem [0:D-1];

  always_ff @(posedge clk) begin
    if (we) mem[waddr] <= wdata;
  end

  always_ff @(posedge clk) begin
    if (re) rdata <= mem[raddr];
  end

`ifndef SYNTHESIS
  // Defined contents in 4-state simulation (FPGA block RAM powers up as zero).
  initial begin
    for (int k = 0; k < D; k = k + 1) mem[k] = '0;
    rdata = '0;
  end
`endif
endmodule
