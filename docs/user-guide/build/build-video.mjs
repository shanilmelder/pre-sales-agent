// Build the narrated product tour: ElevenLabs voice per scene, ffmpeg Ken Burns per screenshot.
//   node build-video.mjs <repo> <shots dir> <work dir>
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [REPO, SHOTS, WORK] = process.argv.slice(2);
const OUT = join(REPO, "docs/user-guide");
const VOICE = process.env.VOICE_ID ?? "Xb7hH8MSUJpSbSDYk0k2"; // Alice, clear British educator
const MODEL = "eleven_multilingual_v2";
const FPS = 30, W = 1920, H = 1200, LEAD = 0.35, TAIL = 0.75;
const FONT = "C\\:/Windows/Fonts/segoeuib.ttf";
const FONT_R = "C\\:/Windows/Fonts/segoeui.ttf";

const env = readFileSync(join(REPO, ".env"), "utf8");
const KEY = env.match(/^ELEVENLABS_API_KEY=(.*)$/m)[1].trim().replace(/^["']|["']$/g, "");
const scenes = JSON.parse(readFileSync(join(OUT, "scenes.json"), "utf8"));
for (const d of ["audio", "seg", "txt"]) mkdirSync(join(WORK, d), { recursive: true });

const ff = (args) => execFileSync("ffmpeg", ["-v", "error", "-y", ...args], { stdio: "inherit" });
const dur = (f) =>
  Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f]).toString());

async function tts(i, s) {
  const file = join(WORK, "audio", `${String(i).padStart(2, "0")}.mp3`);
  const stamp = file + ".txt";
  if (existsSync(file) && existsSync(stamp) && readFileSync(stamp, "utf8") === VOICE + s.say) return file;
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${VOICE}?output_format=mp3_44100_128`, {
    method: "POST",
    headers: { "xi-api-key": KEY, "Content-Type": "application/json" },
    body: JSON.stringify({
      text: s.say,
      model_id: MODEL,
      previous_text: scenes[i - 1]?.say,
      next_text: scenes[i + 1]?.say,
      voice_settings: { stability: 0.55, similarity_boost: 0.75, style: 0.15, use_speaker_boost: true },
    }),
  });
  if (!res.ok) throw new Error(`tts ${i}: ${res.status} ${await res.text()}`);
  writeFileSync(file, Buffer.from(await res.arrayBuffer()));
  writeFileSync(stamp, VOICE + s.say);
  console.log(`tts ${i} ok`);
  return file;
}

// Title card: build/title-card.html rendered to <shots>/000-title-card.png (1920x1200).
const TITLE_S = 4.5;
const title = join(WORK, "seg", "000-title.mp4");
ff([
  "-loop", "1", "-framerate", String(FPS), "-i", join(SHOTS, "000-title-card.png"),
  "-vf", `scale=${W}:${H}:flags=lanczos,format=yuv420p,fade=in:0:18,fade=out:st=${TITLE_S - 0.5}:d=0.5`,
  "-frames:v", String(TITLE_S * FPS), "-an",
  "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "stillimage", "-pix_fmt", "yuv420p", title,
]);

const segs = [title];
const voices = [];
const srt = [];
let clock = 3.5;
const ts = (t) => {
  const ms = Math.round(t * 1000);
  const p = (n, w = 2) => String(n).padStart(w, "0");
  return `${p(Math.floor(ms / 3600000))}:${p(Math.floor(ms / 60000) % 60)}:${p(Math.floor(ms / 1000) % 60)},${p(ms % 1000, 3)}`;
};

for (let i = 0; i < scenes.length; i++) {
  const s = scenes[i];
  const audio = await tts(i, s);
  const a = dur(audio);
  const d = +(LEAD + a + TAIL).toFixed(3);
  const frames = Math.ceil(d * FPS);
  const seg = join(WORK, "seg", `${String(i + 1).padStart(3, "0")}.mp4`);
  const label = join(WORK, "txt", `c${i}.txt`);
  writeFileSync(label, s.chapter);
  const lab = label.replace(/\\/g, "/").replace(":", "\\:");
  const png = join(SHOTS, `${s.img}.png`);
  // A segment is only video; it is rebuilt when its screenshot or narration is newer.
  const fresh = existsSync(seg) && statSync(seg).mtimeMs > Math.max(statSync(png).mtimeMs, statSync(audio).mtimeMs);
  if (!fresh) {
    ff([
      "-loop", "1", "-framerate", String(FPS), "-i", png,
      "-filter_complex",
      `[0]scale=${W}:${H}:flags=lanczos,format=yuv420p,` +
        `drawtext=fontfile='${FONT}':textfile='${lab}':fontsize=28:fontcolor=white:box=1:boxcolor=0x4f46e5@0.92:boxborderw=18:x=w-tw-48:y=h-th-48,` +
        `fade=in:0:8,fade=out:st=${(d - 0.3).toFixed(2)}:d=0.3[v]`,
      "-map", "[v]", "-frames:v", String(frames), "-an",
      "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-tune", "stillimage", "-pix_fmt", "yuv420p", seg,
    ]);
  }
  segs.push(seg);
  voices.push({ audio, a });
  console.log(`seg ${i + 1}/${scenes.length} ${s.img} ${fresh ? "(kept)" : `${d}s`}`);
}

// One continuous narration track, cut to each segment's real video length, so the voice
// never restarts an encoder at a scene boundary. Each clip fades in and out briefly.
const vdur = (f) =>
  Number(execFileSync("ffprobe", ["-v", "error", "-select_streams", "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", f]).toString());
const wavs = [];
for (let i = 0; i < segs.length; i++) {
  const vd = vdur(segs[i]);
  const wav = join(WORK, "audio", `scene-${String(i).padStart(3, "0")}.wav`);
  const pcm = ["-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", wav];
  if (i === 0) {
    ff(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", String(vd), ...pcm]);
  } else {
    const { audio, a } = voices[i - 1];
    ff([
      "-i", audio,
      "-af", `afade=t=in:d=0.03,afade=t=out:st=${Math.max(0, a - 0.12).toFixed(3)}:d=0.12,` +
        `adelay=${LEAD * 1000}:all=1,apad,atrim=0:${vd.toFixed(4)}`,
      ...pcm,
    ]);
    // captions: sentences timed by length within the narration
    const s = scenes[i - 1];
    const parts = s.say.match(/[^.!?]+[.!?]+(\s|$)/g)?.map((x) => x.trim()) ?? [s.say];
    const total = parts.reduce((n, p) => n + p.length, 0);
    let t = clock + LEAD;
    for (const p of parts) {
      const len = (a * p.length) / total;
      srt.push(`${srt.length + 1}\n${ts(t)} --> ${ts(t + len)}\n${p}\n`);
      t += len;
    }
  }
  clock = i === 0 ? vd : clock + vd;
  wavs.push(wav);
}

const list = join(WORK, "list.txt");
writeFileSync(list, segs.map((f) => `file '${f.replace(/\\/g, "/")}'`).join("\n"));
const alist = join(WORK, "alist.txt");
writeFileSync(alist, wavs.map((f) => `file '${f.replace(/\\/g, "/")}'`).join("\n"));
const video = join(OUT, "pre-sales-agent-product-tour.mp4");
ff([
  "-f", "concat", "-safe", "0", "-i", list,
  "-f", "concat", "-safe", "0", "-i", alist,
  "-map", "0:v", "-map", "1:a", "-c:v", "copy",
  "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-c:a", "aac", "-b:a", "192k",
  "-movflags", "+faststart", video,
]);
writeFileSync(join(OUT, "pre-sales-agent-product-tour.srt"), srt.join("\n"));
writeFileSync(
  join(OUT, "pre-sales-agent-product-tour.vtt"),
  "WEBVTT\n\n" + srt.join("\n").replace(/(\d),(\d{3})/g, "$1.$2"),
);
console.log(`done: ${video} (${clock.toFixed(1)} s)`);
