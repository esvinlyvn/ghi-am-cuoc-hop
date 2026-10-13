// AudioWorklet: trộn mọi kênh về mono, chuyển sang PCM 16-bit và gửi từng khối 4096 mẫu.
// Chạy trên luồng âm thanh của trình duyệt nên không bị giật khi trang ở nền.
class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = 4096;
    this.buf = new Int16Array(this.size);
    this.n = 0;
  }
  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const chans = input.length, len = input[0].length;
    for (let i = 0; i < len; i++) {
      let s = 0;
      for (let c = 0; c < chans; c++) s += input[c][i];
      s = s / chans;
      if (s > 1) s = 1; else if (s < -1) s = -1;
      this.buf[this.n++] = s < 0 ? s * 32768 : s * 32767;
      if (this.n === this.size) {
        const out = this.buf;
        this.buf = new Int16Array(this.size);
        this.n = 0;
        this.port.postMessage(out.buffer, [out.buffer]);
      }
    }
    return true;
  }
}
registerProcessor('pcm-capture', PCMCaptureProcessor);
