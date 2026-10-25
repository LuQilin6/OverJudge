import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';

export type MascotPose = 'idle' | 'greeting' | 'examining' | 'presenting';
const poses: MascotPose[] = ['idle', 'greeting', 'examining', 'presenting'];

export function Mascot({ pose = 'idle', bob = false }: { pose?: MascotPose; bob?: boolean }) {
  const reduced = useReducedMotion();
  const [failed, setFailed] = useState<string[]>([]);
  const [ready, setReady] = useState<string[]>([]);
  useEffect(() => {
    const images = poses.map(p => {
      const img = new Image();
      img.onload = () => setReady(current => [...current, p]);
      img.onerror = () => setFailed(current => [...current, p]);
      img.src = `/images/doggo/${p}.png`;
      return img;
    });
    return () => images.forEach(img => { img.onload = null; img.onerror = null; });
  }, []);
  const active = ready.includes(pose) && !failed.includes(pose) ? pose : 'idle';
  return <motion.span className="mascot" aria-hidden="true"
    animate={bob && !reduced ? { y: [0, -5, 0] } : { y: 0 }}
    transition={bob && !reduced ? { duration: 4.5, repeat: Infinity, ease: 'easeInOut' } : { duration: 0 }}>
    {failed.includes('idle') && <span className="mascot-fallback">🐶</span>}
    {poses.map(p => <motion.img key={p} src={`/images/doggo/${p}.png`} alt="" width="1280" height="1280"
      draggable={false} initial={false} animate={{ opacity: p === active && !failed.includes(p) ? 1 : 0 }}
      transition={{ duration: reduced ? 0 : .2 }} onLoad={() => setReady(current => current.includes(p) ? current : [...current, p])}
      onError={() => setFailed(current => current.includes(p) ? current : [...current, p])} />)}
  </motion.span>;
}
