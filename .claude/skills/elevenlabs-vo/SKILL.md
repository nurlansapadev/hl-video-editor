---
name: elevenlabs-vo
description: Voiceover producer for ElevenLabs v4 via the ElevenLabs connector — asks the channel (default Honest Lies, narrator Arny), takes the script as .txt (plus an optional beat-structure .md), marks it up with v4 audio tags, shows it for approval with a credit estimate, generates and saves the mp3 files to a chosen folder on the user's computer. Use whenever the user wants a voiceover, озвучка, VO, narration or TTS for a video script, says «озвучь», «сделай озвучку», «прогони через ElevenLabs», «голос Арни», or attaches a script and mentions ElevenLabs or a narrator — even if he doesn't name this skill.
---

# ElevenLabs VO producer

Turns a finished video script into narrator audio on ElevenLabs v4 and drops the files into the episode folder. The user is Nurlan; talk to him in Russian, short and dry, one step at a time. The script itself stays in English.

Two references, read them when you reach the step that needs them:
- `references/channels.md` — channel list: voice, model, default folder, delivery style. Read at step 1.
- `references/v4-markup.md` — how to write for Eleven v4 (tags, pauses, emphasis, IPA, chunking). Read before step 4.

## VideoEditor mode (episode work in VideoEditor_2.0)
When VideoEditor's CLAUDE.md calls this skill for episode `ep-N`, everything is already known — don't ask steps 1–3:
- channel: Honest Lies; folder: `D:\YouTube-Studio\production\honest-lies\ep-N\01_vo\`;
- clean text: `ep-N\00-script\clean-script.txt`; structure map: `ep-N\00-script\en-script-final.md` (if present);
- outro / end-teaser: `ep-N\00-script\udochka.md` (the EN «✅ for recording» variant) → `vo_outro`, even if `sound-vo.md` says it isn't written yet. No outro anywhere → ask Nurlan «А удочки нет что ли?» before the approval screen;
- run only if `01_vo\` has no `vo_*.mp3` yet (otherwise the voiceover is done — say so and stop; regenerate single chunks only on request).
Then go straight to step 4 (markup) → 5 (chunks) → **6 (approval screen with credits — always wait for his OK, it spends credits)** → 7 → 8 → 9. The model probe still applies once if `channels.md` marks the model unconfirmed. After saving, tell him one line: «Озвучка в 01_vo готова — дальше этап 2 VideoEditor».

## Workflow

### 1. Channel
Read `references/channels.md`. Ask which channel, offering the list (AskUserQuestion if available); Honest Lies is the default and first option. The channel gives you voice_id, model and style. Never take a voice_id from anywhere else.

### 2. Output folder
Ask where to put the result, offering the channel's default with the episode filled in, e.g. `D:\YouTube-Studio\production\honest-lies\ep-8\01_vo\`. Take the episode name from the md header or the file name when there is one. He always picks the folder; don't skip this question.

Check now that the computer is reachable. In Claude Code on his PC (a local shell — Bash or PowerShell — is available) it is: save straight into the folder. Otherwise look for `mcp__remote-devices__` tools (ToolSearch "remote-devices"). If there is neither, tell him in one line that to save into a folder on his PC this chat must be opened in the Claude desktop app, and carry on with the markup meanwhile — files can still go out through SendUserFile at the end.

### 3. Sources
- **clean .txt** — required, the source of truth for the words. Voice exactly these words; never rewrite, add or drop any.
- **structure .md** — optional, a map only. `## BEAT N` = beat boundary, `### N.N` = sub-scene. Use it to find where beats start; ignore its wording differences.
- Text in the clean file that has no counterpart in the md (usually at the very end) is the **outro / end-teaser** for the next episode. It becomes its own file.
- Don't run punctuation comparisons between the two files — he doesn't want that.
- With no md: infer beats from the text itself (topic shifts, standalone one-line paragraphs, time jumps).

### 4. Markup
Read `references/v4-markup.md` and mark up the clean text for the channel's narrator. The essentials:
- Merge the clean file's short paragraphs into larger logical paragraphs: one beat or sub-scene per paragraph, **max ~1 000 characters per paragraph** (about the length of the Honest Lies hook). Split longer beats into 2–3 paragraphs at natural turns. Many tiny paragraphs make the delivery drift between them; one giant blob is also wrong.
- Tags inline, inside the paragraph, only where the delivery changes — a tag holds until the next one.
- `[pause]` before standalone punchlines (lines the author set apart as their own paragraph) and at sub-scene changes inside a chunk. No tags at chunk boundaries — the gap between files is made on the timeline.
- CAPS on a word only where the emphasis is the point of the sentence; a few per chunk.

### 5. Chunks
Group paragraphs into chunks of **≤ 3 000 characters including tags**, cutting only at beat boundaries when possible, otherwise between paragraphs. Never mid-paragraph. Outro is always its own chunk. Name them `vo_01`, `vo_02` … and `vo_outro`.

### 6. Approval screen
Get the credit cost first: call `creative_generate_speech` with `estimate_only: true` for each chunk (it generates nothing). Then show, for each chunk:

```
**vo_01 · BEAT 1 — HOOK · 1 012 знаков · eleven_v4 · Арни**
[code block with the exact text that will be sent]
```

and at the end: number of files, total characters, total credits, then «Ок, или что поправить?». Wait for his explicit OK. Apply any edits and show only the changed chunks again.

### 7. Generate
For each approved chunk call `creative_generate_speech` with the channel's voice_id and model, the chunk text as `prompt`, and `generations_count: 1` (he wants one take per chunk; regenerating a single chunk later is cheaper than four takes of everything). Create one flow first with `creative_create_flow` and pass its flow_id to every chunk, so the whole episode lives on one canvas.

Never call generate twice for the same chunk as a retry — each call charges again. Poll `creative_get_flow_run_status` (wait `poll_after_seconds` between calls) until `all_completed` or `has_failures`. Report failures per chunk; regenerate a failed chunk only after he says so.

### 8. Save
Find each generation's audio URL in the status result. Then:
- **Computer reachable** (local shell in Claude Code, or `mcp__remote-devices__device_bash`): download straight into his folder on his Windows machine, e.g. `curl.exe -L -o "D:\...\vo_01.mp3" "<url>"` (create the folder first). Download each URL once; the links are short-lived, so do it right after generation finishes.
- **Not linked**: download in the workspace if the network allows it and send the files with SendUserFile; if the download is blocked, give him the flow URL to download from the ElevenLabs canvas, and say so plainly.

Format: keep whatever the connector returns (mp3) — he accepts mp3. If he asks for WAV, convert after download with ffmpeg where the file is (`ffmpeg -i vo_01.mp3 vo_01.wav`; check ffmpeg exists first) and tell him once that it's the same quality in a WAV container, convenient for the editor but not cleaner.

With many chunks the status result is too large and is saved to a file (EP-10: 18 chunks): don't read it in chat — a short Python script maps each generation id to its `vo_NN` name, takes `content_url` from that JSON and downloads only the finished, not yet saved files. Chunks may wait in a queue ("concurrency limit… retrying later") — that is not a failure; check again later, never re-generate.

Also save `script_tagged.txt` in the same folder: every chunk with its file name as a header, exactly as sent.

**Only the episode's voice files go into `01_vo\` itself** (`vo_01.mp3 … vo_NN.mp3`, `vo_outro.mp3`): VideoEditor glues every audio file in that folder in name order (1 s gap between files) and uses it as the narration. Probes, alternative takes and anything else — into a subfolder (`01_vo\_probe\`, `01_vo\_takes\`), which VideoEditor does not read. A regenerated chunk replaces its file under the same name.

### 9. Report
One short list: file — duration (if ffprobe or file size lets you tell) — beat. Offer to regenerate any single chunk by name. Nothing else.

## Model probe (once per channel)
If `channels.md` marks the model as not yet confirmed, before the first full generation offer a probe: one paragraph of ~400 characters from the hook, generated on `eleven_v4` and on `eleven_v3` with the same voice, `generations_count: 1` each, saved as `01_vo\_probe\probe_v4.mp3` / `probe_v3.mp3` (a subfolder — never next to the episode's vo files). Reason to give him: Arny is a Voice Design voice, and ElevenLabs says designed voices may sound less performative on v4 than on earlier models. When he picks one, update the model line in `channels.md` (tell him it should be updated in the installed skill too, since the installed copy may be read-only).

## Adding a channel
If he names a channel that isn't in the list, ask for the voice name or ID, verify it with `creative_list_voices`, ask the default folder and a one-line delivery style, and show him the new block to add to `channels.md`.
