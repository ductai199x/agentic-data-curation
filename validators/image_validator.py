"""Image validation module.

Validates downloaded images against generator-specific criteria:
- Resolution matches native output size
- No camera EXIF metadata (indicates real photograph)
- File size / compression within expected range
- Not a thumbnail (dimensions too small or fractional scale)
- Not a real upload (dimensions too large)
"""

from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from PIL.ExifTags import TAGS, IFD


@dataclass
class ValidationResult:
    path: Path
    passed: bool
    width: int = 0
    height: int = 0
    format: str = ""
    file_size: int = 0
    bpp: float = 0.0
    avg_quantization: float | None = None
    has_camera_exif: bool = False
    camera_exif_tags: list[str] = field(default_factory=list)
    has_generator_exif: bool = False
    flags: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        flags_str = ", ".join(self.flags) if self.flags else "none"
        return f"{status} {self.path.name} ({self.width}x{self.height} {self.format}) flags=[{flags_str}]"


def validate_image(
    path: Path,
    native_resolutions: list[tuple[int, int]] | None = None,
    resolution_tolerance: int = 2,
    max_long_side: int | None = None,
    min_long_side: int | None = None,
    expected_formats: list[str] | None = None,
    max_avg_quantization: float | None = None,
    camera_exif_tags: list[str] | None = None,
) -> ValidationResult:
    """Validate a single image against generator-specific criteria.

    Returns a ValidationResult with pass/fail and detailed flags.
    """
    result = ValidationResult(path=path, passed=True)

    try:
        img = Image.open(path)
    except Exception as e:
        result.passed = False
        result.flags.append(f"cannot_open: {e}")
        return result

    result.width, result.height = img.size
    result.format = img.format or "UNKNOWN"
    result.file_size = path.stat().st_size
    pixels = result.width * result.height
    result.bpp = (result.file_size * 8) / pixels if pixels > 0 else 0

    # Format check
    if expected_formats and result.format not in expected_formats:
        result.flags.append(f"unexpected_format:{result.format}")
        result.passed = False

    # Resolution check — must match one of the native resolutions
    if native_resolutions:
        dims = (result.width, result.height)
        matched = any(
            abs(dims[0] - nr[0]) <= resolution_tolerance
            and abs(dims[1] - nr[1]) <= resolution_tolerance
            for nr in native_resolutions
        )
        if not matched:
            result.flags.append(
                f"non_native_resolution:{result.width}x{result.height}"
            )
            result.passed = False

    # Max dimension check (too large = likely real upload)
    long_side = max(result.width, result.height)
    if max_long_side and long_side > max_long_side:
        result.flags.append(f"too_large:{long_side}px")
        result.passed = False

    # Min dimension check (too small = likely thumbnail)
    if min_long_side and long_side < min_long_side:
        result.flags.append(f"too_small:{long_side}px")
        result.passed = False

    # JPEG quantization check
    if result.format == "JPEG" and max_avg_quantization:
        qtables = img.quantization
        if qtables:
            lum = qtables.get(0, qtables.get(list(qtables.keys())[0]))
            result.avg_quantization = sum(lum) / len(lum)
            if result.avg_quantization > max_avg_quantization:
                result.flags.append(
                    f"high_compression:avg_q={result.avg_quantization:.1f}"
                )
                result.passed = False

    # EXIF analysis
    if camera_exif_tags:
        exif = img.getexif()
        if exif:
            # Check main IFD
            tag_name_to_id = {v: k for k, v in TAGS.items()}
            for tag_name in camera_exif_tags:
                tag_id = tag_name_to_id.get(tag_name)
                if tag_id and tag_id in exif:
                    result.has_camera_exif = True
                    result.camera_exif_tags.append(tag_name)

            # Check Exif sub-IFD
            try:
                exif_ifd = exif.get_ifd(IFD.Exif)
                if exif_ifd:
                    for tag_name in camera_exif_tags:
                        tag_id = tag_name_to_id.get(tag_name)
                        if tag_id and tag_id in exif_ifd:
                            if tag_name not in result.camera_exif_tags:
                                result.has_camera_exif = True
                                result.camera_exif_tags.append(tag_name)
            except Exception:
                pass

            # Check for generator-specific EXIF (e.g., Grok's Artist + Signature)
            artist = exif.get(tag_name_to_id.get("Artist", -1))
            desc = exif.get(tag_name_to_id.get("ImageDescription", -1))
            if artist and desc and "Signature:" in str(desc):
                result.has_generator_exif = True

        if result.has_camera_exif:
            result.flags.append(
                f"camera_exif:{','.join(result.camera_exif_tags)}"
            )
            result.passed = False

    return result


def validate_batch(
    image_dir: Path,
    suffixes: tuple[str, ...] = (".jpg", ".jpeg", ".png"),
    **kwargs,
) -> list[ValidationResult]:
    """Validate all images in a directory.

    Returns list of ValidationResults sorted by pass/fail then filename.
    """
    images = sorted(
        f for f in image_dir.iterdir() if f.suffix.lower() in suffixes
    )
    results = [validate_image(f, **kwargs) for f in images]
    # Sort: failures first, then by filename
    results.sort(key=lambda r: (r.passed, r.path.name))
    return results


def print_report(results: list[ValidationResult]) -> None:
    """Print a human-readable validation report."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'='*60}")
    print(f"Validation Report: {passed}/{total} passed, {failed} failed")
    print(f"{'='*60}\n")

    if failed > 0:
        print("FAILED:")
        for r in results:
            if not r.passed:
                print(f"  {r.summary}")

        print()

    print("PASSED:")
    for r in results:
        if r.passed:
            print(f"  {r.summary}")
