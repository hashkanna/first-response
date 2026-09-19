/* Capture mono PCM16 at 16 kHz without main-thread audio processing. */
class WarRoomPcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = new Float32Array(0);
    this.cursor = 0;
    this.ratio = sampleRate / 16000;
    this.frame = new ArrayBuffer(640); // 20 ms, 320 samples, little-endian PCM16.
    this.view = new DataView(this.frame);
    this.offset = 0;
    this.enabled = true;
    this.port.onmessage = ({ data }) => {
      this.enabled = data?.enabled !== false;
      this.pending = new Float32Array(0);
      this.cursor = 0;
      this.offset = 0;
    };
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!this.enabled || !channel?.length) return true;
    const combined = new Float32Array(this.pending.length + channel.length);
    combined.set(this.pending);
    combined.set(channel, this.pending.length);
    while (this.cursor + 1 < combined.length) {
      const index = Math.floor(this.cursor);
      const fraction = this.cursor - index;
      const sample = Math.max(-1, Math.min(1, combined[index] * (1 - fraction) + combined[index + 1] * fraction));
      this.view.setInt16(this.offset * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
      this.offset += 1;
      this.cursor += this.ratio;
      if (this.offset === 320) {
        this.port.postMessage(this.frame, [this.frame]);
        this.frame = new ArrayBuffer(640);
        this.view = new DataView(this.frame);
        this.offset = 0;
      }
    }
    const consumed = Math.min(Math.floor(this.cursor), combined.length);
    this.pending = combined.slice(consumed);
    this.cursor -= consumed;
    return true;
  }
}

registerProcessor('war-room-pcm-capture', WarRoomPcmCapture);
