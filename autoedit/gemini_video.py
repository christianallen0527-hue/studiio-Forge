"""Generate sponsor videos with Google's Gemini Veo API."""

from __future__ import annotations

import os
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

VEO_MODELS = (
    "veo-3.1-generate-preview",
    "veo-3.0-generate-001",
    "veo-2.0-generate-001",
)


def generate_sponsor_video(
    prompt: str,
    out_path: str | Path,
    model: str | None = None,
) -> Path:
    """Generate a 16:9 Veo video, poll its operation, and save its MP4 locally.

    If ``model`` is omitted, supported Veo models are attempted in preference order.
    The last API error is raised if no model can start a generation.
    """
    project_root = Path(__file__).resolve().parent.parent
    load_dotenv(project_root / ".env")
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from .env")

    client = genai.Client(api_key=api_key)
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    models = (model,) if model else VEO_MODELS
    operation = None
    last_error: Exception | None = None

    for candidate in models:
        try:
            operation = client.models.generate_videos(
                model=candidate,
                prompt=prompt,
                config=types.GenerateVideosConfig(
                    aspect_ratio="16:9",
                    duration_seconds=8,
                    number_of_videos=1,
                ),
            )
            break
        except Exception as error:
            last_error = error

    if operation is None:
        raise RuntimeError(f"Unable to start Veo generation: {last_error}") from last_error

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    if operation.error:
        raise RuntimeError(str(operation.error))

    generated_videos = operation.response.generated_videos
    if not generated_videos:
        raise RuntimeError("Veo completed without a generated video")

    video = generated_videos[0].video
    client.files.download(file=video)
    video.save(str(output))
    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError("Veo download did not create an MP4")
    return output
