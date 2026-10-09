// Compute sequencer: drives the systolic array.
//
// Walks the blocks (p, j, kb): panel p of A (MT rows), column block j of B/C
// (P columns), k block kb (P values of K). Two cooperating machines:
//
//  WL (weight loader): reads the P rows B[kb*P + r][j*P +: P], r = 0..P-1, from
//     the B buffer and writes them into PE row r, bank = block parity.
//  ST (streamer): reads A rows A[m][kb*P +: P], m = 0..MT_eff-1, from the A buffer
//     and feeds them into the array together with a token
//     {acc slot, row, first k block, last row of the tile}.
//
// Timing rules (derived in docs/architecture.md, section 3):
//   * ST may start block b one cycle after WL started block b;
//   * WL may start block b+1 only P-1 cycles after ST started block b, which
//     guarantees that the bank being overwritten is no longer used by block b-1;
//   * WL is at most one block ahead of ST.
// With MT_eff >= P the array therefore streams one row per cycle without gaps.
module sequencer #(
  parameter int P    = 16,
  parameter int MT   = 128,
  parameter int KMAX = 1024,
  parameter int AW   = 32
) (
  input  logic                          clk,
  input  logic                          rst_n,
  input  logic                          start,
  // configuration (stable while busy)
  input  logic [15:0]                   cfg_m,
  input  logic [15:0]                   cfg_n,
  input  logic [$clog2(KMAX/P):0]       cfg_kw,     // ceil(K/P)
  input  logic [15:0]                   cfg_nj,     // ceil(N/P)
  input  logic [15:0]                   cfg_np,     // ceil(M/MT)
  input  logic [AW-1:0]                 cfg_addr_c,
  input  logic [AW-1:0]                 cfg_ldc,
  // slot status from the controller
  input  logic [1:0]                    a_full,
  input  logic [1:0]                    b_full,
  input  logic [1:0]                    acc_free,
  // slot events to the controller
  output logic                          a_release,
  output logic                          a_release_slot,
  output logic                          b_release,
  output logic                          b_release_slot,
  output logic                          acc_acquire,
  output logic                          acc_acquire_slot,
  output logic [AW-1:0]                 acc_tile_base,
  output logic [$clog2(MT):0]           acc_tile_rows,
  output logic [$clog2(P):0]            acc_tile_cols,
  // A buffer read port
  output logic                          a_re,
  output logic                          a_rslot,
  output logic [$clog2(MT*KMAX/P)-1:0]  a_raddr,
  // B buffer read port
  output logic                          b_re,
  output logic                          b_rslot,
  output logic [$clog2(KMAX)-1:0]       b_raddr,
  // array control (aligned with the buffer read data, i.e. one cycle after a_re/b_re)
  output logic                          arr_in_valid,
  output logic                          arr_in_bank,
  output logic [$clog2(MT)+2:0]         arr_in_tok,
  output logic                          arr_w_we,
  output logic [$clog2(P)-1:0]          arr_w_row,
  output logic                          arr_w_bank,
  // status
  output logic                          busy,
  output logic                          st_issue,     // a row enters the array this cycle (+1)
  output logic                          stall_mem,    // waiting for A or B data
  output logic                          stall_acc,    // waiting for a free accumulator slot
  output logic                          stall_pipe    // waiting for weight-load timing
);
  localparam int KWW  = $clog2(KMAX / P) + 1;
  localparam int RW   = $clog2(MT) + 1;
  localparam int AAW  = $clog2(MT * KMAX / P);
  localparam int BAW  = $clog2(KMAX);
  localparam int PL   = $clog2(P);

  // ======================= weight loader (WL) =======================
  logic           wl_active, wl_ahead, wl_done_all, wl_bank, wl_bslot;
  logic [PL-1:0]  wl_r;
  logic [KWW-1:0] wl_kb;
  logic [15:0]    wl_j, wl_p;
  logic           wl_go, wl_issue, wl_last_row;
  logic [PL-1:0]  wl_cur_r;

  // ======================= streamer (ST) ============================
  logic           st_active, st_any, st_done_all, st_bank, st_aslot, st_accslot;
  logic [RW-1:0]  st_r;
  logic [AAW-1:0] st_addr;
  logic [KWW-1:0] st_kb;
  logic [15:0]    st_j, st_p;
  logic [PL:0]    st_since;           // cycles since ST started its latest block (saturating)
  logic [16:0]    st_m_left;          // rows of A not yet covered by previous panels
  logic [16:0]    st_n_left;          // columns of C not yet covered by previous blocks
  logic [RW-1:0]  st_mt_eff;
  logic [PL:0]    st_cols;
  logic [AW-1:0]  st_c_panel, st_c_tile;
  logic           st_go, st_last_row, st_last_kb;
  logic [RW-1:0]  st_cur_r;
  logic [AAW-1:0] st_cur_addr;

  assign st_mt_eff = (st_m_left >= 17'(MT)) ? RW'(MT) : RW'(st_m_left);
  assign st_cols   = (st_n_left >= 17'(P))  ? (PL+1)'(P) : (PL+1)'(st_n_left);

  // ---- WL ----
  assign wl_go = !wl_done_all && !wl_active && !wl_ahead && b_full[wl_bslot]
               && (!st_any || (st_since >= (PL+1)'(P - 1)));
  assign wl_issue    = wl_go || wl_active;
  assign wl_cur_r    = wl_go ? '0 : wl_r;
  assign wl_last_row = (wl_cur_r == PL'(P - 1));

  assign b_re    = wl_issue;
  assign b_rslot = wl_bslot;
  assign b_raddr = BAW'(wl_kb) * BAW'(P) + BAW'(wl_cur_r);

  always_ff @(posedge clk) begin
    if (!rst_n || start) begin
      wl_active   <= 1'b0;
      wl_ahead    <= 1'b0;
      wl_done_all <= !rst_n;   // idle after reset, armed by start
      wl_bank     <= 1'b0;
      wl_bslot    <= 1'b0;
      wl_r        <= '0;
      wl_kb       <= '0;
      wl_j        <= '0;
      wl_p        <= '0;
    end else begin
      if (wl_go) wl_ahead <= 1'b1;
      else if (st_go) wl_ahead <= 1'b0;
      if (wl_issue) begin
        if (wl_last_row) begin
          wl_active <= 1'b0;
          wl_bank   <= ~wl_bank;
          if (wl_kb == cfg_kw - 1'b1) begin
            wl_kb    <= '0;
            wl_bslot <= ~wl_bslot;
            if (wl_j == cfg_nj - 16'd1) begin
              wl_j <= '0;
              if (wl_p == cfg_np - 16'd1) wl_done_all <= 1'b1;
              else                        wl_p <= wl_p + 16'd1;
            end else begin
              wl_j <= wl_j + 16'd1;
            end
          end else begin
            wl_kb <= wl_kb + 1'b1;
          end
        end else begin
          wl_active <= 1'b1;
          wl_r      <= wl_cur_r + 1'b1;
        end
      end
    end
  end

  // B slot is released after the last weight row of its last k block is read
  assign b_release      = wl_issue && wl_last_row && (wl_kb == cfg_kw - 1'b1);
  assign b_release_slot = wl_bslot;

  // ---- ST ----
  assign st_go = !st_done_all && !st_active && wl_ahead && a_full[st_aslot]
               && ((st_kb != '0) || acc_free[st_accslot]);
  assign st_issue    = st_go || st_active;
  assign st_cur_r    = st_go ? '0 : st_r;
  assign st_cur_addr = st_go ? AAW'(st_kb) : st_addr;
  assign st_last_row = (st_cur_r == st_mt_eff - 1'b1);
  assign st_last_kb  = (st_kb == cfg_kw - 1'b1);

  assign a_re    = st_issue;
  assign a_rslot = st_aslot;
  assign a_raddr = st_cur_addr;

  assign acc_acquire      = st_go && (st_kb == '0);
  assign acc_acquire_slot = st_accslot;
  assign acc_tile_base    = st_c_tile;
  assign acc_tile_rows    = st_mt_eff;
  assign acc_tile_cols    = st_cols;

  assign a_release      = st_issue && st_last_row && st_last_kb && (st_j == cfg_nj - 16'd1);
  assign a_release_slot = st_aslot;

  always_ff @(posedge clk) begin
    if (!rst_n || start) begin
      st_active   <= 1'b0;
      st_any      <= 1'b0;
      st_done_all <= !rst_n;
      st_bank     <= 1'b0;
      st_aslot    <= 1'b0;
      st_accslot  <= 1'b0;
      st_r        <= '0;
      st_addr     <= '0;
      st_kb       <= '0;
      st_j        <= '0;
      st_p        <= '0;
      st_since    <= '0;
      st_m_left   <= {1'b0, cfg_m};
      st_n_left   <= {1'b0, cfg_n};
      st_c_panel  <= cfg_addr_c;
      st_c_tile   <= cfg_addr_c;
    end else begin
      if (st_go) begin
        st_any   <= 1'b1;
        st_since <= (PL+1)'(1);
      end else if (st_since != (PL+1)'(P)) begin
        st_since <= st_since + 1'b1;
      end
      if (st_issue) begin
        if (st_last_row) begin
          st_active <= 1'b0;
          st_bank   <= ~st_bank;
          if (st_last_kb) begin
            st_kb      <= '0;
            st_accslot <= ~st_accslot;
            if (st_j == cfg_nj - 16'd1) begin
              st_j       <= '0;
              st_aslot   <= ~st_aslot;
              st_n_left  <= {1'b0, cfg_n};
              if (st_p == cfg_np - 16'd1) begin
                st_done_all <= 1'b1;
              end else begin
                st_p       <= st_p + 16'd1;
                st_m_left  <= st_m_left - 17'(MT);
                st_c_panel <= st_c_panel + (cfg_ldc << $clog2(MT));
                st_c_tile  <= st_c_panel + (cfg_ldc << $clog2(MT));
              end
            end else begin
              st_j      <= st_j + 16'd1;
              st_n_left <= st_n_left - 17'(P);
              st_c_tile <= st_c_tile + AW'(P * 4);
            end
          end else begin
            st_kb <= st_kb + 1'b1;
          end
        end else begin
          st_active <= 1'b1;
          st_r      <= st_cur_r + 1'b1;
          st_addr   <= st_cur_addr + AAW'(cfg_kw);
        end
      end
    end
  end

  // ---- array control, delayed by the buffer read latency ----
  always_ff @(posedge clk) begin
    if (!rst_n) begin
      arr_in_valid <= 1'b0;
      arr_w_we     <= 1'b0;
    end else begin
      arr_in_valid <= st_issue;
      arr_w_we     <= wl_issue;
    end
    arr_in_bank <= st_bank;
    arr_in_tok  <= {st_accslot, st_cur_r[RW-2:0], (st_kb == '0), st_last_kb && st_last_row};
    arr_w_row   <= wl_cur_r;
    arr_w_bank  <= wl_bank;
  end

  // ---- status ----
  assign busy       = !st_done_all;
  assign stall_mem  = !st_issue && !st_done_all &&
                      (!a_full[st_aslot] || (!wl_ahead && !wl_active && !wl_done_all && !b_full[wl_bslot]));
  assign stall_acc  = !st_issue && !st_done_all && !stall_mem && (st_kb == '0) && !acc_free[st_accslot];
  assign stall_pipe = !st_issue && !st_done_all && !stall_mem && !stall_acc;
endmodule
