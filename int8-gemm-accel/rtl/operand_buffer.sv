// Ping-pong operand buffer (used for both the A buffer and the B buffer).
// Two slots of SLOT_DEPTH words, one word = W bits = P bytes. The DMA fills one
// slot through the write port while the sequencer reads the other one.
// Slot ownership (FREE/LOADING/FULL) is tracked by the controller.
//
// Physical organisation: the word is split into LANES independent memories
// (byte lanes; lane l feeds row l of the systolic array). Every lane has its
// own copy of the registered read and write address/enable, so no single net
// fans out to all block RAMs of the buffer (on ECP5-85F such a net alone cost
// ~23 ns of routing). Timing seen from the ports:
//   read : address/enable registered here, data valid 2 cycles after re;
//   write: performed 1 cycle after we (the controller reads a slot no earlier
//          than 2 cycles after the DMA reports it full, so this is invisible).
module operand_buffer #(
  parameter int W          = 128,
  parameter int SLOT_DEPTH = 1024,   // power of two
  parameter int LANES      = 16      // must divide W
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
  localparam int LW = W / LANES;
  localparam int DW = $clog2(SLOT_DEPTH) + 1;   // {slot, address}

  genvar l;
  generate
    for (l = 0; l < LANES; l = l + 1) begin : g_lane
      (* keep *) logic          re_q, we_q;
      (* keep *) logic [DW-1:0] raddr_q, waddr_q;
      logic [LW-1:0]            wdata_q;
      always_ff @(posedge clk) begin
        re_q    <= re;
        raddr_q <= {rslot, raddr};
        we_q    <= we;
        waddr_q <= {wslot, waddr};
        wdata_q <= wdata[l*LW +: LW];
      end
      sram_1r1w #(.W(LW), .D(2 * SLOT_DEPTH)) u_mem (
        .clk  (clk),
        .we   (we_q),
        .waddr(waddr_q),
        .wdata(wdata_q),
        .re   (re_q),
        .raddr(raddr_q),
        .rdata(rdata[l*LW +: LW])
      );
    end
  endgenerate
endmodule
