import { useEffect, useRef } from "react";
import * as THREE from "three";
import {
  PARTICLE_COUNT,
  generateWave,
  generateStars,
  generateWaveColors,
  generateStarColors,
} from "./particles";

const STAR_COUNT = 2600;

function radialTexture(size: number, mid: number): THREE.Texture {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const r = size / 2;
  const g = ctx.createRadialGradient(r, r, 0, r, r, r);
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(mid, "rgba(255,255,255,0.5)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  return new THREE.CanvasTexture(canvas);
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (c.getContext("webgl") || c.getContext("experimental-webgl"))
    );
  } catch {
    return false;
  }
}

/** Fixed full-screen particle wave + star field. Raw three.js, scroll-reactive. */
export function ParticleScene({ scrollRef }: { scrollRef: React.MutableRefObject<number> }) {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount || !webglAvailable()) return;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(new THREE.Color("#050408"), 1);
    mount.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.set(0, 0, 9);

    // --- wave ---
    const basePositions = generateWave(PARTICLE_COUNT);
    const waveGeo = new THREE.BufferGeometry();
    waveGeo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(basePositions), 3));
    waveGeo.setAttribute("color", new THREE.BufferAttribute(generateWaveColors(PARTICLE_COUNT), 3));
    const waveTex = radialTexture(64, 0.45);
    const wave = new THREE.Points(
      waveGeo,
      new THREE.PointsMaterial({
        size: 0.044,
        map: waveTex,
        vertexColors: true,
        transparent: true,
        opacity: 0.92,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      }),
    );
    scene.add(wave);

    // --- stars ---
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute("position", new THREE.BufferAttribute(generateStars(STAR_COUNT), 3));
    starGeo.setAttribute("color", new THREE.BufferAttribute(generateStarColors(STAR_COUNT), 3));
    const starTex = radialTexture(32, 0.4);
    const stars = new THREE.Points(
      starGeo,
      new THREE.PointsMaterial({
        size: 0.04,
        map: starTex,
        vertexColors: true,
        transparent: true,
        opacity: 0.85,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
        sizeAttenuation: true,
      }),
    );
    scene.add(stars);

    let raf = 0;
    let t = 0;
    let last = performance.now();
    const wavePos = waveGeo.attributes.position.array as Float32Array;

    const tick = () => {
      const now = performance.now();
      const delta = Math.min((now - last) / 1000, 0.05);
      last = now;
      t += delta;
      const scroll = scrollRef.current;
      const time = t * 0.8;

      for (let i = 0; i < PARTICLE_COUNT; i++) {
        const x = basePositions[i * 3];
        const z = basePositions[i * 3 + 2];
        const waveY =
          Math.sin(x * 0.6 + time) * Math.cos(z * 0.5 + time * 0.5) * 1.0 +
          Math.sin(x * 0.3 - time * 0.2) * 0.5 +
          Math.cos(z * 0.8 + x * 0.2 + time * 0.4) * 0.4;
        wavePos[i * 3 + 1] = waveY + Math.sin(i * 133.7) * 0.04 - 1.2;
      }
      waveGeo.attributes.position.needsUpdate = true;

      wave.rotation.x = -0.2 + scroll * 0.15;
      wave.rotation.y = t * 0.04 + scroll * 0.3;
      stars.rotation.y += delta * 0.005;

      const targetZ = 9.0 + scroll * 2.0;
      const targetY = -1.1 + scroll * 0.8;
      camera.position.z += (targetZ - camera.position.z) * 0.04;
      camera.position.y += (targetY - camera.position.y) * 0.04;

      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);

    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      renderer.dispose();
      waveGeo.dispose();
      starGeo.dispose();
      waveTex.dispose();
      starTex.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
    };
  }, [scrollRef]);

  return <div ref={mountRef} className="particle-scene" aria-hidden="true" />;
}
