"""Core implementation for WuddDropAlpha."""

from .image_common import _make_checkerboard, _parse_hex_color

class WuddDropAlpha:
    """
    用背景替换透明区域，丢掉 alpha 遮罩，输出不透明 RGB 图像。
    mask 未连接或全为不透明时直通。
    背景可选棋盘格或纯色填充，可选按内容区域自动裁剪。
    """

    _parse_hex_color = staticmethod(_parse_hex_color)
    _make_checkerboard = staticmethod(_make_checkerboard)

    @staticmethod
    def _crop_bounds(mask, padding, H, W):
        """
        mask: [B, H, W]，0=不透明内容区域
        返回跨 batch 取并集后加 padding 的裁剪范围 (y1, y2, x1, x2)。
        全透明时返回完整图像尺寸。
        """
        import torch

        content = mask < 0.5
        union = content.any(dim=0)
        rows = torch.where(union.any(dim=1))[0]
        if rows.numel() == 0:
            return 0, H, 0, W

        cols = torch.where(union.any(dim=0))[0]
        y1, y2, x1, x2 = torch.stack(
            (rows[0], rows[-1] + 1, cols[0], cols[-1] + 1)
        ).cpu().tolist()

        y1 = max(0, y1 - padding)
        y2 = min(H, y2 + padding)
        x1 = max(0, x1 - padding)
        x2 = min(W, x2 + padding)
        return y1, y2, x1, x2

    def drop_alpha(self, image, mode, fill_color, tile_size,
                   auto_crop=False, padding=0, mask=None):
        import torch

        if not isinstance(image, torch.Tensor):
            raise TypeError("image must be a torch.Tensor.")
        if image.ndim == 3:
            image = image.unsqueeze(0)
        if image.ndim != 4:
            raise ValueError(
                f"image must have shape [B, H, W, C], got {tuple(image.shape)}."
            )

        B, H, W, channels = image.shape
        if B < 1 or H < 1 or W < 1:
            raise ValueError("image has an empty batch or spatial dimension.")
        if channels not in (3, 4):
            raise ValueError(
                f"image must be RGB or RGBA, got {channels} channels."
            )

        rgb = image[..., :3]
        embedded_transparency = None
        if channels == 4:
            embedded_transparency = (1.0 - image[..., 3:4]).clamp(0.0, 1.0)

        explicit_transparency = None
        mask_batch = B
        if mask is not None:
            if not isinstance(mask, torch.Tensor):
                raise TypeError("mask must be a torch.Tensor when provided.")
            if mask.numel() == 0:
                raise ValueError("mask has an empty dimension.")

            # ComfyUI LoadImage returns a 64x64 all-zero placeholder mask for
            # images without alpha, regardless of the IMAGE dimensions.  The
            # legacy node treated any all-zero mask as disconnected before
            # inspecting its shape, so preserve that workflow behaviour while
            # still allowing embedded RGBA alpha to be processed below.
            if mask.max().item() <= 1e-5:
                mask = None

        if mask is not None:
            if mask.ndim == 2:
                mask = mask.unsqueeze(0)
            elif mask.ndim == 4:
                if tuple(mask.shape[1:]) == (H, W, 1):
                    mask = mask[..., 0]
                elif tuple(mask.shape[1:]) == (1, H, W):
                    mask = mask[:, 0]
                else:
                    raise ValueError(
                        "4D mask must have shape [B, H, W, 1] or [B, 1, H, W]."
                    )
            if mask.ndim != 3:
                raise ValueError(
                    f"mask must have shape [B, H, W], got {tuple(mask.shape)}."
                )
            if tuple(mask.shape[1:]) != (H, W):
                raise ValueError(
                    "mask spatial dimensions must match image; "
                    f"got {tuple(mask.shape[1:])} versus {(H, W)}."
                )
            mask_batch = int(mask.shape[0])
            if mask_batch < 1:
                raise ValueError("mask has an empty batch dimension.")
            explicit_transparency = mask.to(
                dtype=image.dtype, device=image.device
            ).clamp(0.0, 1.0).unsqueeze(-1)

        batch_size = max(B, mask_batch)
        if B not in (1, batch_size) or mask_batch not in (1, batch_size):
            raise ValueError(
                "image and mask batch sizes must match or be 1 for broadcasting; "
                f"got image={B}, mask={mask_batch}."
            )
        if B == 1 and batch_size > 1:
            rgb = rgb.expand(batch_size, -1, -1, -1)
            if embedded_transparency is not None:
                embedded_transparency = embedded_transparency.expand(
                    batch_size, -1, -1, -1
                )
        if explicit_transparency is not None and mask_batch == 1 and batch_size > 1:
            explicit_transparency = explicit_transparency.expand(
                batch_size, -1, -1, -1
            )

        if embedded_transparency is None:
            transparency = explicit_transparency
        elif explicit_transparency is None:
            transparency = embedded_transparency
        else:
            # RGBA alpha 与显式 ComfyUI mask 取透明区域并集。
            transparency = 1.0 - (
                (1.0 - embedded_transparency) * (1.0 - explicit_transparency)
            )

        # RGB 且无 mask，或所有像素都不透明：仍保证输出只有 RGB 三通道。
        if transparency is None or transparency.max().item() <= 1e-5:
            return (rgb.contiguous(),)

        if mode == "checkerboard":
            bg = self._make_checkerboard(
                H,
                W,
                tile_size,
                dtype=image.dtype,
                device=image.device,
            )
            bg = bg.unsqueeze(0).expand(batch_size, -1, -1, -1)
        else:  # fill_color
            r, g, b = self._parse_hex_color(fill_color)
            bg = torch.tensor([r, g, b], dtype=image.dtype,
                              device=image.device).view(1, 1, 1, 3).expand(
                                  batch_size, H, W, -1
                              )

        # mask 在 ComfyUI 中 1=透明，0=不透明
        result = (
            rgb * (1.0 - transparency) + bg * transparency
        ).clamp(0.0, 1.0)

        if auto_crop:
            y1, y2, x1, x2 = self._crop_bounds(
                transparency[..., 0], padding, H, W
            )
            result = result[:, y1:y2, x1:x2, :]

        return (result,)

__all__ = [
    "WuddDropAlpha",
]
