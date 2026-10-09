// Ping-pong operand buffer (used for both the A buffer and the B buffer).
// Two slots of SLOT_DEPTH words, one word = W bits = P bytes. The DMA fills one
// slot through the write port while the sequencer reads the other one.
// Slot ownership (FREE/LOADING/FULL) is tracked by the controller.
module operand_buffer #(
  parameter int W          = 128,
  parameter int SLOT_DEPTH = 1024   // power of two
) (
  input  logic                          clk,
  input  logic                          we,
  input  logic                          wslot,
  input  logic [$clog2(SLOT_DEPTH)-1:0] waddr,
  input  logic [W-1:0]                  wdata,
  input  logic                          re,
  input  logic                          rslot,
  input  logic [$clog2(SLOT_DEPTH)-1:0] raddr,
  output logic [W-1:0]                  rdata
);
  sram_1r1w #(.W(W), .D(2 * SLOT_DEPTH)) u_mem (
    .clk  (clk),
    .we   (we),
    .waddr({wslot, waddr}),
    .wdata(wdata),
    .re   (re),
    .raddr({rslot, raddr}),
    .rdata(rdata)
  );
endmodule
