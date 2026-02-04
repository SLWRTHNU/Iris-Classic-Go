# make_big_digits.py
# Run once to generate big_digits.py from large_font.py, then delete this file if you want.

CHARS = "0123456789."
OUT = "big_digits.py"

import large_font

def _stride_bytes(width):
    # 1bpp, packed bits, MSB-first per byte
    return ((width - 1) // 8) + 1

def main():
    glyphs = {}
    max_w = 0
    h_ref = None

    for ch in CHARS:
        data, h, w = large_font.get_ch(ch)
        if h_ref is None:
            h_ref = h
        if h != h_ref:
            raise ValueError("Height mismatch: %r has %d, expected %d" % (ch, h, h_ref))

        sb = _stride_bytes(w)
        # Make an owned bytes object (not a memoryview slice)
        b = bytes(data)

        glyphs[ch] = (w, h, sb, b)
        if w > max_w:
            max_w = w

    with open(OUT, "w") as f:
        f.write("# Auto-generated from large_font.py\n")
        f.write("HEIGHT = %d\n" % h_ref)
        f.write("GLYPHS = {\n")
        for ch in CHARS:
            w, h, sb, b = glyphs[ch]
            f.write("    %r: (%d, %d, %d, %r),\n" % (ch, w, h, sb, b))
        f.write("}\n")

    print("Wrote", OUT, "chars:", CHARS, "height:", h_ref, "max_w:", max_w)

if __name__ == "__main__":
    main()

