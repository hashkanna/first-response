const video = document.querySelector("#demo-video");
const status = document.querySelector("#playback-status");

document.querySelectorAll("[data-time]").forEach((button) => {
  button.addEventListener("click", async () => {
    const seek = () => {
      video.currentTime = Number(button.dataset.time);
    };
    if (video.readyState >= 1) seek();
    else video.addEventListener("loadedmetadata", seek, { once: true });
    try {
      await video.play();
      status.hidden = true;
    } catch {
      status.textContent =
        "Use the video’s play button to watch this chapter, or download the MP4 below.";
      status.hidden = false;
    }
    video.scrollIntoView({
      block: "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "instant"
        : "smooth",
    });
  });
});

video.addEventListener("error", () => {
  status.textContent =
    "The video could not load. You can download the MP4 below or open the GitHub release from the repository.";
  status.hidden = false;
});

const transcript = document.querySelector(".transcript");
let transcriptLoaded = false;
transcript.addEventListener("toggle", async () => {
  if (!transcript.open || transcriptLoaded) return;
  transcriptLoaded = true;
  const container = document.querySelector("#transcript-content");
  try {
    const response = await fetch("transcript.json");
    if (!response.ok) throw new Error("Transcript unavailable");
    const scenes = await response.json();
    for (const scene of scenes) {
      const heading = document.createElement("h3");
      heading.textContent = `${scene.time} · ${scene.heading}`;
      const paragraph = document.createElement("p");
      paragraph.textContent = scene.text;
      container.append(heading, paragraph);
    }
  } catch {
    const paragraph = document.createElement("p");
    const link = document.createElement("a");
    link.href = "media/captions.vtt";
    link.textContent = "Read the caption file";
    paragraph.append(link);
    container.append(paragraph);
  }
});
