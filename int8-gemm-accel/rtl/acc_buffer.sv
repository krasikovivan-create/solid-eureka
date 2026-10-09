// Accumulator buffer: two slots of MT rows x P int32.
//
// Result rows from the array are accumulated with a 3-stage read-modify-write:
//   stage 0: read ACC[slot][row];  stage 1: register the read data;
//   stage 2: ACC[slot][row] <= first ? psum : ACC + psum.
// Rows of the same tile come back at least P >= 4 cycles apart (one weight
// block), so the write (2 cycles after the read) always lands before the next
// read of the same row: no read-after-write hazard. Arithmetic wraps modulo 2^32 (int32).
// When the row tagged 'last' is written, tile_done pulses for that slot.
// The write-back DMA reads a completed slot through the wb_* port; the
// controller guarantees that RMW and write-back never use the same slot.
module acc_buffer #(
  parameter int P  = 16,
  parameter int MT = 128
) (
  input  logic                  clk,
  input  logic                  rst_n,
  // accumulate port (from systolic array)
  input  logic                  in_valid,
  input  logic [P*32-1:0]       in_row,
  input  logic                  in_slot,
  input  logic [$clog2(MT)-1:0] in_addr,
  input  logic                  in_first,
  input  logic                  in_last,
  output logic                  tile_done,
  output logic                  tile_done_slot,
  // write-back read port
  input  logic                  wb_re,
  input  logic                  wb_slot,
  input  logic [$clog2(MT)-1:0] wb_addr,
  output logic [P*32-1:0]       wb_rdata
);
  localparam int AW = $clog2(MT);

  logic [1:0]          re, we;
  logic [2*AW-1:0]     raddr;     // slot s at [s*AW +: AW]
  logic [2*P*32-1:0]   rdata;     // slot s at [s*P*32 +: P*32]
  logic [AW-1:0]       waddr;
  logic [P*32-1:0]     wdata;

  // stage-1 / stage-2 registers
  logic                s1_valid, s1_slot, s1_first, s1_last;
  logic [AW-1:0]       s1_addr;
  logic [P*32-1:0]     s1_row;
  logic                s2_valid, s2_slot, s2_first, s2_last;
  logic [AW-1:0]       s2_addr;
  logic [P*32-1:0]     s2_row, s2_old;
  logic                wb_slot_q;

  genvar s, c;
  generate
    for (s = 0; s < 2; s = s + 1) begin : g_slot
      logic rmw_rd;
      assign rmw_rd   = in_valid && (in_slot == s);
      assign re[s]    = rmw_rd || (wb_re && (wb_slot == s));
      assign raddr[s*AW +: AW] = rmw_rd ? in_addr : wb_addr;
      assign we[s]    = s2_valid && (s2_slot == s);
      sram_1r1w #(.W(P * 32), .D(MT)) u_mem (
        .clk  (clk),
        .we   (we[s]),
        .waddr(waddr),
        .wdata(wdata),
        .re   (re[s]),
        .raddr(raddr[s*AW +: AW]),
        .rdata(rdata[s*P*32 +: P*32])
      );
    end
  endgenerate

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      s1_valid <= 1'b0;
      s2_valid <= 1'b0;
    end else begin
      s1_valid <= in_valid;
      s2_valid <= s1_valid;
    end
    s1_slot   <= in_slot;
    s1_first  <= in_first;
    s1_last   <= in_last;
    s1_addr   <= in_addr;
    s1_row    <= in_row;
    s2_slot   <= s1_slot;
    s2_first  <= s1_first;
    s2_last   <= s1_last;
    s2_addr   <= s1_addr;
    s2_row    <= s1_row;
    s2_old    <= s1_slot ? rdata[P*32 +: P*32] : rdata[0 +: P*32];
    if (wb_re) wb_slot_q <= wb_slot;
  end

  assign waddr = s2_addr;

  generate
    for (c = 0; c < P; c = c + 1) begin : g_add
      assign wdata[c*32 +: 32] = s2_first ? s2_row[c*32 +: 32]
                                          : s2_old[c*32 +: 32] + s2_row[c*32 +: 32];
    end
  endgenerate

  assign tile_done      = s2_valid && s2_last;
  assign tile_done_slot = s2_slot;
  assign wb_rdata       = wb_slot_q ? rdata[P*32 +: P*32] : rdata[0 +: P*32];

`ifndef SYNTHESIS
  always @(posedge clk) begin
    if (rst_n && in_valid && wb_re && (in_slot == wb_slot))
      $error("acc_buffer: RMW and write-back on the same slot %0d", in_slot);
  end
`endif
endmodule
