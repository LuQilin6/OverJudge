import { useRef, useState } from 'react';
import { motion, useMotionValue, useSpring, useTransform, useReducedMotion } from 'motion/react';
import { ArrowUpRight, Upload } from 'lucide-react';
import { Mascot } from './Mascot';
import '../scene.css';

export function ReplayScene({ onOpen, hasClip }: { onOpen: () => void; hasClip: boolean }) {
  const [greeting, setGreeting] = useState(false);
  const restoringFocus = useRef(false);
  const reduced = useReducedMotion();
  const px = useMotionValue(0), py = useMotionValue(0);
  const sx = useSpring(px, { stiffness: 55, damping: 24 });
  const sy = useSpring(py, { stiffness: 55, damping: 24 });
  const backgroundX = useTransform(sx, v => v * -8), backgroundY = useTransform(sy, v => v * -5);
  const characterX = useTransform(sx, v => v * 5);
  return <main className="room" onPointerMove={e => {
    if (reduced || e.pointerType !== 'mouse') return;
    px.set(e.clientX / window.innerWidth - .5); py.set(e.clientY / window.innerHeight - .5);
  }} onPointerLeave={() => { px.set(0); py.set(0); }}>
    <motion.div className="room-art" aria-hidden="true" style={{ x: reduced ? 0 : backgroundX, y: reduced ? 0 : backgroundY }} />
    <div className="room-shade" aria-hidden="true" />
    <header className="room-header">
      <a className="brand" href="/" aria-label="Was That My Fault home"><span className="brand-mark">?!</span><span>was that<br /><strong>my fault?</strong></span></a>
    </header>
    <motion.div className="character-stage" style={{ x: reduced ? 0 : characterX }}>
      <button className="character-button" aria-label="Talk to the dog referee" aria-haspopup="dialog" onClick={() => {
        restoringFocus.current = true; setGreeting(false); onOpen();
      }} onPointerEnter={() => setGreeting(true)} onPointerLeave={() => setGreeting(false)}
        onFocus={() => { setGreeting(!restoringFocus.current); restoringFocus.current = false; }} onBlur={() => setGreeting(false)}>
        <Mascot pose={greeting ? 'greeting' : 'idle'} bob />
      </button>
    </motion.div>
    <div className="court-bench" aria-hidden="true">
      <img src="/images/courts/foreground-bench.png" alt="" width="2172" height="724" draggable={false} />
      <span className="bench-contact-shadow" />
    </div>
    <section className="judge-dialogue" aria-labelledby="welcome-title">
      <p className="dialogue-kicker"><span /> YOUR REPLAY. A SECOND OPINION.</p>
      <h1 id="welcome-title">Was that<br /><em>your fault?</em></h1>
      <p className="dialogue-message">Show me the fight. One perspective or the whole squad.</p>
      <button className="primary-button dialogue-upload" onClick={onOpen} aria-haspopup="dialog"><Upload size={18} />{hasClip ? 'Back to your clip' : 'Upload a clip'}<ArrowUpRight size={18} /></button>
      <p className="dialogue-details">Overwatch <span>·</span> 10–90 seconds <span>·</span> Evidence review</p>
    </section>
    <footer className="room-about"><details onKeyDown={e => {
      if (e.key === 'Escape') { e.currentTarget.open = false; e.currentTarget.querySelector('summary')?.focus(); }
    }}><summary>About</summary><div className="about-card"><strong>Small paws. Fair calls.</strong><p>An independent Overwatch companion. Not affiliated with Blizzard.</p><p>No flame. Just frames. One fight, a fair call, and something to learn.</p></div></details></footer>
  </main>;
}
