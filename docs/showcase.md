# GitHub Pages showcase

The public project page is **https://hashkanna.github.io/first-response/**.

`site/` contains the static page, stylesheet, chapter/transcript behavior, and the actual demo media. There are no runtime dependencies or provider credentials. The MP4 is the same 120-second file published in the v1.0.0 release, hosted directly on Pages so it plays inline. English captions are also supplied as WebVTT; the video itself already has burned captions. The final audio scene has approximate caption timing, as disclosed in the video.

The page includes the measured timeout results, the investigation workflow, scope, source and evidence links, a readable transcript, and chapter links. It presents the application; it does not run the FastAPI hub or connect visitors to the local development server.

`.github/workflows/pages.yml` publishes only `site/` on changes to that directory or its workflow on `main`. Other source code, runtime files and credentials are excluded from the Pages artifact. The workflow can also be dispatched manually. GitHub Pages uses the workflow publishing source.

To preview locally, serve `site/` using a static server. For video seek testing, use a server that supports HTTP Range requests; Python's basic `http.server` does not. The deployed Pages video supports browser range requests.

Keep `site/transcript.json`, `site/media/captions.vtt`, the chapter times in `site/index.html`, and the recording disclosure aligned when replacing the MP4. Keep reported timings tied to the referenced run rather than treating a single observation as a benchmark.
