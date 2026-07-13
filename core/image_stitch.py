"""Core implementation for WuddImageStitch."""

import torch
import torch.nn.functional as F

from .common import collect_image_inputs


class WuddImageStitch:
    """Linearly stitch image batches while preserving tensor device and dtype."""

    MAX_INPUTS = 16

    @staticmethod
    def _fit_height(image, target_height):
        if image.shape[1] == target_height:
            return image
        width = max(1, round(image.shape[2] * target_height / image.shape[1]))
        resized = F.interpolate(
            image.movedim(-1, 1),
            size=(target_height, width),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        )
        return resized.movedim(1, -1).clamp_(0.0, 1.0)

    @staticmethod
    def _fit_width(image, target_width):
        if image.shape[2] == target_width:
            return image
        height = max(1, round(image.shape[1] * target_width / image.shape[2]))
        resized = F.interpolate(
            image.movedim(-1, 1),
            size=(height, target_width),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        )
        return resized.movedim(1, -1).clamp_(0.0, 1.0)

    def stitch(self, image_1, direction, gap, input_count, **kwargs):
        max_inputs = max(1, min(int(input_count), self.MAX_INPUTS))
        images = collect_image_inputs(image_1, kwargs, max_n=max_inputs)

        normalised = []
        for index, image in enumerate(images, start=1):
            if not isinstance(image, torch.Tensor):
                raise TypeError(f"image_{index} must be a torch.Tensor.")
            if image.ndim == 3:
                image = image.unsqueeze(0)
            if image.ndim != 4:
                raise ValueError(
                    f"image_{index} must have shape [B, H, W, C], "
                    f"got {tuple(image.shape)}."
                )
            if image.shape[0] < 1 or image.shape[1] < 1 or image.shape[2] < 1:
                raise ValueError(
                    f"image_{index} has an empty batch or spatial dimension."
                )
            normalised.append(image)

        if len(normalised) == 1:
            return (normalised[0],)

        channels = {int(image.shape[-1]) for image in normalised}
        if len(channels) != 1:
            raise ValueError(
                "ImageStitch inputs must use the same channel count; "
                f"got {sorted(channels)}."
            )

        batch_size = max(int(image.shape[0]) for image in normalised)
        invalid_batches = [
            int(image.shape[0])
            for image in normalised
            if int(image.shape[0]) not in (1, batch_size)
        ]
        if invalid_batches:
            sizes = [int(image.shape[0]) for image in normalised]
            raise ValueError(
                "ImageStitch batch sizes must match or be 1 for broadcasting; "
                f"got {sizes}."
            )

        images = [
            image.expand(batch_size, -1, -1, -1)
            if image.shape[0] == 1 and batch_size > 1
            else image
            for image in normalised
        ]
        _, reference_height, reference_width, channels = images[0].shape
        horizontal = direction in ("right", "left")
        reference_device = images[0].device
        reference_dtype = images[0].dtype

        scaled = []
        for image in images:
            fitted = (
                self._fit_height(image, reference_height)
                if horizontal
                else self._fit_width(image, reference_width)
            )
            if fitted.device != reference_device or fitted.dtype != reference_dtype:
                fitted = fitted.to(device=reference_device, dtype=reference_dtype)
            scaled.append(fitted)

        ordered = list(reversed(scaled[1:])) + [scaled[0]] if direction in ("left", "up") else scaled
        axis = 2 if horizontal else 1
        gap = max(0, int(gap))
        pieces = []
        for index, image in enumerate(ordered):
            if index and gap:
                shape = list(image.shape)
                shape[axis] = gap
                pieces.append(torch.zeros(shape, device=reference_device, dtype=reference_dtype))
            pieces.append(image)
        return (torch.cat(pieces, dim=axis),)


__all__ = ["WuddImageStitch"]
