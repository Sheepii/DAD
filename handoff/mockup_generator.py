import io


def _get_image_module():
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "Pillow is required to generate mockups. Install it with: pip install Pillow"
        ) from exc
    return Image

from .drive import download_file_bytes, upload_mockup_bytes


def _open_rgba(data: bytes):
    Image = _get_image_module()
    return Image.open(io.BytesIO(data)).convert("RGBA")


def convert_svg_bytes(name: str, mime_type: str, data: bytes) -> tuple[str, bytes]:
    is_svg = name.lower().endswith(".svg") or mime_type == "image/svg+xml"
    if not is_svg:
        return name, data
    try:
        import cairosvg
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "cairosvg is required to render SVG. Install it with: pip install cairosvg"
        ) from exc
    png_bytes = cairosvg.svg2png(bytestring=data, output_width=4000, output_height=4000)
    if name.lower().endswith(".svg"):
        name = name[:-4] + ".png"
    return name, png_bytes


EXPECTED_SIZE = (4000, 4000)


def _ensure_size(image, label: str):
    Image = _get_image_module()
    if image.size != EXPECTED_SIZE:
        image = image.resize(EXPECTED_SIZE, Image.LANCZOS)
    return image


def render_mockup(
    design_bytes: bytes,
    background_bytes: bytes,
    overlay_bytes=None,
    mask_bytes=None,
    overlay_position: str = "OVER",
    design_box=None,
    design_boxes=None,
):
    Image = _get_image_module()
    background = _ensure_size(_open_rgba(background_bytes), "Background")
    design = _ensure_size(_open_rgba(design_bytes), "Design")

    design_layer = Image.new("RGBA", background.size, (0, 0, 0, 0))
    boxes = design_boxes or ([design_box] if design_box else [(0, 0, EXPECTED_SIZE[0], EXPECTED_SIZE[1])])
    for box in boxes:
        if len(box) == 5:
            x, y, w, h, rot = box
        else:
            x, y, w, h = box
            rot = 0
        w = max(1, min(EXPECTED_SIZE[0], int(w)))
        h = max(1, min(EXPECTED_SIZE[1], int(h)))
        x = max(0, min(EXPECTED_SIZE[0] - w, int(x)))
        y = max(0, min(EXPECTED_SIZE[1] - h, int(y)))
        resized = design.resize((w, h), Image.LANCZOS)
        if rot:
            resized = resized.rotate(rot, expand=True, resample=Image.BICUBIC)
            rw, rh = resized.size
            x = max(0, min(EXPECTED_SIZE[0] - rw, int(x)))
            y = max(0, min(EXPECTED_SIZE[1] - rh, int(y)))
        design_layer.paste(resized, (x, y), resized)

    if mask_bytes:
        mask = Image.open(io.BytesIO(mask_bytes)).convert("L")
        if mask.size != EXPECTED_SIZE:
            mask = mask.resize(EXPECTED_SIZE, Image.LANCZOS)
        transparent = Image.new("RGBA", background.size, (0, 0, 0, 0))
        design_layer = Image.composite(design_layer, transparent, mask)

    if overlay_bytes and overlay_position == "UNDER":
        overlay = _ensure_size(_open_rgba(overlay_bytes), "Overlay")
        composed = Image.alpha_composite(background, overlay)
        composed = Image.alpha_composite(composed, design_layer)
    else:
        composed = Image.alpha_composite(background, design_layer)
        if overlay_bytes:
            overlay = _ensure_size(_open_rgba(overlay_bytes), "Overlay")
            composed = Image.alpha_composite(composed, overlay)

    output = io.BytesIO()
    composed.save(output, format="PNG")
    return output.getvalue()


def generate_mockup_for_template(task, template):
    design_name, design_mime, design_bytes = download_file_bytes(task.drive_design_file_id)
    _, design_bytes = convert_svg_bytes(design_name, design_mime, design_bytes)
    bg_name, bg_mime, background_bytes = download_file_bytes(template.background_drive_file_id)
    _, background_bytes = convert_svg_bytes(bg_name, bg_mime, background_bytes)
    overlay_bytes = None
    mask_bytes = None
    if template.overlay_drive_file_id:
        ov_name, ov_mime, overlay_bytes = download_file_bytes(template.overlay_drive_file_id)
        _, overlay_bytes = convert_svg_bytes(ov_name, ov_mime, overlay_bytes)
    if template.mask_drive_file_id:
        mk_name, mk_mime, mask_bytes = download_file_bytes(template.mask_drive_file_id)
        _, mask_bytes = convert_svg_bytes(mk_name, mk_mime, mask_bytes)

    design_boxes = [
        (box.x, box.y, box.width, box.height, box.rotation)
        for box in template.design_boxes.all()
    ]
    png_bytes = render_mockup(
        design_bytes=design_bytes,
        background_bytes=background_bytes,
        overlay_bytes=overlay_bytes,
        mask_bytes=mask_bytes,
        overlay_position=template.overlay_position,
        design_box=(
            template.design_x,
            template.design_y,
            template.design_width,
            template.design_height,
        ),
        design_boxes=design_boxes,
    )
    label = template.label or f"mockup-{template.order}"
    filename = f"{label}.png"
    file_id = upload_mockup_bytes(png_bytes, filename, due_date=task.due_date)
    return file_id, filename


def preview_mockup_for_template(template, design_bytes: bytes):
    _, _, background_bytes = download_file_bytes(template.background_drive_file_id)
    overlay_bytes = None
    mask_bytes = None
    if template.overlay_drive_file_id:
        _, overlay_bytes = download_file_bytes(template.overlay_drive_file_id)
    if template.mask_drive_file_id:
        _, mask_bytes = download_file_bytes(template.mask_drive_file_id)

    design_boxes = [
        (box.x, box.y, box.width, box.height, box.rotation)
        for box in template.design_boxes.all()
    ]
    png_bytes = render_mockup(
        design_bytes=design_bytes,
        background_bytes=background_bytes,
        overlay_bytes=overlay_bytes,
        mask_bytes=mask_bytes,
        overlay_position=template.overlay_position,
        design_box=(
            template.design_x,
            template.design_y,
            template.design_width,
            template.design_height,
        ),
        design_boxes=design_boxes,
    )
    return png_bytes
