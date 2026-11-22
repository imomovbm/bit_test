"""QR kod yaratish (ISO/IEC 18004): bayt rejimi, xatoni tuzatish darajalari L/M/Q/H, 1–40 versiyalar.

Tashqi kutubxonasiz: Octagon lobbisidagi QR kod (o'quvchilar telefoni bilan skanerlab o'yinga qo'shiladi) shu yerda
yaratiladi. Algoritm Project Nayuki'ning ochiq "QR Code generator" kutubxonasi tavsifiga asoslangan.
"""
from __future__ import annotations

from collections import deque

# Xatoni tuzatish darajalari: (format bitlari, jadval indeksi)
ECC_LEVELS = {"L": (1, 0), "M": (0, 1), "Q": (3, 2), "H": (2, 3)}

# Har bir blokdagi xato tuzatish kodlari soni [daraja][versiya] (0-indeks ishlatilmaydi)
ECC_CODEWORDS_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
# Xato tuzatish bloklari soni [daraja][versiya]
NUM_ERROR_CORRECTION_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)

PENALTY_N1, PENALTY_N2, PENALTY_N3, PENALTY_N4 = 3, 3, 40, 10

_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def _bit(x: int, i: int) -> bool:
    return (x >> i) & 1 != 0


def num_raw_data_modules(ver: int) -> int:
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        numalign = ver // 7 + 2
        result -= (25 * numalign - 10) * numalign - 55
        if ver >= 7:
            result -= 36
    return result


def num_data_codewords(ver: int, ecl: str) -> int:
    e = ECC_LEVELS[ecl][1]
    return num_raw_data_modules(ver) // 8 - ECC_CODEWORDS_PER_BLOCK[e][ver] * NUM_ERROR_CORRECTION_BLOCKS[e][ver]


# ------------------------------------------------------------ Reed–Solomon
def _rs_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_multiply(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_multiply(coef, factor)
    return result


# ------------------------------------------------------------------ kodlash
def _encode_data(data: bytes, ecl: str, min_version: int = 1) -> tuple[int, str, list[int]]:
    """Mos versiyani tanlaydi va ma'lumot kodlarini (codewords) tayyorlaydi. Sig'sa, xato tuzatish darajasi oshiriladi."""
    for ver in range(min_version, 41):
        count_bits = 8 if ver <= 9 else 16
        used = 4 + count_bits + len(data) * 8
        if used <= num_data_codewords(ver, ecl) * 8:
            break
    else:
        raise ValueError("Matn QR kod uchun juda uzun")
    for better in ("M", "Q", "H"):  # xuddi shu versiyaga sig'sa — kuchliroq xato tuzatish
        if "LMQH".index(better) > "LMQH".index(ecl) and used <= num_data_codewords(ver, better) * 8:
            ecl = better
    bits: list[int] = []

    def append(val: int, n: int) -> None:
        bits.extend((val >> i) & 1 for i in reversed(range(n)))

    append(0b0100, 4)  # bayt rejimi
    append(len(data), count_bits)
    for b in data:
        append(b, 8)
    capacity = num_data_codewords(ver, ecl) * 8
    append(0, min(4, capacity - len(bits)))
    append(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < capacity:
        append(pad, 8)
        pad ^= 0xEC ^ 0x11
    codewords = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    return ver, ecl, codewords


def _add_ecc_and_interleave(data: list[int], ver: int, ecl: str) -> list[int]:
    e = ECC_LEVELS[ecl][1]
    numblocks = NUM_ERROR_CORRECTION_BLOCKS[e][ver]
    blockecclen = ECC_CODEWORDS_PER_BLOCK[e][ver]
    rawcodewords = num_raw_data_modules(ver) // 8
    numshortblocks = numblocks - rawcodewords % numblocks
    shortblocklen = rawcodewords // numblocks
    divisor = _rs_divisor(blockecclen)
    blocks, k = [], 0
    for i in range(numblocks):
        dat = data[k:k + shortblocklen - blockecclen + (0 if i < numshortblocks else 1)]
        k += len(dat)
        ecc = _rs_remainder(dat, divisor)
        if i < numshortblocks:
            dat = dat + [0]
        blocks.append(dat + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != shortblocklen - blockecclen or j >= numshortblocks:
                result.append(blk[i])
    return result


class _Matrix:
    def __init__(self, ver: int, ecl: str):
        self.ver, self.ecl = ver, ecl
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.isfunction = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.isfunction[y][x] = True

    def alignment_positions(self) -> list[int]:
        if self.ver == 1:
            return []
        numalign = self.ver // 7 + 2
        step = (self.ver * 8 + numalign * 3 + 5) // (numalign * 4 - 4) * 2
        result = [self.size - 7 - i * step for i in range(numalign - 1)] + [6]
        return list(reversed(result))

    def draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for x, y in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < size and 0 <= yy < size:
                        self.set_function(xx, yy, max(abs(dx), abs(dy)) not in (2, 4))
        positions = self.alignment_positions()
        n = len(positions)
        for i in range(n):
            for j in range(n):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(positions[i] + dx, positions[j] + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format_bits(0)
        self.draw_version()

    def draw_format_bits(self, mask: int) -> None:
        data = ECC_LEVELS[self.ecl][0] << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        for i in range(0, 6):
            self.set_function(8, i, _bit(bits, i))
        self.set_function(8, 7, _bit(bits, 6))
        self.set_function(8, 8, _bit(bits, 7))
        self.set_function(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, _bit(bits, i))
        size = self.size
        for i in range(0, 8):
            self.set_function(size - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self.set_function(8, size - 15 + i, _bit(bits, i))
        self.set_function(8, size - 8, True)  # doim qora modul

    def draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = self.ver << 12 | rem
        for i in range(18):
            bit = _bit(bits, i)
            a, b = self.size - 11 + i % 3, i // 3
            self.set_function(a, b, bit)
            self.set_function(b, a, bit)

    def draw_codewords(self, data: list[int]) -> None:
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(size):
                for j in range(2):
                    x = right - j
                    upward = (right + 1) & 2 == 0
                    y = size - 1 - vert if upward else vert
                    if not self.isfunction[y][x] and i < len(data) * 8:
                        self.modules[y][x] = _bit(data[i >> 3], 7 - (i & 7))
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        fn = _MASKS[mask]
        for y in range(self.size):
            row, func = self.modules[y], self.isfunction[y]
            for x in range(self.size):
                if not func[x] and fn(x, y):
                    row[x] = not row[x]

    # -------------------------------------------------------- jarima ballari
    def _finder_count(self, history: deque) -> int:
        n = history[1]
        core = n > 0 and history[2] == history[4] == history[5] == n and history[3] == n * 3
        return (1 if core and history[0] >= n * 4 and history[6] >= n else 0) + (1 if core and history[6] >= n * 4 and history[0] >= n else 0)

    def _finder_add(self, run: int, history: deque) -> None:
        if history[0] == 0:
            run += self.size  # chap tomondagi oq chegara
        history.appendleft(run)

    def _finder_terminate(self, color: bool, run: int, history: deque) -> int:
        if color:
            self._finder_add(run, history)
            run = 0
        run += self.size  # o'ng tomondagi oq chegara
        self._finder_add(run, history)
        return self._finder_count(history)

    def _line_penalty(self, line: list[bool]) -> int:
        result = 0
        color = False
        run = 0
        history: deque = deque([0] * 7, 7)
        for cell in line:
            if cell == color:
                run += 1
                if run == 5:
                    result += PENALTY_N1
                elif run > 5:
                    result += 1
            else:
                self._finder_add(run, history)
                if not color:
                    result += self._finder_count(history) * PENALTY_N3
                color = cell
                run = 1
        result += self._finder_terminate(color, run, history) * PENALTY_N3
        return result

    def penalty(self) -> int:
        size, m = self.size, self.modules
        result = sum(self._line_penalty(m[y]) for y in range(size))
        result += sum(self._line_penalty([m[y][x] for y in range(size)]) for x in range(size))
        for y in range(size - 1):
            for x in range(size - 1):
                c = m[y][x]
                if c == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    result += PENALTY_N2
        dark = sum(row.count(True) for row in m)
        total = size * size
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        result += k * PENALTY_N4
        return result


def encode(text: str, ecl: str = "M", mask: int | None = None, min_version: int = 1) -> list[list[bool]]:
    """Matnni QR kod matritsasiga aylantiradi (True — qora modul). Chegara (quiet zone) qo'shilmaydi."""
    data = text.encode("utf-8")
    ver, ecl, codewords = _encode_data(data, ecl, min_version)
    allcodewords = _add_ecc_and_interleave(codewords, ver, ecl)
    qr = _Matrix(ver, ecl)
    qr.draw_function_patterns()
    qr.draw_codewords(allcodewords)
    if mask is None:  # eng kam jarimali niqob
        best, best_penalty = 0, None
        for m in range(8):
            qr.apply_mask(m)
            qr.draw_format_bits(m)
            p = qr.penalty()
            if best_penalty is None or p < best_penalty:
                best, best_penalty = m, p
            qr.apply_mask(m)  # XOR — qaytarib olamiz
        mask = best
    qr.apply_mask(mask)
    qr.draw_format_bits(mask)
    return qr.modules


def qr_path(text: str, border: int = 4) -> dict:
    """SVG uchun ixcham yo'l: {"size": modullar soni (chegara bilan), "path": "M..h..v..h..z"}."""
    modules = encode(text)
    parts = []
    for y, row in enumerate(modules):
        x = 0
        n = len(row)
        while x < n:
            if row[x]:
                start = x
                while x < n and row[x]:
                    x += 1
                parts.append(f"M{start + border} {y + border}h{x - start}v1h-{x - start}z")
            else:
                x += 1
    return {"size": len(modules) + border * 2, "path": "".join(parts)}
