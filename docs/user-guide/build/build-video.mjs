// Build the narrated product tour: ElevenLabs voice per scene, ffmpeg Ken Burns per screenshot.
//   node build-video.mjs <repo> <shots dir> <work dir>
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [REPO, SHOTS, WORK] = process.argv.slice(2);
const OUT = join(REPO, "docs/user-guide");
const VOICE = process.env.VOICE_ID ?? "Xb7hH8MSUJpSbSDYk0k2"; // Alice, clear British educator
const MODEL = "eleven_multilingual_v2";
const FPS = 30, W = 1440, H = 900, LEAD = 0.35, TAIL = 0.75;
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

// Title card
const title = join(WORK, "seg", "000-title.mp4");
writeFileSync(join(WORK, "txt", "t1.txt"), "Pre Sales Agent Framework");
writeFileSync(join(WORK, "txt", "t2.txt"), "Product tour  ·  from first customer email to a baselined estimate");
ff([
  "-f", "lavfi", "-i", `color=c=0x141826:s=${W}x${H}:r=${FPS}:d=3.5`,
  "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
  "-filter_complex",
  `[0]drawtext=fontfile='${FONT}':textfile='${join(WORK, "txt", "t1.txt").replace(/\\/g, "/").replace(":", "\\:")}':fontsize=64:fontcolor=white:x=(w-tw)/2:y=h/2-70,` +
    `drawtext=fontfile='${FONT_R}':textfile='${join(WORK, "txt", "t2.txt").replace(/\\/g, "/").replace(":", "\\:")}':fontsize=28:fontcolor=0xa5b4fc:x=(w-tw)/2:y=h/2+20,` +
    `fade=in:0:15,fade=out:st=3.0:d=0.5[v]`,
  "-map", "[v]", "-map", "1", "-t", "3.5",
  "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", title,
]);

const segs = [title];
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
  // alternate zoom direction for some variety
  const zin = i % 2 === 0;
  const z = zin ? `1+0.04*on/${frames}` : `1.04-0.04*on/${frames}`;
  ff([
    "-loop", "1", "-framerate", String(FPS), "-i", join(SHOTS, `${s.img}.png`), "-i", audio,
    "-filter_complex",
    `[0]scale=${W * 2}:${H * 2},zoompan=z='${z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${frames}:s=${W}x${H}:fps=${FPS},` +
      `drawtext=fontfile='${FONT}':textfile='${lab}':fontsize=22:fontcolor=white:box=1:boxcolor=0x4f46e5@0.92:boxborderw=14:x=w-tw-36:y=h-th-36,` +
      `fade=in:0:8,fade=out:st=${(d - 0.3).toFixed(2)}:d=0.3[v];` +
      `[1]adelay=${LEAD * 1000}|${LEAD * 1000},apad,atrim=0:${d}[a]`,
    "-map", "[v]", "-map", "[a]", "-t", String(d),
    "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", seg,
  ]);
  segs.push(seg);

  // captions: sentences timed by length within the narration
  const parts = s.say.match(/[^.!?]+[.!?]+(\s|$)/g)?.map((x) => x.trim()) ?? [s.say];
  const total = parts.reduce((n, p) => n + p.length, 0);
  let t = clock + LEAD;
  for (const p of parts) {
    const len = (a * p.length) / total;
    srt.push(`${srt.length + 1}\n${ts(t)} --> ${ts(t + len)}\n${p}\n`);
    t += len;
  }
  clock += d;
  console.log(`seg ${i + 1}/${scenes.length} ${s.img} ${d}s`);
}

const list = join(WORK, "list.txt");
writeFileSync(list, segs.map((f) => `file '${f.replace(/\\/g, "/")}'`).join("\n"));
const video = join(OUT, "pre-sales-agent-product-tour.mp4");
ff(["-f", "concat", "-safe", "0", "-i", list, "-c", "copy", "-movflags", "+faststart", video]);
writeFileSync(join(OUT, "pre-sales-agent-product-tour.srt"), srt.join("\n"));
console.log(`done: ${video} (${clock.toFixed(1)} s)`);
