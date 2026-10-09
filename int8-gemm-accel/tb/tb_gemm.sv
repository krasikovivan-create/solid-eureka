// Top-level testbench: loads a memory image, programs the accelerator through
// its CSRs, waits for completion, prints the performance counters and dumps
// the C region. Driven by sim/accel_sim.py.
//
// Plusargs: +MEMFILE= +OUTFILE= +TIMEOUT= and either +JOBS=<file> (several jobs
// run back to back, one per line: M N K ADDR_A ADDR_B ADDR_C LDA LDB LDC) or a
// single job given by +M= +N= +K= +ADDR_A= +ADDR_B= +ADDR_C= +LDA= +LDB= +LDC=.
// Memory knobs for mem_model: +LAT= +BWNUM= +BWDEN=. C of job i -> OUTFILE.i
`timescale 1ns/1ps
module tb_gemm;
  parameter int P     = 16;
  parameter int MT    = 128;
  parameter int KMAX  = 1024;
  parameter int N_DSP = P * P;
  parameter int WORDS = 1 << 19;
  localparam int BUS = P;
  localparam int AW  = 32;

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  logic             csr_we = 1'b0;
  logic [7:0]       csr_addr = 8'h00;
  logic [31:0]      csr_wdata = 32'd0;
  logic [31:0]      csr_rdata;
  logic             irq_done;
  logic             rd_req_valid, rd_req_ready, rd_rsp_valid;
  logic [AW-1:0]    rd_req_addr;
  logic [7:0]       rd_req_len;
  logic [BUS*8-1:0] rd_rsp_data;
  logic             wr_valid, wr_ready;
  logic [AW-1:0]    wr_addr;
  logic [BUS*8-1:0] wr_data;
  logic [BUS-1:0]   wr_strb;

  gemm_accel_top #(.P(P), .MT(MT), .KMAX(KMAX), .N_DSP(N_DSP), .AW(AW)) dut (
    .clk(clk), .rst_n(rst_n),
    .csr_we(csr_we), .csr_addr(csr_addr), .csr_wdata(csr_wdata), .csr_rdata(csr_rdata),
    .irq_done(irq_done),
    .mem_rd_req_valid(rd_req_valid), .mem_rd_req_ready(rd_req_ready),
    .mem_rd_req_addr(rd_req_addr), .mem_rd_req_len(rd_req_len),
    .mem_rd_rsp_valid(rd_rsp_valid), .mem_rd_rsp_data(rd_rsp_data),
    .mem_wr_valid(wr_valid), .mem_wr_ready(wr_ready), .mem_wr_addr(wr_addr),
    .mem_wr_data(wr_data), .mem_wr_strb(wr_strb)
  );

  mem_model #(.BUS(BUS), .AW(AW), .WORDS(WORDS)) mem (
    .clk(clk), .rst_n(rst_n),
    .rd_req_valid(rd_req_valid), .rd_req_ready(rd_req_ready),
    .rd_req_addr(rd_req_addr), .rd_req_len(rd_req_len),
    .rd_rsp_valid(rd_rsp_valid), .rd_rsp_data(rd_rsp_data),
    .wr_valid(wr_valid), .wr_ready(wr_ready), .wr_addr(wr_addr),
    .wr_data(wr_data), .wr_strb(wr_strb)
  );

  task automatic csr_wr(input logic [7:0] a, input logic [31:0] d);
    @(negedge clk);
    csr_we = 1'b1; csr_addr = a; csr_wdata = d;
    @(negedge clk);
    csr_we = 1'b0;
  endtask

  task automatic csr_rd(input logic [7:0] a, output logic [31:0] d);
    @(negedge clk);
    csr_addr = a;
    #1 d = csr_rdata;
  endtask

  string  memfile, outfile, jobfile;
  integer m, n, k, addr_a, addr_b, addr_c, lda, ldb, ldc, timeout;
  integer polls, job, fd, nread;
  logic [31:0] status, val;

  // Runs one job: program the CSRs, start, wait for done, report, dump C.
  task automatic run_job(input integer idx);
    csr_wr(8'h08, m);
    csr_wr(8'h0C, n);
    csr_wr(8'h10, k);
    csr_wr(8'h14, addr_a);
    csr_wr(8'h18, addr_b);
    csr_wr(8'h1C, addr_c);
    csr_wr(8'h20, lda);
    csr_wr(8'h24, ldb);
    csr_wr(8'h28, ldc);
    csr_wr(8'h00, 32'd1);
    polls = 0;
    do begin
      csr_rd(8'h04, status);
      polls = polls + 1;
    end while (!status[1] && polls < timeout);
    if (!status[1]) begin
      $display("JOB %0d RESULT TIMEOUT after %0d cycles", idx, polls);
      $finish;
    end
    $display("JOB %0d RESULT %s", idx, status[2] ? "ERROR" : "OK");
    csr_rd(8'h30, val); $display("PERF %0d cycles %0d", idx, val);
    csr_rd(8'h34, val); $display("PERF %0d busy %0d", idx, val);
    csr_rd(8'h38, val); $display("PERF %0d stall_mem %0d", idx, val);
    csr_rd(8'h3C, val); $display("PERF %0d stall_acc %0d", idx, val);
    csr_rd(8'h40, val); $display("PERF %0d stall_pipe %0d", idx, val);
    csr_rd(8'h44, val); $display("PERF %0d tail %0d", idx, val);
    csr_rd(8'h48, val); $display("PERF %0d rd_beats %0d", idx, val);
    csr_rd(8'h4C, val); $display("PERF %0d wr_beats %0d", idx, val);
    if (!status[2])
      $writememh($sformatf("%s.%0d", outfile, idx), mem.mem, addr_c / BUS, (addr_c + m * ldc) / BUS - 1);
  endtask

  initial begin
    if (!$value$plusargs("MEMFILE=%s", memfile)) memfile = "mem.hex";
    if (!$value$plusargs("OUTFILE=%s", outfile)) outfile = "c_out.hex";
    if (!$value$plusargs("TIMEOUT=%d", timeout)) timeout = 50000000;

    $readmemh(memfile, mem.mem);
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
    repeat (2) @(posedge clk);

    csr_rd(8'h50, val);
    $display("HWCFG P=%0d BUS=%0d log2MT=%0d log2KMAX=%0d", val[7:0], val[15:8], val[23:16], val[31:24]);

    if ($value$plusargs("JOBS=%s", jobfile)) begin
      // one job per line: M N K ADDR_A ADDR_B ADDR_C LDA LDB LDC
      fd = $fopen(jobfile, "r");
      if (fd == 0) $fatal(1, "cannot open %s", jobfile);
      job = 0;
      nread = $fscanf(fd, "%d %d %d %d %d %d %d %d %d", m, n, k, addr_a, addr_b, addr_c, lda, ldb, ldc);
      while (nread == 9) begin
        run_job(job);
        job = job + 1;
        nread = $fscanf(fd, "%d %d %d %d %d %d %d %d %d", m, n, k, addr_a, addr_b, addr_c, lda, ldb, ldc);
      end
      $fclose(fd);
    end else begin
      if (!$value$plusargs("M=%d", m)) m = 16;
      if (!$value$plusargs("N=%d", n)) n = 16;
      if (!$value$plusargs("K=%d", k)) k = 16;
      if (!$value$plusargs("ADDR_A=%d", addr_a)) addr_a = 0;
      if (!$value$plusargs("ADDR_B=%d", addr_b)) addr_b = 0;
      if (!$value$plusargs("ADDR_C=%d", addr_c)) addr_c = 0;
      if (!$value$plusargs("LDA=%d", lda)) lda = k;
      if (!$value$plusargs("LDB=%d", ldb)) ldb = n;
      if (!$value$plusargs("LDC=%d", ldc)) ldc = 4 * n;
      run_job(0);
    end
    $finish;
  end
endmodule
