# big_digits_draw.py
import micropython
import big_digits

@micropython.viper
def _blit_1bpp_to_rgb565(dst, dst_off: int, dst_stride: int,
                        src, src_stride: int, w: int, h: int,
                        fg: int, bg: int):
    """
    Writes BOTH fg and bg pixels (so no separate clear is needed).
    dst: lcd.buffer (RGB565)
    src: packed 1bpp rows
    """
    d16 = ptr16(dst)
    s8 = ptr8(src)

    # Convert byte stride -> 16-bit stride once
    dst_stride16 = dst_stride >> 1
    dst_off16 = dst_off >> 1

    row = 0
    while row < h:
        si = row * src_stride
        di = dst_off16 + (row * dst_stride16)

        x = 0
        # Process 8 pixels per source byte
        while x < w:
            b = s8[si + (x >> 3)]
            # Unroll 8 bits (only write those inside width)
            # Bit 7
            if x < w:
                d16[di + x] = fg if (b & 0x80) else bg
                x += 1
            # Bit 6
            if x < w:
                d16[di + x] = fg if (b & 0x40) else bg
                x += 1
            # Bit 5
            if x < w:
                d16[di + x] = fg if (b & 0x20) else bg
                x += 1
            # Bit 4
            if x < w:
                d16[di + x] = fg if (b & 0x10) else bg
                x += 1
            # Bit 3
            if x < w:
                d16[di + x] = fg if (b & 0x08) else bg
                x += 1
            # Bit 2
            if x < w:
                d16[di + x] = fg if (b & 0x04) else bg
                x += 1
            # Bit 1
            if x < w:
                d16[di + x] = fg if (b & 0x02) else bg
                x += 1
            # Bit 0
            if x < w:
                d16[di + x] = fg if (b & 0x01) else bg
                x += 1

        row += 1


def measure_big_text(text, spacing=2):
    """
    Returns (w, h). Useful for centering and dirty rect sizing.
    """
    H = big_digits.HEIGHT
    x = 0
    any_glyph = False
    for ch in text:
        g = big_digits.GLYPHS.get(ch)
        if not g:
            continue
        any_glyph = True
        x += g[0] + spacing
    if not any_glyph:
        return (0, 0)
    return (x - spacing, H)


def draw_big_text(lcd, text, x, y, fg=0xFFFF, bg=0x0000, spacing=2, flush=True):
    """
    Requires:
      - lcd.buffer (RGB565 framebuffer)
      - lcd.show_rect(x,y,w,h) OR you can set flush=False and flush yourself

    Draws using baked glyphs, no Writer, no large_font import.

    Returns (x, y, w, h) of the region touched (for your caller to flush once).
    """
    H = big_digits.HEIGHT

    total_w, _ = measure_big_text(text, spacing=spacing)
    if total_w <= 0:
        return (x, y, 0, 0)

    cx = x
    dst_stride = lcd.width * 2

    for ch in text:
        g = big_digits.GLYPHS.get(ch)
        if not g:
            continue
        w, h, src_stride, src_bytes = g

        dst_off = (y * dst_stride) + (cx * 2)

        _blit_1bpp_to_rgb565(
            lcd.buffer, dst_off, dst_stride,
            src_bytes, src_stride, w, h,
            fg, bg
        )
        cx += w + spacing

    if flush:
        lcd.show_rect(x, y, total_w, H)

    return (x, y, total_w, H)

