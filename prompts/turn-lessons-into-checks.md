# Turn a lesson into a check

Use this when a lesson can be measured. A headline crowding the content. Text running into the footer. Something off the canvas. If you keep telling your agent the same thing, a check says it for you, every time.

```text
My lessons in house-style/lessons.md keep repeating [the mistake, in my words]. This is a common mistake.

Write a small check for it:
1. Read the mistake and say how to measure it: what to look at, and how far counts as wrong. Use numbers.
2. Write a short script that runs after every render of [the format], loads the rendered page, and measures it. For example, with Playwright, compare the bounding boxes of the headline and the content, or the text and the footer.
3. When it fails, print a plain warning that names the element and the amount, like "headline is 6px from the chart; minimum is 24px." Warn, don't block, until we trust it.
4. Run it on three things I've approved and make sure it stays quiet. Run it on one with the mistake and make sure it speaks up.
5. Make the render step call it, so no one has to remember.

Put the script in house-style/checks/. Add a line to the standard for this kind of work saying the check exists.
```

Write checks against your own pages, not someone else's. When a check misses something you catch by eye, tighten it.
