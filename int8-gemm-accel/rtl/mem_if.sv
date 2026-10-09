// Shared-memory interface of the accelerator.
//
// External port (to the unified memory / interconnect):
//   read request  : rd_req_{valid,ready,addr,len}  (len = beats, addr BUS-aligned)
//   read response : rd_rsp_{valid,data}            (in order, no back-pressure:
//                                                  requests are issued only for
//                                                  reserved buffer space)
//   write         : wr_{valid,ready,addr,data,strb} (one beat per handshake)
// All outgoing channels go through register slices; responses are registered.
// Beat counters feed the performance registers.
module mem_if #(
  parameter int BUS = 16,   // bytes per beat
  parameter int AW  = 32
) (
  input  logic             clk,
  input  logic             rst_n,
  input  logic             cnt_clear,
  // internal side: read DMA
  input  logic             dma_req_valid,
  output logic             dma_req_ready,
  input  logic [AW-1:0]    dma_req_addr,
  input  logic [7:0]       dma_req_len,
  output logic             dma_rsp_valid,
  output logic [BUS*8-1:0] dma_rsp_data,
  // internal side: write DMA
  input  logic             dma_wr_valid,
  output logic             dma_wr_ready,
  input  logic [AW-1:0]    dma_wr_addr,
  input  logic [BUS*8-1:0] dma_wr_data,
  input  logic [BUS-1:0]   dma_wr_strb,
  // external side
  output logic             rd_req_valid,
  input  logic             rd_req_ready,
  output logic [AW-1:0]    rd_req_addr,
  output logic [7:0]       rd_req_len,
  input  logic             rd_rsp_valid,
  input  logic [BUS*8-1:0] rd_rsp_data,
  output logic             wr_valid,
  input  logic             wr_ready,
  output logic [AW-1:0]    wr_addr,
  output logic [BUS*8-1:0] wr_data,
  output logic [BUS-1:0]   wr_strb,
  // statistics
  output logic [31:0]      rd_beats,
  output logic [31:0]      wr_beats
);
  reg_slice #(.W(AW + 8)) u_rd_req (
    .clk(clk), .rst_n(rst_n),
    .s_valid(dma_req_valid), .s_ready(dma_req_ready), .s_data({dma_req_addr, dma_req_len}),
    .m_valid(rd_req_valid),  .m_ready(rd_req_ready),  .m_data({rd_req_addr, rd_req_len}));

  reg_slice #(.W(AW + BUS * 8 + BUS)) u_wr (
    .clk(clk), .rst_n(rst_n),
    .s_valid(dma_wr_valid), .s_ready(dma_wr_ready), .s_data({dma_wr_addr, dma_wr_data, dma_wr_strb}),
    .m_valid(wr_valid),     .m_ready(wr_ready),     .m_data({wr_addr, wr_data, wr_strb}));

  always_ff @(posedge clk) begin
    if (!rst_n) dma_rsp_valid <= 1'b0;
    else        dma_rsp_valid <= rd_rsp_valid;
    dma_rsp_data <= rd_rsp_data;
  end

  always_ff @(posedge clk) begin
    if (!rst_n || cnt_clear) begin
      rd_beats <= '0;
      wr_beats <= '0;
    end else begin
      if (rd_rsp_valid)          rd_beats <= rd_beats + 32'd1;
      if (wr_valid && wr_ready)  wr_beats <= wr_beats + 32'd1;
    end
  end
endmodule
