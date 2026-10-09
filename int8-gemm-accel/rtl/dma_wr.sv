// Write-back DMA: completed accumulator slot -> C in shared memory.
//
// A tile is `rows` rows of P int32; row r goes to base + r*ldc. Each row is
// 4P bytes = 4P/BUS beats; only beats that contain columns < `cols` are sent,
// and the byte strobe masks the columns >= cols in the last beat.
// Two-stage pipeline (SRAM output register + hold register) keeps the write
// channel busy every cycle while the memory accepts beats.
module dma_wr #(
  parameter int P   = 16,
  parameter int MT  = 128,
  parameter int BUS = 16,
  parameter int AW  = 32
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [AW-1:0]         ldc,
  // tile command
  input  logic                  tile_valid,
  output logic                  tile_ready,
  input  logic                  tile_slot,
  input  logic [AW-1:0]         tile_base,
  input  logic [$clog2(MT):0]   tile_rows,
  input  logic [$clog2(P):0]    tile_cols,
  output logic                  tile_done,
  output logic                  tile_done_slot,
  // accumulator read port
  output logic                  acc_re,
  output logic                  acc_slot,
  output logic [$clog2(MT)-1:0] acc_addr,
  input  logic [P*32-1:0]       acc_rdata,
  // memory write channel
  output logic                  wr_valid,
  input  logic                  wr_ready,
  output logic [AW-1:0]         wr_addr,
  output logic [BUS*8-1:0]      wr_data,
  output logic [BUS-1:0]        wr_strb
);
  localparam int BEATS  = (P * 4) / BUS;      // beats per accumulator row
  localparam int BW     = $clog2(BEATS) + 1;
  localparam int RW     = $clog2(MT) + 1;
  localparam int COLS_PER_BEAT = BUS / 4;

  logic           active;
  logic           t_slot;
  logic [RW-1:0]  t_rows;
  logic [BW-1:0]  nbeats;          // beats actually sent per row
  logic [$clog2(BUS):0] last_bytes; // valid bytes in the last sent beat

  // read stage
  logic [RW-1:0]  rd_row;          // next row to read
  logic [AW-1:0]  rd_row_addr;     // its memory address
  logic           r_valid;         // SRAM output holds an unconsumed row
  logic [AW-1:0]  r_addr;
  logic           r_last;
  // hold stage
  logic           h_valid;
  logic [P*32-1:0] h_data;
  logic [AW-1:0]  h_addr;
  logic [BW-1:0]  h_beat;
  logic           h_last;

  logic fire, h_done, move, rd_issue;

  assign tile_ready = !active;
  assign fire     = h_valid && wr_ready;
  assign h_done   = fire && (h_beat == nbeats - 1'b1);
  assign move     = r_valid && (!h_valid || h_done);
  assign rd_issue = active && (rd_row != t_rows) && (!r_valid || move);

  assign acc_re   = rd_issue;
  assign acc_slot = t_slot;
  assign acc_addr = rd_row[$clog2(MT)-1:0];

  // write channel
  assign wr_valid = h_valid;
  assign wr_addr  = h_addr + AW'(h_beat) * AW'(BUS);
  always_comb begin
    wr_data = '0;
    for (int b = 0; b < BEATS; b = b + 1) begin
      if (h_beat == BW'(b)) wr_data = h_data[b*BUS*8 +: BUS*8];
    end
    wr_strb = '1;
    if (h_beat == nbeats - 1'b1) begin
      for (int i = 0; i < BUS; i = i + 1) begin
        if (i >= last_bytes) wr_strb[i] = 1'b0;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      active    <= 1'b0;
      r_valid   <= 1'b0;
      h_valid   <= 1'b0;
      tile_done <= 1'b0;
    end else begin
      tile_done <= 1'b0;
      if (tile_valid && tile_ready) begin
        active      <= 1'b1;
        t_slot      <= tile_slot;
        t_rows      <= RW'(tile_rows);
        nbeats      <= BW'((tile_cols + ($clog2(P)+1)'(COLS_PER_BEAT - 1)) / ($clog2(P)+1)'(COLS_PER_BEAT));
        last_bytes  <= ($clog2(BUS)+1)'(((tile_cols - 1'b1) % ($clog2(P)+1)'(COLS_PER_BEAT) + 1'b1) * 3'd4);
        rd_row      <= '0;
        rd_row_addr <= tile_base;
      end else if (active) begin
        // read stage
        if (rd_issue) begin
          r_valid     <= 1'b1;
          r_addr      <= rd_row_addr;
          r_last      <= (rd_row == t_rows - 1'b1);
          rd_row      <= rd_row + 1'b1;
          rd_row_addr <= rd_row_addr + ldc;
        end else if (move) begin
          r_valid <= 1'b0;
        end
        // hold stage
        if (move) begin
          h_valid <= 1'b1;
          h_data  <= acc_rdata;
          h_addr  <= r_addr;
          h_beat  <= '0;
          h_last  <= r_last;
        end else if (h_done) begin
          h_valid <= 1'b0;
        end else if (fire) begin
          h_beat <= h_beat + 1'b1;
        end
        if (h_done && h_last) begin
          active    <= 1'b0;
          tile_done <= 1'b1;
        end
      end
    end
  end

  always_ff @(posedge clk) begin
    if (tile_valid && tile_ready) tile_done_slot <= tile_slot;
  end
endmodule
