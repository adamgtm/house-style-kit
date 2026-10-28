# Generate people, don't draw them

Use this when a graphic needs a person: an avatar in a chat window, a worker in a diagram, a speaker card. Drawing people in HTML never looks like a person. Generating them does. Keep drawing icons, objects and UI in HTML or SVG.

```text
This graphic needs [N] people: [who each one is, in a few words].
Generate them as images instead of drawing them. Use any image model you can call; for example, `codex exec` with image generation. Don't use an API key I haven't given you.

1. Write one prompt per person, as short labeled lines, in this order:
   - Subject: role, age band, gender, ethnicity, hair, clothes, one prop, one expression. Let role cues do the work: a lanyard, over-ear headphones, a hoodie.
   - Framing: head-and-shoulders portrait, centered, cropped at mid-chest, slight three-quarter turn, square. Keep hands out of frame.
   - Style block: my illustration style in one sentence, such as "modern flat editorial illustration, clean vector-like shapes, thin warm-black outlines, soft shading, realistic faces." Also say what it is not: photoreal stock, cartoon mascot, 3D render.
   - Palette as hex, taken from my house style.
   - Background: one solid flat color, the same as the graphic's ground. No shadow, no gradient, no floor.
   - Exclude: text, letters, logos, watermarks, frames, extra people, and any real person's likeness. These are invented people.
2. Keep the set consistent. Paste the identical style block into every prompt and change only the subject line. Restate outfit and traits every time. Generate the whole set in one session. If one image drifts, regenerate just that one. If the set still won't match, pass a good image as a reference and say "same illustration style as this image."
3. For cut-outs, keep the flat background color, then remove it afterward by flood-filling from the edges. Inside circular avatars, use the original image. Check the hair edge on dark or colored grounds, where a pale fringe can show.
4. Review each image before it goes in. Look for:
   - hands (none is best);
   - eyes that don't match in direction or size;
   - garbled text on lanyards, shirts or headphones;
   - stray logos;
   - an uncanny smile or teeth;
   - a style that doesn't match the rest of the set;
   - an age and role that aren't believable.
5. Save the exact prompt as a .txt next to each image, with the same name, so any person can be regenerated or edited later.

Show me the set side by side before you put it in the graphic.
```

When a flaw keeps showing up, add it to the review list in your lessons.
