"""توليد ريل رأسي من صورة الخبر وعنوانه — بلا تكلفة ولا خدمة خارجية.

الفكرة: لا نولّد شيئًا جديدًا، بل نحرّك ما نملكه. صورة الخبر تتقرّب ببطء
(تأثير Ken Burns)، والعنوان يظهر سطرًا بعد سطر، والشعار ثابت. بلا صوت،
لأن أغلب متصفّحي فيسبوك يشاهدون صامتًا.

النص العربي يُرسم بـ Pillow لا بـ drawtext الخاصة بـ ffmpeg، لأن الأخيرة
لا تصل الحروف العربية ولا تعالج اتجاه الكتابة. نصنع طبقات PNG شفافة
ونركّبها على الفيديو، فنحتفظ بجودة التشكيل نفسها التي في الصور.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from .config import resolve
from .imaging import (
    cover,
    download_image,
    draw_text,
    find_logo,
    fit_text,
    hex_rgb,
    load_font,
    measure,
    mix,
    paste_logo,
    placeholder,
)

log = logging.getLogger(__name__)

W, H = 1080, 1920          # 9:16 — مقاس الريلز والستوري


def ffmpeg_path() -> str | None:
    """
    يحدد مسار ffmpeg.

    الأولوية لنسخة pip المضمّنة (imageio-ffmpeg): تُثبَّت مع بقية المكتبات
    ولا تعتمد على apt. الاعتماد على apt كان يعلّق التشغيل 25 دقيقة حين
    تتأخر مرايا أوبونتو، فيُلغى قبل أن يبدأ جمع الأخبار أصلًا.
    """
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and Path(exe).exists():
            return exe
    except Exception:  # noqa: BLE001 — غير مثبّتة أو تعذّر تحديد الملف
        pass
    return shutil.which("ffmpeg")


def has_ffmpeg() -> bool:
    return ffmpeg_path() is not None


# ──────────────────────────── الطبقات ────────────────────────────


def build_layers(headline: str, category: str, urgent: bool, cfg,
                 folder: Path) -> tuple[list[Path], Path]:
    """
    يبني طبقات PNG شفافة: الترويسة، ثم سطور العنوان واحدًا واحدًا.

    يعيد (قائمة الطبقات بالترتيب، طبقة التعتيم السفلي).
    """
    primary = hex_rgb(cfg.path("brand.primary_color", "#12203A"))
    accent = hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
    f_head = cfg.path("image.font_headline")
    f_body = cfg.path("image.font_body") or f_head
    head_weight = cfg.path("image.font_headline_weight") or None
    body_weight = cfg.path("image.font_body_weight") or None
    margin = int(W * 0.07)

    probe = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    pd = ImageDraw.Draw(probe)

    # تعتيم متدرّج أسفل الإطار ليُقرأ النص فوق أي صورة
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    top = int(H * 0.42)
    for y in range(top, H):
        ratio = (y - top) / max(H - top, 1)
        sd.line([(0, y), (W, y)], fill=(*mix(primary, (0, 0, 0), 0.45),
                                        int(235 * ratio ** 1.4)))
    header_h = int(H * 0.11)
    for y in range(header_h):
        sd.line([(0, y), (W, y)],
                fill=(*primary, int(215 * (1 - y / header_h) ** 0.8)))
    shade_path = folder / "shade.png"
    shade.save(shade_path)

    layers: list[Path] = []

    # الطبقة الأولى: الشعار والملصق
    head = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    hd = ImageDraw.Draw(head)
    logo_rel = cfg.path("brand.logo")
    logo_bottom = int(H * 0.035)
    if logo_rel:
        logo_file = find_logo(logo_rel)
        if logo_file:
            box_h = int(H * 0.055 * float(cfg.path("brand.logo_scale", 1.0)))
            paste_logo(head, logo_file,
                       (W - margin - int(W * 0.55), logo_bottom,
                        W - margin, logo_bottom + box_h))
            hd = ImageDraw.Draw(head)

    badge_font = load_font(f_body, int(W * 0.030), body_weight)
    bx, by = margin, logo_bottom + int(H * 0.012)
    for text, bg, fg in ([("عاجل", (206, 32, 39), (255, 255, 255))] if urgent else []) \
            + ([(category, accent, primary)] if category else []):
        tw, th = measure(hd, text, badge_font)
        pad = int(W * 0.022)
        hd.rounded_rectangle([bx, by, bx + tw + pad * 2, by + th + pad],
                             radius=int((th + pad) / 2), fill=bg)
        draw_text(hd, (bx + pad + tw // 2, by + (th + pad) // 2), text,
                  badge_font, fg, anchor="mm")
        bx += tw + pad * 2 + int(W * 0.018)

    head_path = folder / "layer_0.png"
    head.save(head_path)
    layers.append(head_path)

    # سطور العنوان: طبقة لكل سطر لتظهر تباعًا
    font, lines, line_h = fit_text(
        pd, headline, f_head, max_width=W - margin * 2,
        max_lines=5, start=int(W * 0.075), minimum=int(W * 0.045),
        weight=head_weight,
    )
    block_bottom = int(H * 0.80)
    y0 = block_bottom - len(lines) * line_h

    for index, line in enumerate(lines):
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        y = y0 + index * line_h + line_h // 2
        draw_text(ld, (W - margin, y), line, font, (255, 255, 255), anchor="rm")
        path = folder / f"layer_{index + 1}.png"
        layer.save(path)
        layers.append(path)

    # شريط ذهبي وخاتمة المعرّف
    tail = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tail)
    td.rounded_rectangle(
        [W - margin - int(W * 0.30), block_bottom + int(H * 0.018),
         W - margin, block_bottom + int(H * 0.024)],
        radius=4, fill=accent)
    handle = cfg.path("brand.handle", "")
    if handle:
        hf = load_font(f_body, int(W * 0.028), body_weight)
        draw_text(td, (W - margin, block_bottom + int(H * 0.048)), handle, hf,
                  mix(accent, (255, 255, 255), 0.35), anchor="rm")
    tail_path = folder / f"layer_{len(lines) + 1}.png"
    tail.save(tail_path)
    layers.append(tail_path)

    return layers, shade_path


# ──────────────────────────── الخلفية ────────────────────────────


def background(image_urls, cfg, folder: Path) -> tuple[Path, bool]:
    """يجهّز صورة الخلفية بمقاس 9:16. يعيد (المسار، هل هي صورة حقيقية)."""
    urls = [image_urls] if isinstance(image_urls, str) else list(image_urls or [])
    source = None
    for url in urls[:6]:
        source = download_image(url)
        if source is not None:
            break

    if source is None:
        primary = hex_rgb(cfg.path("brand.primary_color", "#12203A"))
        accent = hex_rgb(cfg.path("brand.accent_color", "#F0B429"))
        canvas = placeholder(W, H, primary, accent)
        used = False
    else:
        # نكبّر قليلًا لأن التقريب سيقتطع من الحواف
        canvas = cover(source, int(W * 1.15), int(H * 1.15))
        used = True

    path = folder / "bg.jpg"
    canvas.convert("RGB").save(path, "JPEG", quality=92)
    return path, used


# ──────────────────────────── التركيب ────────────────────────────


def build_reel(headline: str, category: str, urgent: bool, image_urls,
               cfg, out_path: Path) -> Path | None:
    """
    يبني الريل كاملًا. يعيد None عند أي فشل — والصورة تبقى بديلًا صالحًا،
    فلا نخسر المنشور بسبب الفيديو.
    """
    if not has_ffmpeg():
        log.warning("ffmpeg غير متاح — تخطي توليد الريل")
        return None

    rcfg = cfg.get("reel", {}) or {}
    duration = float(rcfg.get("duration_seconds", 10))
    fps = int(rcfg.get("fps", 30))
    zoom = float(rcfg.get("zoom", 1.12))

    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        try:
            bg_path, _ = background(image_urls, cfg, folder)
            layers, shade = build_layers(headline, category, urgent, cfg, folder)
        except Exception as exc:  # noqa: BLE001
            log.warning("تعذّر تجهيز طبقات الريل: %s", exc)
            return None

        frames = int(duration * fps)
        cmd = [ffmpeg_path() or "ffmpeg", "-y", "-loglevel", "error",
               "-loop", "1", "-t", f"{duration}", "-i", str(bg_path),
               "-loop", "1", "-t", f"{duration}", "-i", str(shade)]
        for layer in layers:
            cmd += ["-loop", "1", "-t", f"{duration}", "-i", str(layer)]

        # تقريب بطيء ثابت المركز
        chain = [
            f"[0:v]scale={int(W*1.15)}:{int(H*1.15)},"
            f"zoompan=z='min(1+({zoom}-1)*on/{frames},{zoom})'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={W}x{H}:fps={fps}[bgz]",
            f"[bgz][1:v]overlay=0:0[base]",
        ]

        # كل طبقة تظهر بتلاشٍ متدرّج
        start = float(rcfg.get("first_layer_at", 0.4))
        step = float(rcfg.get("layer_step", 0.45))
        current = "base"
        for index in range(len(layers)):
            at = start + step * index
            src = f"{index + 2}:v"
            chain.append(f"[{src}]fade=t=in:st={at:.2f}:d=0.45:alpha=1[l{index}]")
            nxt = f"c{index}"
            chain.append(f"[{current}][l{index}]overlay=0:0:format=auto[{nxt}]")
            current = nxt

        chain.append(f"[{current}]format=yuv420p[v]")
        cmd += ["-filter_complex", ";".join(chain), "-map", "[v]",
                "-c:v", "libx264", "-preset", str(rcfg.get("preset", "veryfast")),
                "-crf", str(int(rcfg.get("crf", 24))),
                "-movflags", "+faststart", "-r", str(fps),
                "-t", f"{duration}", str(out_path)]

        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=int(rcfg.get("timeout", 180)))
        except subprocess.TimeoutExpired:
            log.warning("انتهت مهلة توليد الريل")
            return None

        if proc.returncode != 0 or not out_path.exists():
            log.warning("فشل ffmpeg: %s", (proc.stderr or "")[-300:])
            return None

    size_mb = out_path.stat().st_size / 1_048_576
    log.info("🎬 الريل جاهز: %s (%.1f ميغابايت، %d ثانية)",
             out_path.name, size_mb, int(duration))
    return out_path
