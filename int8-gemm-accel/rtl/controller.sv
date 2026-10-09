// Controller: CSR block, job validation, loader (descriptor generation for the
// read DMA), ownership state of all ping-pong slots, write-back dispatch and
// performance counters.
//
// CSR map (32-bit registers, byte addresses):
//   0x00 CTRL    W: bit0 = start (ignored while busy)
//   0x04 STATUS  R: bit0 busy, bit1 done, bit2 error (bad configuration)
//   0x08 M  0x0C N  0x10 K                       (1..65535; K <= KMAX)
//   0x14 ADDR_A  0x18 ADDR_B  0x1C ADDR_C        (byte addresses, BUS-aligned)
//   0x20 LDA     0x24 LDB     0x28 LDC           (row strides in bytes, BUS-aligned;
//                                                 LDA >= K, LDB >= N, LDC >= 4N)
//   0x30 CYCLES       start..done
//   0x34 CYC_BUSY     a row entered the array
//   0x38 CYC_MEM      array idle: waiting for A/B data from memory
//   0x3C CYC_ACC      array idle: waiting for a free accumulator slot (write-back)
//   0x40 CYC_PIPE     array idle: weight-load timing / short panels
//   0x44 CYC_TAIL     array done, draining pipeline and writing the last tile
//   0x48 RD_BEATS 0x4C WR_BEATS
//   0x50 HWCFG   R: {8'(log2 KMAX), 8'(log2 MT), 8'(BUS), 8'(P)}
module controller #(
  parameter int P    = 16,
  parameter int MT   = 128,
  parameter int KMAX = 1024,
  parameter int BUS  = P,
  parameter int AW   = 32
) (
  input  logic                    clk,
  input  logic                    rst_n,
  // CSR port
  input  logic                    csr_we,
  input  logic [7:0]              csr_addr,
  input  logic [31:0]             csr_wdata,
  output logic [31:0]             csr_rdata,
  output logic                    irq_done,
  // configuration to the datapath
  output logic [15:0]             cfg_m,
  output logic [15:0]             cfg_n,
  output logic [$clog2(KMAX/P):0] cfg_kw,
  output logic [15:0]             cfg_nj,
  output logic [15:0]             cfg_np,
  output logic [AW-1:0]           cfg_addr_c,
  output logic [AW-1:0]           cfg_ldc,
  output logic                    seq_start,
  output logic                    cnt_clear,
  // read DMA descriptors
  output logic                    desc_valid,
  input  logic                    desc_ready,
  output logic                    desc_buf,
  output logic                    desc_slot,
  output logic [AW-1:0]           desc_src,
  output logic [15:0]             desc_rows,
  output logic [7:0]              desc_row_beats,
  output logic [AW-1:0]           desc_stride,
  output logic [$clog2(BUS)-1:0]  desc_mask,
  input  logic                    dma_done,
  input  logic                    dma_done_buf,
  input  logic                    dma_done_slot,
  // sequencer
  output logic [1:0]              a_full,
  output logic [1:0]              b_full,
  output logic [1:0]              acc_free,
  input  logic                    a_release,
  input  logic                    a_release_slot,
  input  logic                    b_release,
  input  logic                    b_release_slot,
  input  logic                    acc_acquire,
  input  logic                    acc_acquire_slot,
  input  logic [AW-1:0]           acc_tile_base,
  input  logic [$clog2(MT):0]     acc_tile_rows,
  input  logic [$clog2(P):0]      acc_tile_cols,
  input  logic                    seq_busy,
  input  logic                    seq_st_issue,
  input  logic                    seq_stall_mem,
  input  logic                    seq_stall_acc,
  input  logic                    seq_stall_pipe,
  // accumulator
  input  logic                    acc_tile_done,
  input  logic                    acc_tile_done_slot,
  // write-back DMA
  output logic                    wb_tile_valid,
  input  logic                    wb_tile_ready,
  output logic                    wb_tile_slot,
  output logic [AW-1:0]           wb_tile_base,
  output logic [$clog2(MT):0]     wb_tile_rows,
  output logic [$clog2(P):0]      wb_tile_cols,
  input  logic                    wb_tile_done,
  input  logic                    wb_tile_done_slot,
  // memory statistics
  input  logic [31:0]             rd_beats,
  input  logic [31:0]             wr_beats
);
  localparam int PL  = $clog2(P);
  localparam int ML  = $clog2(MT);
  localparam int BL  = $clog2(BUS);
  localparam int KWW = $clog2(KMAX / P) + 1;

  localparam logic [1:0] S_FREE = 2'd0, S_LOADING = 2'd1, S_FULL = 2'd2;          // operand slots
  localparam logic [1:0] A_FREE = 2'd0, A_ACCUM = 2'd1, A_DONE = 2'd2, A_WB = 2'd3; // acc slots

  // ---------------- CSR registers ----------------
  logic [15:0]   r_m, r_n, r_k;
  logic [AW-1:0] r_addr_a, r_addr_b, r_addr_c, r_lda, r_ldb, r_ldc;
  logic          st_busy, st_done, st_err;
  logic [31:0]   pc_cycles, pc_busy, pc_mem, pc_acc, pc_pipe, pc_tail;

  logic start_req, cfg_bad, go, go_d, run_q;
  assign start_req = csr_we && (csr_addr == 8'h00) && csr_wdata[0] && !st_busy;

  logic [BL-1:0] align_or;
  assign align_or = r_addr_a[BL-1:0] | r_addr_b[BL-1:0] | r_addr_c[BL-1:0]
                  | r_lda[BL-1:0] | r_ldb[BL-1:0] | r_ldc[BL-1:0];
  assign cfg_bad = (r_m == 16'd0) || (r_n == 16'd0) || (r_k == 16'd0)
                || (32'(r_k) > 32'(KMAX)) || (align_or != '0)
                || (r_lda < AW'(r_k)) || (r_ldb < AW'(r_n)) || (r_ldc < (AW'(r_n) << 2));
  assign go = start_req && !cfg_bad;

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      r_m <= '0; r_n <= '0; r_k <= '0;
      r_addr_a <= '0; r_addr_b <= '0; r_addr_c <= '0;
      r_lda <= '0; r_ldb <= '0; r_ldc <= '0;
    end else if (csr_we && !st_busy) begin
      case (csr_addr)
        8'h08: r_m      <= csr_wdata[15:0];
        8'h0C: r_n      <= csr_wdata[15:0];
        8'h10: r_k      <= csr_wdata[15:0];
        8'h14: r_addr_a <= csr_wdata;
        8'h18: r_addr_b <= csr_wdata;
        8'h1C: r_addr_c <= csr_wdata;
        8'h20: r_lda    <= csr_wdata;
        8'h24: r_ldb    <= csr_wdata;
        8'h28: r_ldc    <= csr_wdata;
        default: ;
      endcase
    end
  end

  // derived configuration, latched at start
  always_ff @(posedge clk) begin
    if (go) begin
      cfg_m      <= r_m;
      cfg_n      <= r_n;
      cfg_kw     <= KWW'((32'(r_k) + 32'(P - 1)) >> PL);
      cfg_nj     <= 16'((32'(r_n) + 32'(P - 1)) >> PL);
      cfg_np     <= 16'((32'(r_m) + 32'(MT - 1)) >> ML);
      cfg_addr_c <= r_addr_c;
      cfg_ldc    <= r_ldc;
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      go_d  <= 1'b0;
      run_q <= 1'b0;
    end else begin
      go_d  <= go;
      run_q <= go_d ? 1'b1 : (st_busy ? run_q : 1'b0);
    end
  end
  assign seq_start = go_d;
  assign cnt_clear = go;

  // ---------------- loader ----------------
  logic          ld_active, ld_phase_b, ld_aslot, ld_bslot;
  logic [15:0]   ld_p, ld_j;
  logic [AW-1:0] ld_a_src, ld_b_src;
  logic [16:0]   ld_m_left;
  logic [3:0]    a_st, b_st;      // slot s state at [2*s +: 2]
  logic          ld_fire;

  assign desc_valid     = ld_active && (ld_phase_b ? (b_st[2*ld_bslot +: 2] == S_FREE)
                                                   : (a_st[2*ld_aslot +: 2] == S_FREE));
  assign ld_fire        = desc_valid && desc_ready;
  assign desc_buf       = ld_phase_b;
  assign desc_slot      = ld_phase_b ? ld_bslot : ld_aslot;
  assign desc_src       = ld_phase_b ? ld_b_src : ld_a_src;
  assign desc_rows      = ld_phase_b ? r_k : ((ld_m_left >= 17'(MT)) ? 16'(MT) : ld_m_left[15:0]);
  assign desc_row_beats = ld_phase_b ? 8'd1 : 8'(cfg_kw);
  assign desc_stride    = ld_phase_b ? r_ldb : r_lda;
  assign desc_mask      = ld_phase_b ? '0 : r_k[BL-1:0];

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      ld_active <= 1'b0;
    end else if (go_d) begin
      ld_active  <= 1'b1;
      ld_phase_b <= 1'b0;
      ld_aslot   <= 1'b0;
      ld_bslot   <= 1'b0;
      ld_p       <= '0;
      ld_j       <= '0;
      ld_a_src   <= r_addr_a;
      ld_b_src   <= r_addr_b;
      ld_m_left  <= {1'b0, r_m};
    end else if (ld_fire) begin
      if (!ld_phase_b) begin
        ld_phase_b <= 1'b1;
      end else begin
        ld_bslot <= ~ld_bslot;
        if (ld_j == cfg_nj - 16'd1) begin
          ld_j       <= '0;
          ld_b_src   <= r_addr_b;
          ld_aslot   <= ~ld_aslot;
          ld_a_src   <= ld_a_src + (r_lda << ML);
          ld_m_left  <= ld_m_left - 17'(MT);
          ld_phase_b <= 1'b0;
          if (ld_p == cfg_np - 16'd1) ld_active <= 1'b0;
          else                        ld_p <= ld_p + 16'd1;
        end else begin
          ld_j     <= ld_j + 16'd1;
          ld_b_src <= ld_b_src + AW'(P);
        end
      end
    end
  end

  // ---------------- slot ownership ----------------
  logic [3:0]          acc_st;                 // slot s at [2*s +: 2]
  logic [2*AW-1:0]     t_base;                 // tile info of slot s
  logic [2*(ML+1)-1:0] t_rows;
  logic [2*(PL+1)-1:0] t_cols;
  logic                wb_ptr;

  assign wb_tile_valid = st_busy && (acc_st[2*wb_ptr +: 2] == A_DONE);
  assign wb_tile_slot  = wb_ptr;
  assign wb_tile_base  = t_base[wb_ptr*AW +: AW];
  assign wb_tile_rows  = t_rows[wb_ptr*(ML+1) +: ML+1];
  assign wb_tile_cols  = t_cols[wb_ptr*(PL+1) +: PL+1];

  genvar s;
  generate
    for (s = 0; s < 2; s = s + 1) begin : g_slots
      assign a_full[s]   = (a_st[2*s +: 2] == S_FULL);
      assign b_full[s]   = (b_st[2*s +: 2] == S_FULL);
      assign acc_free[s] = (acc_st[2*s +: 2] == A_FREE);

      always_ff @(posedge clk) begin
        if (!rst_n || go_d) begin
          a_st[2*s +: 2]   <= S_FREE;
          b_st[2*s +: 2]   <= S_FREE;
          acc_st[2*s +: 2] <= A_FREE;
        end else begin
          // A slot
          if (ld_fire && !ld_phase_b && (ld_aslot == s))              a_st[2*s +: 2] <= S_LOADING;
          else if (dma_done && !dma_done_buf && (dma_done_slot == s)) a_st[2*s +: 2] <= S_FULL;
          else if (a_release && (a_release_slot == s))                a_st[2*s +: 2] <= S_FREE;
          // B slot
          if (ld_fire && ld_phase_b && (ld_bslot == s))               b_st[2*s +: 2] <= S_LOADING;
          else if (dma_done && dma_done_buf && (dma_done_slot == s))  b_st[2*s +: 2] <= S_FULL;
          else if (b_release && (b_release_slot == s))                b_st[2*s +: 2] <= S_FREE;
          // accumulator slot
          if (acc_acquire && (acc_acquire_slot == s))                 acc_st[2*s +: 2] <= A_ACCUM;
          else if (acc_tile_done && (acc_tile_done_slot == s))        acc_st[2*s +: 2] <= A_DONE;
          else if (wb_tile_valid && wb_tile_ready && (wb_ptr == s))   acc_st[2*s +: 2] <= A_WB;
          else if (wb_tile_done && (wb_tile_done_slot == s))          acc_st[2*s +: 2] <= A_FREE;
        end
        if (acc_acquire && (acc_acquire_slot == s)) begin
          t_base[s*AW +: AW]         <= acc_tile_base;
          t_rows[s*(ML+1) +: ML+1]   <= acc_tile_rows;
          t_cols[s*(PL+1) +: PL+1]   <= acc_tile_cols;
        end
      end
    end
  endgenerate

  always_ff @(posedge clk) begin
    if (!rst_n || go_d)                    wb_ptr <= 1'b0;
    else if (wb_tile_valid && wb_tile_ready) wb_ptr <= ~wb_ptr;
  end

  // ---------------- status, done, counters ----------------
  logic all_idle;
  assign all_idle = run_q && !go_d && !seq_busy && !ld_active
                 && (acc_st == {A_FREE, A_FREE});

  always_ff @(posedge clk) begin
    if (!rst_n) begin
      st_busy  <= 1'b0;
      st_done  <= 1'b0;
      st_err   <= 1'b0;
      irq_done <= 1'b0;
    end else begin
      irq_done <= 1'b0;
      if (start_req) begin
        st_busy <= !cfg_bad;
        st_done <= cfg_bad;
        st_err  <= cfg_bad;
        irq_done <= cfg_bad;
      end else if (st_busy && all_idle) begin
        st_busy  <= 1'b0;
        st_done  <= 1'b1;
        irq_done <= 1'b1;
      end
    end
  end

  always_ff @(posedge clk) begin
    if (!rst_n || go) begin
      pc_cycles <= '0; pc_busy <= '0; pc_mem <= '0; pc_acc <= '0; pc_pipe <= '0; pc_tail <= '0;
    end else if (st_busy) begin
      pc_cycles <= pc_cycles + 32'd1;
      if (!run_q || go_d)      pc_mem  <= pc_mem  + 32'd1;   // job start-up
      else if (!seq_busy)      pc_tail <= pc_tail + 32'd1;
      else if (seq_st_issue)   pc_busy <= pc_busy + 32'd1;
      else if (seq_stall_mem)  pc_mem  <= pc_mem  + 32'd1;
      else if (seq_stall_acc)  pc_acc  <= pc_acc  + 32'd1;
      else                     pc_pipe <= pc_pipe + 32'd1;
    end
  end

  always_comb begin
    case (csr_addr)
      8'h04: csr_rdata = {29'd0, st_err, st_done, st_busy};
      8'h08: csr_rdata = {16'd0, r_m};
      8'h0C: csr_rdata = {16'd0, r_n};
      8'h10: csr_rdata = {16'd0, r_k};
      8'h14: csr_rdata = r_addr_a;
      8'h18: csr_rdata = r_addr_b;
      8'h1C: csr_rdata = r_addr_c;
      8'h20: csr_rdata = r_lda;
      8'h24: csr_rdata = r_ldb;
      8'h28: csr_rdata = r_ldc;
      8'h30: csr_rdata = pc_cycles;
      8'h34: csr_rdata = pc_busy;
      8'h38: csr_rdata = pc_mem;
      8'h3C: csr_rdata = pc_acc;
      8'h40: csr_rdata = pc_pipe;
      8'h44: csr_rdata = pc_tail;
      8'h48: csr_rdata = rd_beats;
      8'h4C: csr_rdata = wr_beats;
      8'h50: csr_rdata = {8'($clog2(KMAX)), 8'(ML), 8'(BUS), 8'(P)};
      default: csr_rdata = 32'd0;
    endcase
  end

  // unused in this controller (kept for debug visibility)
  logic unused;
  assign unused = seq_stall_pipe;
endmodule
