# Turn a format you repeat into a builder

Use this when you make the same kind of thing over and over: a weekly cover, a quote card, a chart style, a post thumbnail. Build the approved design once. Every new one then starts at your bar, and your time goes into what it says.

```text
I make [the format] every [week, month, post]. Turn my approved version into a builder. Start from [a role model id, or a file].

1. Write a small script that makes it from a short spec file (JSON). Only the content changes from one to the next: the headline, the numbers, the image, the quote. The look comes from my house style and stays fixed.
2. Render it as HTML, then save a PNG at the size it's used, at 2x.
3. Make the build fail, with a plain message, when:
   - any text overflows its box or runs past an edge;
   - text would have to shrink below a minimum size to fit (cut words instead; never shrink past the floor);
   - something important sits where a platform crops it, like an archive that shows only the center square;
   - anything runs off the canvas;
   - an image is missing, or is a web address instead of a local file.
4. Let a spec carry variants, like a second headline or quote, so I can compare options side by side.
5. Rebuild my approved version from a spec and show me it matches before we use the builder for anything new.

Put the script and an example spec in house-style/builders/[format]/, and write how to use it into the standard for this kind of work (house-style/standards/).
```

When a check misses something you catch by eye, add it as a new check. The builder gets stricter every time you use it.
