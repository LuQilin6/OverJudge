const MAX_FILE_BYTES = 200 * 1024 * 1024;

export function checkFile(file: File) {
  if (file.size > MAX_FILE_BYTES) throw new Error('This clip is over 200 MB. Export a shorter or smaller clip.');
  if (!['video/mp4', 'video/webm'].includes(file.type) && !/\.(mp4|webm)$/i.test(file.name)) {
    throw new Error('Choose an MP4 or WebM video.');
  }
}

export function checkDuration(duration: number) {
  if (!Number.isFinite(duration) || duration < 10 || duration > 90) {
    throw new Error('Choose a clip between 10 and 90 seconds. Trim longer recordings before uploading.');
  }
}

function waitForVideo(video: HTMLVideoElement, event: string, signal: AbortSignal, action: () => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const cleanup = () => { clearTimeout(timer); video.removeEventListener(event, done); video.removeEventListener('error', fail); signal.removeEventListener('abort', abort); };
    const done = () => { cleanup(); resolve(); };
    const fail = () => { cleanup(); reject(new Error('This video could not be decoded. Export it as an H.264 MP4 or a playable WebM.')); };
    const abort = () => { cleanup(); reject(new DOMException('Cancelled', 'AbortError')); };
    const timer = setTimeout(fail, 15_000);
    video.addEventListener(event, done, { once: true });
    video.addEventListener('error', fail, { once: true });
    signal.addEventListener('abort', abort, { once: true });
    if (signal.aborted) { abort(); return; }
    try { action(); } catch { fail(); }
  });
}

export function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60).toString().padStart(2, '0');
  const wholeSeconds = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${minutes}:${wholeSeconds}${seconds % 1 >= 0.5 ? '.5' : ''}`;
}

export async function inspectDuration(url: string, signal: AbortSignal): Promise<number> {
  const video = document.createElement('video');
  video.preload = 'metadata';
  try {
    await waitForVideo(video, 'loadedmetadata', signal, () => { video.src = url; video.load(); });
    checkDuration(video.duration);
    return video.duration;
  } finally { video.removeAttribute('src'); video.load(); }
}
