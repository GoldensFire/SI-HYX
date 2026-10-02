# -*- coding: utf-8 -*-
"""Transport decoding must restore a scene, including partial edge tiles."""
import io
import pytest
from PIL import Image
from si_hyx_parts.animepack_api.comix_image import decode_image, tile_order, _xor


def _png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def test_encoded_image_restores_real_png_bytes():
    original = _png(Image.new("RGB", (31, 47), (15, 80, 130)))
    for algo in ("1", "2"):
        encoded = _xor(original, 123 | 1, len(original), shift=algo == "2")
        restored = decode_image(encoded, {"X-Enc-Seed": "123", "X-Enc-Len": str(len(original)),
                                          "X-Enc-Algo": algo})
        with Image.open(io.BytesIO(restored)) as image:
            assert image.size == (31, 47)
            assert image.getpixel((20, 30)) == (15, 80, 130)


@pytest.mark.parametrize("algo", ["1", "2", "3"])
def test_tile_permutation_restores_the_scene_and_edge_pixels(algo):
    original = Image.new("RGB", (53, 57), "purple")
    order = tile_order(177, algo)
    scrambled = original.copy()
    for target, source in enumerate(order):
        color = (target * 7, target * 5, target * 3)
        Image.Image.paste(original, color, (target % 5 * 10, target // 5 * 11,
                                           target % 5 * 10 + 10, target // 5 * 11 + 11))
        scrambled.paste(color, (source % 5 * 10, source // 5 * 11,
                               source % 5 * 10 + 10, source // 5 * 11 + 11))
    data = decode_image(_png(scrambled), {"X-Scramble-Grid": "5x5",
                                        "X-Scramble-Seed": "177", "X-Scramble-Algo": algo})
    with Image.open(io.BytesIO(data)) as restored:
        assert restored.tobytes() == original.tobytes()


def test_unknown_grid_format_cannot_be_saved_as_a_scene():
    with pytest.raises(ValueError, match="плиток"):
        decode_image(_png(Image.new("RGB", (10, 10))), {
            "X-Scramble-Grid": "6x6", "X-Scramble-Seed": "1"})
