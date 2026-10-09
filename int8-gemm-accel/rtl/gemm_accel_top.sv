// int8 GEMM accelerator, top level.
//   C[M x N] (int32) = A[M x K] (int8) * B[K x N] (int8), all row-major in shared memory.
// See docs/architecture.md for the block diagram, dataflow and CSR map.
module gemm_accel_top #(
  parameter int P     = 16,      // systolic array P x P
  parameter int MT    = 128,     // rows of A per on-chip panel
  parameter int KMAX  = 1024,    // largest supported K
  parameter int N_DSP = P * P,   // PEs whose multiplier is written for DSP inference
  parameter int AW    = 32
) (
  input  logic             clk,
  input  logic             rst_n,
  // control/status registers
  input  logic             csr_we,
  input  logic [7:0]       csr_addr,
  input  logic [31:0]      csr_wdata,
  output logic [31:0]      csr_rdata,
  output logic             irq_done,
  // shared memory port
  output logic             mem_rd_req_valid,
  input  logic             mem_rd_req_ready,
  output logic [AW-1:0]    mem_rd_req_addr,
  output logic [7:0]       mem_rd_req_len,
  input  logic             mem_rd_rsp_valid,
  input  logic [P*8-1:0]   mem_rd_rsp_data,
  output logic             mem_wr_valid,
  input  logic             mem_wr_ready,
  output logic [AW-1:0]    mem_wr_addr,
  output logic [P*8-1:0]   mem_wr_data,
  output logic [P-1:0]     mem_wr_strb
);
  localparam int BUS  = P;                       // bytes per memory beat = one buffer word
  localparam int ML   = $clog2(MT);
  localparam int PL   = $clog2(P);
  localparam int AAW  = $clog2(MT * KMAX / P);   // A slot address width
  localparam int BAW  = $clog2(KMAX);            // B slot address width
  localparam int TW   = ML + 3;                  // token {slot, row, first, last}

  // ---------------- configuration / control ----------------
  logic [15:0]             cfg_m, cfg_n, cfg_nj, cfg_np;
  logic [$clog2(KMAX/P):0] cfg_kw;
  logic [AW-1:0]           cfg_addr_c, cfg_ldc;
  logic                    seq_start, cnt_clear;

  // read DMA
  logic                    desc_valid, desc_ready, desc_buf, desc_slot;
  logic [AW-1:0]           desc_src, desc_stride;
  logic [15:0]             desc_rows;
  logic [7:0]              desc_row_beats;
  logic [$clog2(BUS)-1:0]  desc_mask;
  logic                    dma_done, dma_done_buf, dma_done_slot;
  logic                    rd_req_valid, rd_req_ready;
  logic [AW-1:0]           rd_req_addr;
  logic [7:0]              rd_req_len;
  logic                    rd_rsp_valid;
  logic [BUS*8-1:0]        rd_rsp_data;
  logic                    bw_en, bw_buf, bw_slot;
  logic [AAW-1:0]          bw_addr;
  logic [BUS*8-1:0]        bw_data;

  // sequencer
  logic [1:0]              a_full, b_full, acc_free;
  logic                    a_release, a_release_slot, b_release, b_release_slot;
  logic                    acc_acquire, acc_acquire_slot;
  logic [AW-1:0]           acc_tile_base;
  logic [ML:0]             acc_tile_rows;
  logic [PL:0]             acc_tile_cols;
  logic                    a_re, a_rslot, b_re, b_rslot;
  logic [AAW-1:0]          a_raddr;
  logic [BAW-1:0]          b_raddr;
  logic [BUS*8-1:0]        a_rdata, b_rdata;
  logic                    arr_in_valid, arr_in_bank, arr_w_we, arr_w_bank;
  logic [TW-1:0]           arr_in_tok, arr_out_tok;
  logic [PL-1:0]           arr_w_row;
  logic                    seq_busy, seq_st_issue, seq_stall_mem, seq_stall_acc, seq_stall_pipe;

  // array / accumulator / write-back
  logic                    arr_out_valid;
  logic [P*32-1:0]         arr_out_row;
  logic                    acc_tile_done, acc_tile_done_slot;
  logic                    wb_tile_valid, wb_tile_ready, wb_tile_slot, wb_tile_done, wb_tile_done_slot;
  logic [AW-1:0]           wb_tile_base;
  logic [ML:0]             wb_tile_rows;
  logic [PL:0]             wb_tile_cols;
  logic                    wb_re, wb_slot;
  logic [ML-1:0]           wb_addr;
  logic [P*32-1:0]         wb_rdata;
  logic                    wr_valid, wr_ready;
  logic [AW-1:0]           wr_addr;
  logic [BUS*8-1:0]        wr_data;
  logic [BUS-1:0]          wr_strb;
  logic [31:0]             rd_beats, wr_beats;

  controller #(.P(P), .MT(MT), .KMAX(KMAX), .BUS(BUS), .AW(AW)) u_ctrl (
    .clk, .rst_n,
    .csr_we, .csr_addr, .csr_wdata, .csr_rdata, .irq_done,
    .cfg_m, .cfg_n, .cfg_kw, .cfg_nj, .cfg_np, .cfg_addr_c, .cfg_ldc, .seq_start, .cnt_clear,
    .desc_valid, .desc_ready, .desc_buf, .desc_slot, .desc_src, .desc_rows, .desc_row_beats,
    .desc_stride, .desc_mask, .dma_done, .dma_done_buf, .dma_done_slot,
    .a_full, .b_full, .acc_free, .a_release, .a_release_slot, .b_release, .b_release_slot,
    .acc_acquire, .acc_acquire_slot, .acc_tile_base, .acc_tile_rows, .acc_tile_cols,
    .seq_busy, .seq_st_issue, .seq_stall_mem, .seq_stall_acc, .seq_stall_pipe,
    .acc_tile_done, .acc_tile_done_slot,
    .wb_tile_valid, .wb_tile_ready, .wb_tile_slot, .wb_tile_base, .wb_tile_rows, .wb_tile_cols,
    .wb_tile_done, .wb_tile_done_slot,
    .mem_wr_busy(mem_wr_valid), .rd_beats, .wr_beats
  );

  dma_rd #(.BUS(BUS), .AW(AW), .BUF_AW(AAW)) u_dma_rd (
    .clk, .rst_n,
    .desc_valid, .desc_ready, .desc_buf, .desc_slot, .desc_src, .desc_rows, .desc_row_beats,
    .desc_stride, .desc_mask,
    .req_valid(rd_req_valid), .req_ready(rd_req_ready), .req_addr(rd_req_addr), .req_len(rd_req_len),
    .rsp_valid(rd_rsp_valid), .rsp_data(rd_rsp_data),
    .wr_en(bw_en), .wr_buf(bw_buf), .wr_slot(bw_slot), .wr_addr(bw_addr), .wr_data(bw_data),
    .done(dma_done), .done_buf(dma_done_buf), .done_slot(dma_done_slot)
  );

  // The operand buffers register their read (and write) ports internally, with
  // one copy per byte lane, so the sequencer's issue logic never drives the
  // high-fanout block-RAM address/enable nets combinationally. A slot released
  // by the sequencer is therefore read one cycle after the release; the DMA
  // needs many more cycles before it can write into a freed slot.
  operand_buffer #(.W(BUS * 8), .SLOT_DEPTH(MT * KMAX / P), .LANES(P)) u_abuf (
    .clk,
    .we(bw_en && !bw_buf), .wslot(bw_slot), .waddr(bw_addr), .wdata(bw_data),
    .re(a_re), .rslot(a_rslot), .raddr(a_raddr), .rdata(a_rdata)
  );

  operand_buffer #(.W(BUS * 8), .SLOT_DEPTH(KMAX), .LANES(P)) u_bbuf (
    .clk,
    .we(bw_en && bw_buf), .wslot(bw_slot), .waddr(bw_addr[BAW-1:0]), .wdata(bw_data),
    .re(b_re), .rslot(b_rslot), .raddr(b_raddr), .rdata(b_rdata)
  );

  sequencer #(.P(P), .MT(MT), .KMAX(KMAX), .AW(AW)) u_seq (
    .clk, .rst_n, .start(seq_start),
    .cfg_m, .cfg_n, .cfg_kw, .cfg_nj, .cfg_np, .cfg_addr_c, .cfg_ldc,
    .a_full, .b_full, .acc_free,
    .a_release, .a_release_slot, .b_release, .b_release_slot,
    .acc_acquire, .acc_acquire_slot, .acc_tile_base, .acc_tile_rows, .acc_tile_cols,
    .a_re, .a_rslot, .a_raddr, .b_re, .b_rslot, .b_raddr,
    .arr_in_valid, .arr_in_bank, .arr_in_tok, .arr_w_we, .arr_w_row, .arr_w_bank,
    .busy(seq_busy), .st_issue(seq_st_issue), .stall_mem(seq_stall_mem),
    .stall_acc(seq_stall_acc), .stall_pipe(seq_stall_pipe)
  );

  // Pipeline register between the (cascaded) block RAMs and the array. The
  // control that travels with the data is delayed by the same number of cycles
  // as the data (registered read port + RAM + output register), so all timing
  // relations of the sequencer are unchanged.
  logic [BUS*8-1:0] a_rdata_q, b_rdata_q;
  logic             in_valid_d, in_bank_d, w_we_d, w_bank_d;
  logic [TW-1:0]    in_tok_d;
  logic [PL-1:0]    w_row_d;
  logic             in_valid_q, in_bank_q, w_we_q, w_bank_q;
  logic [TW-1:0]    in_tok_q;
  logic [PL-1:0]    w_row_q;
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      in_valid_d <= 1'b0;
      w_we_d     <= 1'b0;
      in_valid_q <= 1'b0;
      w_we_q     <= 1'b0;
    end else begin
      in_valid_d <= arr_in_valid;
      w_we_d     <= arr_w_we;
      in_valid_q <= in_valid_d;
      w_we_q     <= w_we_d;
    end
    in_bank_d <= arr_in_bank;
    in_tok_d  <= arr_in_tok;
    w_row_d   <= arr_w_row;
    w_bank_d  <= arr_w_bank;
    a_rdata_q <= a_rdata;
    b_rdata_q <= b_rdata;
    in_bank_q <= in_bank_d;
    in_tok_q  <= in_tok_d;
    w_row_q   <= w_row_d;
    w_bank_q  <= w_bank_d;
  end

  systolic_array #(.P(P), .TW(TW), .N_DSP(N_DSP)) u_array (
    .clk, .rst_n,
    .a_row(a_rdata_q), .in_valid(in_valid_q), .in_bank(in_bank_q), .in_tok(in_tok_q),
    .w_row_data(b_rdata_q), .w_we(w_we_q), .w_row_idx(w_row_q), .w_bank(w_bank_q),
    .out_row(arr_out_row), .out_valid(arr_out_valid), .out_tok(arr_out_tok)
  );

  acc_buffer #(.P(P), .MT(MT)) u_acc (
    .clk, .rst_n,
    .in_valid(arr_out_valid), .in_row(arr_out_row),
    .in_slot(arr_out_tok[ML+2]), .in_addr(arr_out_tok[ML+1:2]),
    .in_first(arr_out_tok[1]), .in_last(arr_out_tok[0]),
    .tile_done(acc_tile_done), .tile_done_slot(acc_tile_done_slot),
    .wb_re, .wb_slot, .wb_addr, .wb_rdata
  );

  dma_wr #(.P(P), .MT(MT), .BUS(BUS), .AW(AW)) u_dma_wr (
    .clk, .rst_n, .ldc(cfg_ldc),
    .tile_valid(wb_tile_valid), .tile_ready(wb_tile_ready), .tile_slot(wb_tile_slot),
    .tile_base(wb_tile_base), .tile_rows(wb_tile_rows), .tile_cols(wb_tile_cols),
    .tile_done(wb_tile_done), .tile_done_slot(wb_tile_done_slot),
    .acc_re(wb_re), .acc_slot(wb_slot), .acc_addr(wb_addr), .acc_rdata(wb_rdata),
    .wr_valid, .wr_ready, .wr_addr, .wr_data, .wr_strb
  );

  mem_if #(.BUS(BUS), .AW(AW)) u_mem_if (
    .clk, .rst_n, .cnt_clear,
    .dma_req_valid(rd_req_valid), .dma_req_ready(rd_req_ready),
    .dma_req_addr(rd_req_addr), .dma_req_len(rd_req_len),
    .dma_rsp_valid(rd_rsp_valid), .dma_rsp_data(rd_rsp_data),
    .dma_wr_valid(wr_valid), .dma_wr_ready(wr_ready), .dma_wr_addr(wr_addr),
    .dma_wr_data(wr_data), .dma_wr_strb(wr_strb),
    .rd_req_valid(mem_rd_req_valid), .rd_req_ready(mem_rd_req_ready),
    .rd_req_addr(mem_rd_req_addr), .rd_req_len(mem_rd_req_len),
    .rd_rsp_valid(mem_rd_rsp_valid), .rd_rsp_data(mem_rd_rsp_data),
    .wr_valid(mem_wr_valid), .wr_ready(mem_wr_ready), .wr_addr(mem_wr_addr),
    .wr_data(mem_wr_data), .wr_strb(mem_wr_strb),
    .rd_beats, .wr_beats
  );
endmodule
