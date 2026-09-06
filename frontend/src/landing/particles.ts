/** Particle-field geometry for the landing scene (pure math, no three import). */

export const PARTICLE_COUNT = 26000;

function randRange(a: number, b: number) {
  return a + Math.random() * (b - a);
}

export function generateWave(count: number): Float32Array {
  const pos = new Float32Array(count * 3);
  const cols = Math.ceil(Math.sqrt(count * 2.5));
  const rows = Math.ceil(count / cols);
  let idx = 0;
  for (let r = 0; r < rows && idx < count; r++) {
    for (let c = 0; c < cols && idx < count; c++) {
      const x = (c / cols - 0.5) * 18;
      const z = (r / rows - 0.3) * 10;
      const wave =
        Math.sin(x * 0.6 + 1.0) * Math.cos(z * 0.5) * 1.0 +
        Math.sin(x * 0.3) * 0.5 +
        Math.cos(z * 0.8 + x * 0.2) * 0.4;
      const jitter = (Math.random() - 0.5) * 0.15;
      pos[idx * 3] = x + jitter;
      pos[idx * 3 + 1] = wave + (Math.random() - 0.5) * 0.08 - 1.2;
      pos[idx * 3 + 2] = z;
      idx++;
    }
  }
  return pos;
}

export function generateStars(count: number): Float32Array {
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const r = randRange(8, 60);
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(randRange(-1, 1));
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta) * 0.6;
    pos[i * 3 + 2] = r * Math.cos(phi);
  }
  return pos;
}

/** Warm gold / deep-ember palette to match the Checkout Copilot accent. */
export function generateWaveColors(count: number): Float32Array {
  const col = new Float32Array(count * 3);
  const gold = [240 / 255, 192 / 255, 96 / 255];
  const ember = [150 / 255, 70 / 255, 20 / 255];
  for (let i = 0; i < count; i++) {
    const color = Math.random() < 0.55 ? gold : ember;
    col[i * 3] = color[0];
    col[i * 3 + 1] = color[1];
    col[i * 3 + 2] = color[2];
  }
  return col;
}

export function generateStarColors(count: number): Float32Array {
  const col = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const brightness = 0.5 + Math.random() * 0.5;
    const hue = Math.random();
    if (hue < 0.72) {
      col[i * 3] = brightness;
      col[i * 3 + 1] = brightness;
      col[i * 3 + 2] = brightness;
    } else {
      col[i * 3] = brightness;
      col[i * 3 + 1] = brightness * 0.82;
      col[i * 3 + 2] = brightness * 0.5;
    }
  }
  return col;
}
