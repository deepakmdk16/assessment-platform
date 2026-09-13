"""Turning an uploaded file into an image this platform is willing to serve (P3b).

An upload is not an image until we have decoded it ourselves. Everything the
client said about the file — its name, its `Content-Type` — is a claim; the only
facts are the bytes. So the pipeline here is: look at the leading bytes, decode
with Pillow, and **re-encode**. The re-encode is the point of the whole module:

- it strips EXIF, which routinely carries a GPS fix and a device serial;
- it kills polyglots — a file that is a valid PNG *and* a valid HTML document or
  ZIP archive survives a magic-byte check and dies here, because what gets
  stored is what Pillow wrote, not what arrived;
- it normalises the type, so `content_type` on the row is something we produced.

SVG is refused outright rather than sanitised. It is a script-bearing document
that browsers execute, and there is no version of "safe SVG" worth owning for a
logo.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from PIL.Image import DecompressionBombError, Resampling

# The upload cap. Generous for a logo and small enough that the whole thing can
# sit in memory while it is checked.
MAX_UPLOAD_BYTES = 256 * 1024
# And the cap on what we *store*, which is not automatically the same number:
# re-encoding a lossy source as lossless PNG can more than triple it. Nothing is
# refused for exceeding this — it is the threshold at which `_encode` switches to
# a lossy format instead.
MAX_STORED_BYTES = MAX_UPLOAD_BYTES
# The longest edge we keep. A logo is rendered at ~21px on the candidate header
# and ~88px in settings; 512 leaves room for a retina display and nothing more.
MAX_EDGE = 512
# The most pixels we will decode. The output is capped at MAX_EDGE either way,
# so this only has to be large enough for a plausible source: 16 MP is a phone
# photo of a printed logo, which is about as unreasonable as a real upload gets.
#
# It is a memory limit, not a pedantry: `convert("RGBA")` materialises 4 bytes a
# pixel, so 16 MP is ~64 MB of transient RSS and 40 MP was ~330 MB — one upload
# away from OOM-killing a small container, from a file well under the size cap.
MAX_PIXELS = 16_000_000

# The three formats a browser renders and Pillow can be trusted to re-encode.
# Keyed by the magic bytes, because that is the only part of the upload that is
# evidence. WebP is RIFF....WEBP, so it is matched in two pieces.
_PNG = b"\x89PNG\r\n\x1a\n"
_JPEG = b"\xff\xd8\xff"
_RIFF = b"RIFF"
_WEBP = b"WEBP"

# What we re-encode *to*. A JPEG stays a JPEG (photographic logos would bloat as
# PNG); everything else, WebP included, comes out as PNG — two output paths
# instead of three, and PNG is the one format every browser has always rendered.
_OUTPUT = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "WEBP": "image/webp",
}

# What Pillow is allowed to report for each sniffed format. Usually the same
# name; the exception is MPO — a multi-picture JPEG, which is what Android burst
# and several cameras' HDR modes emit. Its magic bytes are a plain JPEG SOI, so
# demanding `format == "JPEG"` would refuse an ordinary, decodable photo.
_DECODES_AS = {
    "PNG": {"PNG"},
    "JPEG": {"JPEG", "MPO"},
    "WEBP": {"WEBP"},
}


class ImageRejectedError(Exception):
    """The upload is not something we will store. The message is shown to the
    uploader, so it says what to do about it."""


@dataclass(frozen=True)
class NormalizedImage:
    """What the pipeline produced: the bytes to store, and what they are."""

    data: bytes
    content_type: str
    width: int
    height: int
    sha256: str


def _sniff(data: bytes) -> str:
    """The format the leading bytes actually say this is."""
    if data.startswith(_PNG):
        return "PNG"
    if data.startswith(_JPEG):
        return "JPEG"
    if data.startswith(_RIFF) and data[8:12] == _WEBP:
        return "WEBP"
    raise ImageRejectedError(
        "that file is not a PNG, JPEG or WebP image. SVG and PDF logos aren’t accepted."
    )


def _encode(frame: Image.Image, declared: str) -> tuple[str, io.BytesIO]:
    """Write the downscaled frame out, small enough to serve.

    PNG is lossless, so re-encoding a lossy source into it *grows* the file: a
    249 KB noisy WebP came back out as a 795 KB PNG — three times the cap this
    module advertises, stored in a row and pulled on every candidate page load.
    So PNG is the first choice (it is what a logo usually is, and it keeps the
    alpha), and anything that does not fit is written again as lossy WebP, which
    also has alpha. JPEG in, JPEG out: a photographic source has nothing to gain
    from the round trip.
    """
    buffer = io.BytesIO()
    if declared == "JPEG":
        # JPEG has no alpha; flatten onto white rather than let Pillow refuse.
        flat = Image.new("RGB", frame.size, (255, 255, 255))
        flat.paste(frame, mask=frame.split()[3])
        flat.save(buffer, format="JPEG", quality=90, optimize=True)
        return "JPEG", buffer

    frame.save(buffer, format="PNG", optimize=True)
    if buffer.tell() <= MAX_STORED_BYTES:
        return "PNG", buffer
    buffer = io.BytesIO()
    frame.save(buffer, format="WEBP", quality=85, method=4)
    return "WEBP", buffer


def normalize_logo(data: bytes) -> NormalizedImage:
    """Decode, downscale and re-encode an uploaded logo, or say why not."""
    if not data:
        raise ImageRejectedError("that file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejectedError(f"logos are limited to {MAX_UPLOAD_BYTES // 1024} KB.")
    declared = _sniff(data)

    # Pillow's own bomb guard, set per call rather than globally so this module
    # cannot change decoding behaviour for anything else in the process.
    previous = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            # `open` reads the header only, so the dimensions are known before a
            # single pixel is allocated. Checked here rather than left to
            # Pillow's own guard, which only *warns* until twice this number.
            if img.size[0] * img.size[1] > MAX_PIXELS:
                raise ImageRejectedError(
                    f"that image is {img.size[0]}×{img.size[1]}, which is far larger "
                    "than a logo needs to be."
                )
            if img.format not in _DECODES_AS[declared]:
                # The magic bytes and the decoder disagree: a container holding
                # something other than what it announced.
                raise ImageRejectedError("that image’s contents don’t match its format.")
            img.load()
            # A palette or greyscale PNG, a CMYK JPEG, an animated WebP — all
            # decode, and all re-encode cleanly from RGBA.
            frame = img.convert("RGBA")
            frame.thumbnail((MAX_EDGE, MAX_EDGE), Resampling.LANCZOS)
            out_format, buffer = _encode(frame, declared)
            width, height = frame.size
    except ImageRejectedError:
        raise
    except (UnidentifiedImageError, DecompressionBombError, OSError, ValueError) as exc:
        raise ImageRejectedError("that image couldn’t be read. Try re-exporting it.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous

    encoded = buffer.getvalue()
    return NormalizedImage(
        data=encoded,
        content_type=_OUTPUT[out_format],
        width=width,
        height=height,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
