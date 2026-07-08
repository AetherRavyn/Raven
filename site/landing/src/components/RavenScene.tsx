import { useRef, useMemo } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

/** A raven silhouette as an extruded 3D shape that slowly breathes. */
function Raven({ mouse }: { mouse: React.MutableRefObject<{ x: number; y: number }> }) {
  const group = useRef<THREE.Group>(null);
  const matRef = useRef<THREE.MeshStandardMaterial>(null);

  // Build a raven profile silhouette path (stylized, symmetric-ish).
  const shape = useMemo(() => {
    const s = new THREE.Shape();
    // Head + beak (left), body curve, wing, tail.
    s.moveTo(0, 1.55);
    s.bezierCurveTo(0.18, 1.5, 0.32, 1.35, 0.3, 1.15);
    s.bezierCurveTo(0.62, 1.18, 0.95, 0.95, 1.05, 0.6);
    s.bezierCurveTo(1.12, 0.3, 0.9, 0.05, 0.55, -0.15);
    s.bezierCurveTo(0.78, -0.35, 0.82, -0.7, 0.5, -1.0);
    s.bezierCurveTo(0.32, -1.2, 0.1, -1.15, 0, -0.95);
    s.bezierCurveTo(-0.1, -1.15, -0.32, -1.2, -0.5, -1.0);
    s.bezierCurveTo(-0.82, -0.7, -0.78, -0.35, -0.55, -0.15);
    s.bezierCurveTo(-0.9, 0.05, -1.12, 0.3, -1.05, 0.6);
    s.bezierCurveTo(-0.95, 0.95, -0.62, 1.18, -0.3, 1.15);
    s.bezierCurveTo(-0.32, 1.35, -0.18, 1.5, 0, 1.55);
    return s;
  }, []);

  const geo = useMemo(() => new THREE.ExtrudeGeometry(shape, {
    depth: 0.18,
    bevelEnabled: true,
    bevelThickness: 0.05,
    bevelSize: 0.04,
    bevelSegments: 4,
  }), [shape]);

  useFrame((state) => {
    const t = state.clock.elapsedTime;
    if (group.current) {
      // Breathing
      const breathe = 1 + Math.sin(t * 1.05) * 0.012;
      group.current.scale.set(breathe, breathe, breathe);
      // Gentle float + parallax to mouse
      group.current.position.y = Math.sin(t * 0.5) * 0.08;
      group.current.rotation.y = mouse.current.x * 0.35 + Math.sin(t * 0.2) * 0.05;
      group.current.rotation.x = -mouse.current.y * 0.2;
    }
    if (matRef.current) {
      matRef.current.emissiveIntensity = 0.35 + Math.sin(t * 1.05) * 0.12;
    }
  });

  return (
    <group ref={group}>
      <mesh geometry={geo} castShadow>
        <meshStandardMaterial
          ref={matRef}
          color="#0a0a0a"
          emissive="#c8102e"
          emissiveIntensity={0.4}
          metalness={0.7}
          roughness={0.35}
        />
      </mesh>
    </group>
  );
}

/** Drifting dust / ember particles in a slow vortex. */
function Particles({ count = 600 }: { count?: number }) {
  const ref = useRef<THREE.Points>(null);
  const positions = useMemo(() => {
    const arr = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 4 + Math.random() * 6;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = (Math.random() - 0.5) * 10;
      arr[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta) - 4;
    }
    return arr;
  }, [count]);

  useFrame((state, delta) => {
    if (ref.current) {
      ref.current.rotation.y += delta * 0.02;
    }
  });

  return (
    <points ref={ref}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        size={0.025}
        color="#c8102e"
        transparent
        opacity={0.6}
        sizeAttenuation
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}

/** Volumetric fog plane with a soft radial gradient (moonlight). */
function MoonGlow() {
  const tex = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = c.height = 256;
    const ctx = c.getContext("2d")!;
    const g = ctx.createRadialGradient(128, 96, 10, 128, 128, 128);
    g.addColorStop(0, "rgba(200,16,46,0.5)");
    g.addColorStop(0.4, "rgba(120,10,30,0.15)");
    g.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  }, []);
  return (
    <mesh position={[0, 1.6, -5]} scale={[14, 9, 1]}>
      <planeGeometry />
      <meshBasicMaterial map={tex} transparent depthWrite={false} blending={THREE.AdditiveBlending} />
    </mesh>
  );
}

export default function RavenScene() {
  const mouse = useRef({ x: 0, y: 0 });
  return (
    <div className="absolute inset-0">
      <Canvas
        camera={{ position: [0, 0, 6], fov: 45 }}
        gl={{ antialias: true, alpha: true }}
        dpr={[1, 2]}
        onCreated={({ gl }) => gl.setClearColor(0x000000, 0)}
      >
        <ambientLight intensity={0.4} />
        <spotLight position={[0, 6, 4]} angle={0.5} penumbra={1} intensity={2} color="#c8102e" />
        <pointLight position={[-4, -2, 3]} intensity={0.5} color="#3a0008" />
        <MoonGlow />
        <Raven mouse={mouse} />
        <Particles count={700} />
      </Canvas>
      <div
        onMouseMove={(e) => {
          mouse.current.x = (e.clientX / window.innerWidth) * 2 - 1;
          mouse.current.y = (e.clientY / window.innerHeight) * 2 - 1;
        }}
        className="absolute inset-0"
      />
    </div>
  );
}
