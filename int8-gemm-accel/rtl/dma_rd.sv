// Read DMA: shared memory -> A/B operand buffers.
//
// A descriptor describes a 2D panel: `rows` rows of `row_beats` beats each,
// starting at `src`, rows `stride` bytes apart. One memory request is issued per
// row. Responses come back in order; the panel is written densely into the
// selected buffer slot (word address 0, 1, 2, ...). For the last beat of each
// row only the first `mask` bytes are kept (the K tail of A), the rest are
// zeroed; mask = 0 keeps the whole beat. A two-entry FIFO of panel descriptors
// lets the issue side start the next panel while responses of the previous
// one are still arriving. `done` pulses together with the last buffer write.
module dma_rd #(
  parameter int BUS    = 16,
  parameter int AW     = 32,
  parameter int BUF_AW = 13
) (
  input  logic                   clk,
  input  logic                   rst_n,
  // descriptor
  input  logic                   desc_valid,
  output logic                   desc_ready,
  input  logic                   desc_buf,     // 0: A buffer, 1: B buffer
  input  logic                   desc_slot,
  input  logic [AW-1:0]          desc_src,
  input  logic [15:0]            desc_rows,
  input  logic [7:0]             desc_row_beats,
  input  logic [AW-1:0]          desc_stride,
  input  logic [$clog2(BUS)-1:0] desc_mask,
  // memory side
  output logic                   req_valid,
  input  logic                   req_ready,
  output logic [AW-1:0]          req_addr,
  output logic [7:0]             req_len,
  input  logic                   rsp_valid,
  input  logic [BUS*8-1:0]       rsp_data,
  // buffer write port
  output logic                   wr_en,
  output logic                   wr_buf,
  output logic                   wr_slot,
  output logic [BUF_AW-1:0]      wr_addr,
  output logic [BUS*8-1:0]       wr_data,
  // completion
  output logic                   done,
  output logic                   done_buf,
  output logic                   done_slot
);
  localparam int MW = $clog2(BUS);

  // ---------------- panel FIFO (depth 2) ----------------
  logic [1:0]    f_buf, f_slot;
  logic [15:0]   f_rows  [0:1];
  logic [7:0]    f_beats [0:1];
  logic [MW-1:0] f_mask  [0:1];
  logic          f_wp, f_rp;
  logic [1:0]    f_count;
  logic          push, pop;

  // ---------------- issue side ----------------
  logic          iss_active;
  logic [AW-1:0] iss_addr, iss_stride;
  logic [15:0]   iss_rows_left;
  logic [7:0]    iss_len;

  assign desc_ready = !iss_active && (f_count < 2'd2);
  assign push       = desc_valid && desc_ready;
  assign req_valid  = iss_active;
  assign req_addr   = iss_addr;
  assign req_len    = iss_len;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      iss_active <= 1'b0;
    end else if (push) begin
      iss_active    <= 1'b1;
      iss_addr      <= desc_src;
      iss_stride    <= desc_stride;
      iss_rows_left <= desc_rows;
      iss_len       <= desc_row_beats;
    end else if (req_valid && req_ready) begin
      iss_addr      <= iss_addr + iss_stride;
      iss_rows_left <= iss_rows_left - 16'd1;
      if (iss_rows_left == 16'd1) iss_active <= 1'b0;
    end
  end

  always_ff @(posedge clk) begin
    if (push) begin
      f_buf[f_wp]   <= desc_buf;
      f_slot[f_wp]  <= desc_slot;
      f_rows[f_wp]  <= desc_rows;
      f_beats[f_wp] <= desc_row_beats;
      f_mask[f_wp]  <= desc_mask;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      f_wp    <= 1'b0;
      f_rp    <= 1'b0;
      f_count <= 2'd0;
    end else begin
      if (push) f_wp <= ~f_wp;
      if (pop)  f_rp <= ~f_rp;
      f_count <= f_count + {1'b0, push} - {1'b0, pop};
    end
  end

  // ---------------- response side ----------------
  // The parameters of the panel at the FIFO head are loaded into registers
  // (h_*) when it becomes the head; "last beat of row" / "last row" are kept
  // as precomputed flags, so the per-beat logic is a few LUT levels deep.
  logic              h_loaded, h_buf, h_slot, h_last_beat, h_last_row;
  logic [7:0]        h_beats, h_beat_left;
  logic [15:0]       h_rows_left;
  logic [MW-1:0]     h_mask;
  logic [BUF_AW-1:0] r_waddr;
  logic [BUS*8-1:0]  masked;
  logic              next_avail, load_next;

  assign pop        = rsp_valid && h_last_beat && h_last_row;
  // after a pop the next panel is loaded at once if it is already in the FIFO
  assign next_avail = pop ? (f_count == 2'd2) : (f_count != 2'd0);
  assign load_next  = (!h_loaded || pop) && next_avail;

  always_comb begin
    masked = rsp_data;
    if (h_last_beat && (h_mask != '0)) begin
      for (int b = 0; b < BUS; b = b + 1) begin
        if (b >= h_mask) masked[b*8 +: 8] = 8'd0;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      h_loaded <= 1'b0;
      r_waddr  <= '0;
      wr_en    <= 1'b0;
      done     <= 1'b0;
    end else begin
      wr_en <= rsp_valid;
      done  <= pop;
      if (load_next) begin
        // f_rp has not advanced yet in the pop cycle: the next entry is at ~f_rp
        h_loaded    <= 1'b1;
        h_buf       <= pop ? f_buf[~f_rp]   : f_buf[f_rp];
        h_slot      <= pop ? f_slot[~f_rp]  : f_slot[f_rp];
        h_beats     <= pop ? f_beats[~f_rp] : f_beats[f_rp];
        h_beat_left <= pop ? f_beats[~f_rp] : f_beats[f_rp];
        h_last_beat <= pop ? (f_beats[~f_rp] == 8'd1) : (f_beats[f_rp] == 8'd1);
        h_rows_left <= pop ? f_rows[~f_rp]  : f_rows[f_rp];
        h_last_row  <= pop ? (f_rows[~f_rp] == 16'd1) : (f_rows[f_rp] == 16'd1);
        h_mask      <= pop ? f_mask[~f_rp]  : f_mask[f_rp];
      end else if (pop) begin
        h_loaded <= 1'b0;
      end else if (rsp_valid) begin
        if (h_last_beat) begin
          h_beat_left <= h_beats;
          h_last_beat <= (h_beats == 8'd1);
          h_rows_left <= h_rows_left - 16'd1;
          h_last_row  <= (h_rows_left == 16'd2);
        end else begin
          h_beat_left <= h_beat_left - 8'd1;
          h_last_beat <= (h_beat_left == 8'd2);
        end
      end
      if (rsp_valid) r_waddr <= pop ? '0 : r_waddr + 1'b1;
    end
  end

  always_ff @(posedge clk) begin
    wr_buf    <= h_buf;
    wr_slot   <= h_slot;
    wr_addr   <= r_waddr;
    wr_data   <= masked;
    done_buf  <= h_buf;
    done_slot <= h_slot;
  end

`ifndef SYNTHESIS
  always @(posedge clk) begin
    if (rst_n && rsp_valid && !h_loaded)
      $error("dma_rd: response beat without an active panel descriptor");
  end
`endif
endmodule
