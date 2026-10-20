"""A short icon gesture, with no worker or timer running while idle."""

import logging
import math
import threading


def build_activity_frames(image):
    """Breathe and gently turn the mark, keeping transparent edges intact."""
    from PIL import Image

    # Pillow 9.0 predates the Resampling enum.
    resampling = getattr(Image, "Resampling", Image)
    size = image.size
    large_size = (size[0] * 4, size[1] * 4)
    frames = []
    with image.resize(large_size, resampling.LANCZOS) as source:
        for index in range(1, 13):
            progress = index / 13
            breath = math.sin(math.pi * progress)
            angle = 12 * math.sin(2 * math.pi * progress) * breath
            scale = 1 - 0.09 * breath
            scaled_size = tuple(round(dimension * scale) for dimension in large_size)
            with source.resize(scaled_size, resampling.LANCZOS) as scaled:
                with Image.new("RGBA", large_size) as canvas:
                    offset = tuple((a - b) // 2 for a, b in zip(large_size, scaled_size))
                    canvas.paste(scaled, offset)
                    with canvas.rotate(angle, resampling.BICUBIC) as turned:
                        frames.append(turned.resize(size, resampling.LANCZOS))
    return frames


class IconAnimation:
    def __init__(self, image, update, interval=0.08):
        self._rest = image
        self._frames = build_activity_frames(image)
        self._update = update
        self._interval = interval
        self._closed = threading.Event()
        self._lock = threading.Lock()
        self._thread = None

    def play(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            # Rapid actions share one gesture; they cannot accumulate workers.
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="launcher-icon", daemon=True,
            )
            try:
                self._thread.start()
            except RuntimeError:
                self._thread = None
                raise

    def _run(self) -> None:
        try:
            for frame in self._frames:
                if self._closed.is_set():
                    break
                self._update(frame)
                if self._closed.wait(self._interval):
                    break
        except Exception:
            logging.getLogger(__name__).debug("Icon animation failed", exc_info=True)
        finally:
            if not self._closed.is_set():
                try:
                    self._update(self._rest)
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Could not restore the resting icon", exc_info=True,
                    )

    def close(self) -> None:
        with self._lock:
            if self._closed.is_set():
                return
            self._closed.set()
            worker = self._thread
        if worker is not None:
            worker.join()
        for frame in self._frames:
            frame.close()
