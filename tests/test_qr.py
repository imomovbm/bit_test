"""QR kod kodlovchisi (app/qr.py): tuzilma, Reed–Solomon, niqob/format, ma'lumotni qayta o'qish."""
import pytest

from app import qr

# Ishlab chiqishda mustaqil dekoder (jsQR) bilan o'qib tekshirilgan natija — o'zgarib qolmasligi uchun.
FIXTURE_TEXT = "http://192.168.1.10:8080/play/123456"
FIXTURE = [
    "11111110000101010101001111111",
    "10000010011011110010001000001",
    "10111010110001001010001011101",
    "10111010111010111110101011101",
    "10111010100000000001001011101",
    "10000010100010011010001000001",
    "11111110101010101010101111111",
    "00000000110110111010000000000",
    "10111110000100011111101111100",
    "11000100100101100111001010001",
    "00010010011101110100000110000",
    "00011001101011011001011010010",
    "11010011101010111101110101100",
    "11001000110010000001001010101",
    "11101110111010011010011000100",
    "01101001000110100010010100010",
    "00111010001100011100110000100",
    "11011001010001100111011011101",
    "10000110110111110000101001100",
    "10111100010111000010011010010",
    "10111010000100111100111110111",
    "00000000110000000011100011111",
    "11111110001010011011101011100",
    "10000010110100110000100010010",
    "10111010110000011100111111100",
    "10111010101001100100110100011",
    "10111010111101111011101011010",
    "10000010001011101000110110010",
    "11111110100000100110000001100",
]


def test_reed_solomon_known_vector():
    # ISO/IEC 18004 misoli: "HELLO WORLD" (1-M) ma'lumot kodlari va ularning xato tuzatish kodlari
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr._rs_remainder(data, qr._rs_divisor(10)) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


def test_fixture_unchanged():
    assert ["".join("1" if c else "0" for c in row) for row in qr.encode(FIXTURE_TEXT)] == FIXTURE


def _format(matrix):
    """Format ma'lumotini o'qiydi (ikkala nusxa) va (daraja, niqob) ni qaytaradi."""
    size = len(matrix)
    first = [matrix[i][8] for i in range(6)] + [matrix[7][8], matrix[8][8], matrix[8][7]] + [matrix[8][14 - i] for i in range(9, 15)]
    second = [matrix[8][size - 1 - i] for i in range(8)] + [matrix[size - 15 + i][8] for i in range(8, 15)]
    to_int = lambda bits: sum(1 << i for i, b in enumerate(bits) if b)  # noqa: E731
    assert to_int(first) == to_int(second)
    raw = to_int(first) ^ 0x5412
    data = raw >> 10
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    assert raw == (data << 10 | rem), "format BCH kodi noto'g'ri"
    ecl = {1: "L", 0: "M", 3: "Q", 2: "H"}[data >> 3]
    return ecl, data & 7


def _decode(matrix):
    """Mustaqil o'quvchi: niqobni olib tashlaydi, kodlarni zigzag tartibda o'qiydi, bloklarni ajratadi,
    har bir blokning Reed–Solomon kodini tekshiradi va bayt rejimidagi matnni qaytaradi."""
    size = len(matrix)
    ver = (size - 17) // 4
    ecl, mask = _format(matrix)
    ref = qr._Matrix(ver, ecl)
    ref.draw_function_patterns()
    fn = qr._MASKS[mask]
    bits = []
    right = size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                y = size - 1 - vert if (right + 1) & 2 == 0 else vert
                if not ref.isfunction[y][x]:
                    bits.append(matrix[y][x] ^ fn(x, y))
        right -= 2
    raw = qr.num_raw_data_modules(ver) // 8
    codewords = [int("".join("1" if b else "0" for b in bits[i * 8:i * 8 + 8]), 2) for i in range(raw)]
    e = qr.ECC_LEVELS[ecl][1]
    nblocks = qr.NUM_ERROR_CORRECTION_BLOCKS[e][ver]
    ecclen = qr.ECC_CODEWORDS_PER_BLOCK[e][ver]
    nshort = nblocks - raw % nblocks
    shortlen = raw // nblocks
    blocks = [[] for _ in range(nblocks)]
    it = iter(codewords)
    for i in range(shortlen + 1):
        for j in range(nblocks):
            if i == shortlen - ecclen and j < nshort:
                continue  # qisqa bloklarda bu joy yo'q (uzun bloklarning qo'shimcha ma'lumot kodi)
            blocks[j].append(next(it))
    data = []
    for j, blk in enumerate(blocks):
        dlen = shortlen - ecclen + (0 if j < nshort else 1)
        assert qr._rs_remainder(blk[:dlen], qr._rs_divisor(ecclen)) == blk[dlen:], f"{j}-blok RS kodi noto'g'ri"
        data += blk[:dlen]
    stream = "".join(f"{b:08b}" for b in data)
    assert stream[:4] == "0100"  # bayt rejimi
    nbits = 8 if ver <= 9 else 16
    length = int(stream[4:4 + nbits], 2)
    start = 4 + nbits
    payload = bytes(int(stream[start + 8 * i:start + 8 * i + 8], 2) for i in range(length))
    return payload.decode("utf-8"), ver, ecl, mask


def _finder_ok(matrix, x0, y0):
    for dy in range(7):
        for dx in range(7):
            ring = max(abs(dx - 3), abs(dy - 3))
            if matrix[y0 + dy][x0 + dx] != (ring != 2):
                return False
    return True


@pytest.mark.parametrize("text", [
    "A",
    FIXTURE_TEXT,
    "https://bit-test-production-4821.up.railway.app/play/908172",
    "http://localhost:8080/play/100000",
    "Oʻzbekiston — Toshkent ✓",
    "x" * 150,          # 7+ versiya: versiya ma'lumoti ham tekshiriladi
    "y" * 400,
])
def test_encode_round_trip_and_structure(text):
    matrix = qr.encode(text)
    size = len(matrix)
    decoded, ver, ecl, mask = _decode(matrix)
    assert decoded == text
    assert size == ver * 4 + 17 and all(len(r) == size for r in matrix)
    assert "LMQH".index(ecl) >= "LMQH".index("M")  # kamida M (sig'sa — kuchliroq)
    for x0, y0 in ((0, 0), (size - 7, 0), (0, size - 7)):
        assert _finder_ok(matrix, x0, y0)
    assert all(matrix[6][i] == (i % 2 == 0) for i in range(8, size - 8))  # vaqt chiziqlari
    assert all(matrix[i][6] == (i % 2 == 0) for i in range(8, size - 8))
    assert matrix[size - 8][8] is True  # doim qora modul
    if ver >= 7:
        rem = ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        expected = ver << 12 | rem
        for i in range(18):
            bit = (expected >> i) & 1 == 1
            assert matrix[i // 3][size - 11 + i % 3] == bit and matrix[size - 11 + i % 3][i // 3] == bit


def test_too_long_text_rejected():
    with pytest.raises(ValueError):
        qr.encode("z" * 3000)


def test_svg_path_covers_dark_modules():
    data = qr.qr_path(FIXTURE_TEXT)
    dark = sum(row.count(True) for row in qr.encode(FIXTURE_TEXT))
    widths = [int(part.split("h")[1].split("v")[0]) for part in data["path"].split("M")[1:]]
    assert data["size"] == len(FIXTURE) + 8 and sum(widths) == dark
