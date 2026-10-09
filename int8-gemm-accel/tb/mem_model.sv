// Behavioral model of the shared (unified) memory. SIMULATION ONLY.
//
// * Read requests (addr, len beats) are queued; each request's data becomes
//   available LAT cycles after the request was accepted, beats are returned in
//   request order.
// * Read and write beats share one bandwidth budget: at most BWNUM/BWDEN beats
//   per cycle (default 1 beat = BUS bytes per cycle), round-robin between
//   read data and write data when both compete.
// Run-time knobs (plusargs): +LAT=<cycles> +BWNUM=<n> +BWDEN=<d>
module mem_model #(
  parameter int BUS    = 16,
  parameter int AW     = 32,
  parameter int WORDS  = 1 << 19,
  parameter int QDEPTH = 256
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             rd_req_valid,
  output logic             rd_req_ready,
  input  logic [AW-1:0]    rd_req_addr,
  input  logic [7:0]       rd_req_len,
  output logic             rd_rsp_valid,
  output logic [BUS*8-1:0] rd_rsp_data,
  input  logic             wr_valid,
  output logic             wr_ready,
  input  logic [AW-1:0]    wr_addr,
  input  logic [BUS*8-1:0] wr_data,
  input  logic [BUS-1:0]   wr_strb
);
  logic [BUS*8-1:0] mem [0:WORDS-1];

  integer lat, bw_num, bw_den;
  initial begin
    if (!$value$plusargs("LAT=%d", lat))     lat    = 32;
    if (!$value$plusargs("BWNUM=%d", bw_num)) bw_num = 1;
    if (!$value$plusargs("BWDEN=%d", bw_den)) bw_den = 1;
  end

  logic [AW-1:0] q_addr [0:QDEPTH-1];
  logic [7:0]    q_len  [0:QDEPTH-1];
  logic [63:0]   q_time [0:QDEPTH-1];
  integer        q_head, q_tail, q_count;
  logic [63:0]   now;
  integer        credit;
  logic          rr;            // 1: write wins a conflict this cycle
  logic          head_ready, can_beat, do_rd, do_wr, push;
  integer        credit_next;

  always_comb begin
    head_ready   = (q_count > 0) && (now >= q_time[q_head] + 64'(lat));
    can_beat     = (credit >= bw_den);
    rd_req_ready = (q_count < QDEPTH);
    wr_ready     = can_beat && (!head_ready || rr);
    do_wr        = wr_valid && wr_ready;
    do_rd        = can_beat && head_ready && !do_wr;
    push         = rd_req_valid && rd_req_ready;
    credit_next  = ((do_rd || do_wr) ? credit - bw_den : credit) + bw_num;
    if (credit_next > bw_den) credit_next = bw_den;
  end

  always @(posedge clk) begin
    if (!rst_n) begin
      q_head <= 0; q_tail <= 0; q_count <= 0;
      now <= 64'd0; credit <= bw_den; rr <= 1'b0;
      rd_rsp_valid <= 1'b0;
    end else begin
      now <= now + 64'd1;
      credit <= credit_next;
      if (do_rd || do_wr) rr <= ~rr;

      if (push) begin
        if ((rd_req_addr % BUS) != 0 || (rd_req_addr / BUS) + rd_req_len > WORDS || rd_req_len == 0)
          $fatal(1, "mem_model: bad read request addr=0x%0h len=%0d", rd_req_addr, rd_req_len);
        q_addr[q_tail] <= rd_req_addr;
        q_len[q_tail]  <= rd_req_len;
        q_time[q_tail] <= now;
        q_tail <= (q_tail + 1) % QDEPTH;
      end

      rd_rsp_valid <= do_rd;
      if (do_rd) begin
        rd_rsp_data <= mem[q_addr[q_head] / BUS];
        if (q_len[q_head] == 8'd1) begin
          q_head <= (q_head + 1) % QDEPTH;
        end else begin
          q_addr[q_head] <= q_addr[q_head] + BUS;
          q_len[q_head]  <= q_len[q_head] - 8'd1;
        end
      end
      q_count <= q_count + (push ? 1 : 0) - ((do_rd && q_len[q_head] == 8'd1) ? 1 : 0);

      if (do_wr) begin
        if ((wr_addr % BUS) != 0 || (wr_addr / BUS) >= WORDS)
          $fatal(1, "mem_model: bad write addr=0x%0h", wr_addr);
        for (int b = 0; b < BUS; b = b + 1)
          if (wr_strb[b]) mem[wr_addr / BUS][b*8 +: 8] <= wr_data[b*8 +: 8];
      end
    end
  end
endmodule
