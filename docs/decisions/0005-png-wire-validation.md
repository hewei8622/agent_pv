# First PNG wire-validation correction

The independent review of commit `5f03e1e` demonstrated three wrongly accepted
payloads: an invalid zlib IDAT stream, truecolor RGB16 labelled as RGB8, and a
nonempty IEND containing a synthetic private-path canary. No private file was
read and no leak was found in the actual camera image.

The existing Pillow `verify()` call checks integrity without decoding pixels.
Pillow can also expose a 16-bit truecolor PNG as mode RGB, and permissive decoding
alone does not enforce the public wire subset. The correction validates the
container and compressed stream before reopening the image for a full decode:

- Exactly one initial 13-byte IHDR, fixed 640x480 dimensions, bit depth 8,
  truecolor type 2, compression/filter method 0 and interlace method 0 or 1.
- Only IHDR, consecutive IDAT chunks and one empty terminal IEND; every chunk's
  framing and CRC checked; no metadata or trailing container data.
- Exactly one complete zlib stream with the required scanline byte count.
  Decompression is bounded at that fixed count plus one byte to reject excess
  data without unbounded allocation. Noninterlaced and Adam7 images are supported.
- Pillow integrity verification followed by reopening and `load()`.
  Decoder exceptions become validation errors.

The extra IDAT checks are based on preserved failing regressions: trailing bytes,
a second compressed stream, missing zlib trailer, short pixels and extra pixels
were also accepted by the original validator. They address the same wire-boundary
defect, not new M1 functionality. The existing 2,800,000-character base64 limit and
public schema remain unchanged. Valid pixel data is not an information-flow or
hostile-process isolation guarantee.

Thirty-one new cases include the reviewer's three counterexamples, critical
chunk/header/stream failures and valid controls. Controls include the original
captured PNG copied byte-for-byte with provenance, synthetic RGB8, split IDAT
chunks (including an empty chunk), and an independently constructed Adam7 image.
Before the fix, 16 assertions failed and 15 passed; afterward, all 31 passed.
One repair round was used. Earlier failures and the original PDF are preserved.

Primary sources checked:

- [Pillow Image.verify/load](https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.verify)
- [PNG IHDR](https://www.w3.org/TR/png-3/#11IHDR),
  [IEND](https://www.w3.org/TR/png-3/#11IEND), and
  [interlacing](https://www.w3.org/TR/png-3/#8Interlace)

This implementation response is not an independent passing verdict. Fresh desktop
rendering/full-suite verification and independent acceptance remain required.
