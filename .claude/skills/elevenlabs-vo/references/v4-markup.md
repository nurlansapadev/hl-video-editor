# Writing for Eleven v4

Sources: ElevenLabs docs "Best practices → Prompting Eleven v4", "Eleven v4" overview, the v4 Audio Tags list and pauses guide (Sep–Oct 2026), and the connector's own model guide. v4 is under active development; if something here stops working, re-check the model guide (`creative_get_model_guide eleven_v4`).

## What v4 is and isn't
- The text you send is what gets spoken. There is no separate "scene description" field.
- **No SSML.** `<break>`, `<prosody>`, `<phoneme>` and any XML are not supported. Remove them if a script has them.
- **No speed or style sliders.** Only Stability and Similarity exist, and the connector can't set them — they come from the voice's own settings on the ElevenLabs site. So all control over delivery is in the text: tags, punctuation, capitals, paragraphing.
- v4 reads tone from the words themselves; tags fine-tune a delivery the words already suggest. Over-tagging fights the model.
- Numbers: leave them exactly as the script has them, digits or words. v4 reads both. Don't convert.

## Audio tags
Free text in square brackets, placed right before the words they colour. A tag holds until the next tag, so tag only where the delivery changes.

**Describe how the line sounds, not what the speaker does.** `[grinning]`, `[pacing]`, `[leaning in]`, `[standing]` are not performed. `[low, gravelly voice]` beats `[gravelly]` — a one-word tag can be misread as a sound effect.

Combine qualities with commas inside one bracket: `[full, confident, measured]`. Short phrases are fine: `[dry, with controlled contempt]`. Keep them under ~6 words. Plain words, no hyphens.

Match tags to the voice. A serious voice doesn't do `[giggles]` well. Check the channel's range in `channels.md`.

One tag per clause. Contrasting tags on the same words blur the performance.

Useful for Arny — a strong, energetic narrator with a full, confident voice (starting set, write your own;
the four registers are from hl-script `production/voice-and-sound.md`):
- Steady reporter (beats 1–2): `[full, confident, measured]`, `[matter-of-fact]`, `[clear, steady]`
- Impressed pro (beat 4): `[with relish]`, `[impressed, energetic]`, `[eager, building]`
- Deadpan skeptic (beats 5–6): `[dry, deadpan]`, `[dry, a hint of contempt]`, `[wry]`, `[sarcastic, confident]`
- Mask off (beat 7): `[firm, direct]`, `[plain, no nonsense]`
- Weight / reveal: `[firm, hard]`, `[slower, deliberate]`, `[grim, steady]` — a calm, steady line against a heavy meaning
- Outro: `[dry, a hint of a smile]`
- Non-verbal, sparingly and only if they fit the character: `[short laugh]`, `[clears throat]`
- **Never for Arny:** whisper, breathy, `[quiet]`, `[quietly]`, `[confidential]`, `[weary]`, `[sighs]`, sleepy or lulling tags,
  and no shouting / trailer-voice tags. A take that comes out sluggish, sleepy, whispering or announcer-flat is regenerated.

Avoid sound-effect tags (`[applause]`, `[explosion]`, `[footsteps]`) in narration — music and SFX are done in the edit.

## Pauses
- `[pause]` — a short beat, about a breath. Before a punchline, after a setup line, between two ideas.
- `[long pause]` — a held silence before a reveal or between scenes. Inside one chunk only; between chunks the gap is made on the timeline.
- `[short pause]` also exists.
- Ellipsis `...` — hesitation, slows the line, adds weight.
- Em dash `—` — a short beat or a cut.
- Short sentences. Fragments. They create rhythm on their own.

Be consistent across the whole script: if one chunk uses `[pause]` before punchlines, all chunks do. Mixed approaches make long-form audio sound uneven.

## Emphasis
CAPS on a single word: `It's a SHOWROOM.` Use sparingly — a few per chunk, only where the stress carries the meaning. Never CAPS a whole sentence for a calm narrator.

## Pronunciation (IPA)
Only when a name or term is likely to be misread and he asks, or it's critical. Replace the word with IPA between slashes: `Svenningsen` → `/ˈsvɛnɪŋsən/`. Include stress marks. The IPA replaces the word in the text that is sent. Test important ones; results vary by voice. Show every IPA replacement on the approval screen.

## Paragraphs and chunks
- One beat or sub-scene = one paragraph. Max ~1 000 characters per paragraph; split longer beats into 2–3 paragraphs at natural turns.
- Chunk = one generation call = one file. Max 3 000 characters including tags. Cut at beat boundaries; never mid-paragraph.
- The model performs better with context, so don't make chunks tiny either: aim for 1 500–3 000 characters, except the outro.

## Example (Honest Lies hook; text approved by the user, tags updated 2026-10-28 to the hl-script voice rules)
```
[full, confident, measured] Greenland. A tunnel carved deep into ice that's been here for thousands of years. Camera flashes catch two Boy Scouts in the half-dark — one American, one Danish. They're grinning for the photographers at the mouth of a tunnel that leads to a nuclear reactor. [dry, deadpan] This is no top-secret bunker. It's a SHOWROOM. The U.S. Army wants the whole world to see its city under the ice. [slower, deliberate] Two things, though, stay out of the picture. First: the Americans started digging into this ice before Denmark — which owns the island — ever said yes. Second: this camp wasn't REALLY built for science. [firm, direct] So what was the Pentagon actually burying under the Greenland snow? And why didn't America's ally ever ask what it was for? [dry, a hint of a smile] You're about to see how you hide a massive nuclear plan inside the most famous camp in the Arctic — and hide it so LOUDLY that your ally would rather not look.
```
