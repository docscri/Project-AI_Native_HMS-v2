// Ported from Project-Dictate: low-pass and resample any mic rate to 16 kHz mono 16-bit PCM for Deepgram.
class PCMEncoder {
  constructor(inputRate, onFrame, frameSamples = 320) {
    this.ratio = inputRate / 16000;
    this.remaining = this.ratio; this.sum = 0;
    this.frame = new ArrayBuffer(frameSamples * 2); this.offset = 0;
    this.view = new DataView(this.frame);
    this.onFrame = onFrame; this.frameSamples = frameSamples;
    this.history = new Float32Array(31); this.head = 0;
    const cutoff = Math.min(0.45, 7200 / inputRate);
    const taps = Array.from({ length: 31 }, (_, i) => {
      const x = i - 15;
      return (x === 0 ? 2 * cutoff : Math.sin(2 * Math.PI * cutoff * x) / (Math.PI * x)) * (0.54 - 0.46 * Math.cos(2 * Math.PI * i / 30));
    });
    const scale = taps.reduce((a, b) => a + b, 0);
    this.taps = taps.map(tap => tap / scale);
  }
  push(channels) {
    if (!channels.length) return;
    for (let index = 0; index < channels[0].length; index += 1) {
      let value = 0;
      for (const channel of channels) value += channel[index] ?? 0;
      this.history[this.head] = value / channels.length;
      let filtered = 0;
      for (let tap = 0; tap < this.taps.length; tap += 1) filtered += this.taps[tap] * this.history[(this.head - tap + 31) % 31];
      this.head = (this.head + 1) % 31;
      let available = 1;
      while (available > 1e-9) {
        const amount = Math.min(available, this.remaining);
        this.sum += filtered * amount; this.remaining -= amount; available -= amount;
        if (this.remaining < 1e-9) {
          const sample = Math.max(-1, Math.min(1, this.sum / this.ratio));
          this.view.setInt16(this.offset * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
          this.offset += 1; this.sum = 0; this.remaining = this.ratio;
          if (this.offset === this.frameSamples) { this.onFrame(this.frame); this.frame = new ArrayBuffer(this.frameSamples * 2); this.view = new DataView(this.frame); this.offset = 0; }
        }
      }
    }
  }
  flush() { if (this.offset) { this.onFrame(this.frame.slice(0, this.offset * 2)); this.offset = 0; } }
}

class PCMCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.encoder = new PCMEncoder(sampleRate, frame => this.port.postMessage({ type: "audio", frame }, [frame]));
    this.port.onmessage = ({ data }) => { if (data === "flush") { this.encoder.flush(); this.port.postMessage({ type: "flushed" }); } };
  }
  process(inputs) { this.encoder.push(inputs[0] ?? []); return true; }
}
registerProcessor("dictate-pcm", PCMCaptureProcessor);
