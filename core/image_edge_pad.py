"""Torch-native edge padding for vertically stitched image workflows."""

import math

import torch
import torch.nn.functional as F

from .common import collect_image_inputs


class WuddEdgePad:
    MAX_INPUTS = 16

    @staticmethod
    def _gaussian_kernel(sigma, extent, device, dtype):
        if sigma <= 0 or extent <= 1:
            return None, 0
        radius = min(max(1, int(4.0 * sigma + 0.5)), extent - 1)
        positions = torch.arange(-radius, radius + 1, device=device, dtype=dtype)
        kernel = torch.exp(-(positions * positions) / (2.0 * sigma * sigma))
        return kernel / kernel.sum(), radius

    @classmethod
    def _gaussian_blur(cls, image, sigma_y, sigma_x):
        """Apply a separable Gaussian blur to a BHWC tensor."""
        if sigma_y <= 0 and sigma_x <= 0:
            return image
        work = image.movedim(-1, 1)
        channels = work.shape[1]

        kernel_y, radius_y = cls._gaussian_kernel(
            sigma_y, work.shape[2], work.device, work.dtype
        )
        if kernel_y is not None:
            weight_y = kernel_y.view(1, 1, -1, 1).expand(channels, 1, -1, 1)
            work = F.conv2d(
                F.pad(work, (0, 0, radius_y, radius_y), mode="reflect"),
                weight_y,
                groups=channels,
            )

        kernel_x, radius_x = cls._gaussian_kernel(
            sigma_x, work.shape[3], work.device, work.dtype
        )
        if kernel_x is not None:
            weight_x = kernel_x.view(1, 1, 1, -1).expand(channels, 1, 1, -1)
            work = F.conv2d(
                F.pad(work, (radius_x, radius_x, 0, 0), mode="reflect"),
                weight_x,
                groups=channels,
            )
        return work.movedim(1, -1)

    @staticmethod
    def _resize_edge_rows(rows, target_height, target_width, reference):
        if rows.device != reference.device or rows.dtype != reference.dtype:
            rows = rows.to(device=reference.device, dtype=reference.dtype)
        if rows.shape[1] == target_height and rows.shape[2] == target_width:
            return rows
        resized = F.interpolate(
            rows.movedim(-1, 1),
            size=(target_height, target_width),
            mode="bilinear",
            align_corners=False,
        )
        return resized.movedim(1, -1)

    @classmethod
    def _edge_pad(cls, edge_rows, pad_px, sigma):
        edge_rows = cls._resize_edge_rows(
            edge_rows, pad_px, edge_rows.shape[2], edge_rows
        )
        return cls._gaussian_blur(
            edge_rows.flip(1), float(sigma), float(sigma) * 0.3
        )

    @classmethod
    def _cross_blend_pad(cls, a_bottom, b_top, pad_px, sigma):
        def blend_for(reference):
            target_width = reference.shape[2]
            a_rows = cls._resize_edge_rows(a_bottom, pad_px, target_width, reference)
            b_rows = cls._resize_edge_rows(b_top, pad_px, target_width, reference)
            combined = torch.cat((a_rows, b_rows), dim=1)
            return cls._gaussian_blur(
                combined, float(sigma), float(sigma) * 0.3
            )

        blended_a = blend_for(a_bottom)
        same_target = (
            a_bottom.shape[2] == b_top.shape[2]
            and a_bottom.device == b_top.device
            and a_bottom.dtype == b_top.dtype
        )
        blended_b = blended_a if same_target else blend_for(b_top)
        return blended_a[:, :pad_px], blended_b[:, pad_px:]

    @staticmethod
    def _chamfer(image, chamfer_rows):
        if chamfer_rows <= 0:
            return image
        height = image.shape[1]
        chamfer_rows = min(chamfer_rows, height)
        top_color = image[:, :chamfer_rows].mean(dim=(1, 2), keepdim=True)
        bottom_color = image[:, height - chamfer_rows :].mean(
            dim=(1, 2), keepdim=True
        )
        t = torch.linspace(
            0.0,
            1.0,
            chamfer_rows,
            device=image.device,
            dtype=image.dtype,
        ).view(1, chamfer_rows, 1, 1)
        alpha = t * t * (3.0 - 2.0 * t)
        result = image.clone()
        result[:, :chamfer_rows] = (
            image[:, :chamfer_rows] * alpha + top_color * (1.0 - alpha)
        )
        reverse_alpha = alpha.flip(1)
        result[:, height - chamfer_rows :] = (
            image[:, height - chamfer_rows :] * reverse_alpha
            + bottom_color * (1.0 - reverse_alpha)
        )
        return result

    @classmethod
    def _blend_junction_band(cls, canvas, junction, blend_rows, sigma):
        total_height = canvas.shape[1]
        band_start = max(0, junction - blend_rows)
        band_end = min(total_height, junction + blend_rows)
        if band_end <= band_start:
            return canvas

        halo = int(math.ceil(4.0 * max(0.0, float(sigma))))
        region_start = max(0, band_start - halo)
        region_end = min(total_height, band_end + halo)
        region = canvas[:, region_start:region_end]
        blurred = cls._gaussian_blur(region, float(sigma), float(sigma) * 0.3)
        blurred_band = blurred[
            :, band_start - region_start : band_end - region_start
        ]

        positions = torch.arange(
            band_start,
            band_end,
            device=canvas.device,
            dtype=canvas.dtype,
        )
        phase = (positions - junction) / blend_rows
        weight = (0.5 * (1.0 + torch.cos(phase * torch.pi))).view(
            1, -1, 1, 1
        )
        result = canvas.clone()
        result[:, band_start:band_end] = (
            canvas[:, band_start:band_end] * (1.0 - weight)
            + blurred_band * weight
        )
        return result

    @classmethod
    def _blend_junctions(cls, canvas, pad_px, image_height, blend_rows, sigma):
        canvas = cls._blend_junction_band(
            canvas, pad_px, blend_rows, sigma
        )
        return cls._blend_junction_band(
            canvas, pad_px + image_height, blend_rows, sigma
        )

    @classmethod
    def _pad_batches(
        cls,
        images,
        pad_px,
        blend_pct,
        pad_sigma,
        blend_sigma,
        chamfer_pct,
    ):
        count = len(images)
        top_pads = [None] * count
        bottom_pads = [None] * count

        for index, image in enumerate(images):
            height = image.shape[1]
            grab = min(pad_px, height)
            if index == 0:
                top_pads[0] = cls._edge_pad(image[:, :grab], pad_px, pad_sigma)
            if index == count - 1:
                bottom_pads[-1] = cls._edge_pad(
                    image[:, height - grab :], pad_px, pad_sigma
                )
            if index < count - 1:
                next_image = images[index + 1]
                next_grab = min(pad_px, next_image.shape[1])
                bottom_pads[index], top_pads[index + 1] = cls._cross_blend_pad(
                    image[:, height - grab :],
                    next_image[:, :next_grab],
                    pad_px,
                    pad_sigma,
                )

        results = []
        for index, image in enumerate(images):
            height = image.shape[1]
            chamfer_rows = max(0, int(height * chamfer_pct / 100.0))
            blend_rows = max(2, int(height * blend_pct / 100.0))
            chamfered = cls._chamfer(image, chamfer_rows)
            canvas = torch.cat(
                (top_pads[index], chamfered, bottom_pads[index]), dim=1
            )
            canvas = cls._blend_junctions(
                canvas,
                pad_px,
                height,
                blend_rows,
                blend_sigma,
            )
            results.append(canvas.clamp_(0.0, 1.0))
        return results

    def pad_edges(
        self,
        image_1,
        pad_px,
        blend_pct,
        pad_sigma,
        blend_sigma,
        chamfer_pct,
        **kwargs,
    ):
        images = collect_image_inputs(image_1, kwargs)
        pad_px = int(pad_px)
        if pad_px < 1:
            raise ValueError("pad_px must be at least 1.")

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
            if not torch.is_floating_point(image):
                raise TypeError(f"image_{index} must use a floating-point dtype.")
            normalised.append(image)

        channel_counts = {int(image.shape[-1]) for image in normalised}
        if len(channel_counts) != 1:
            raise ValueError(
                "EdgePad inputs must use the same channel count; "
                f"got {sorted(channel_counts)}."
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
                "EdgePad batch sizes must match or be 1 for broadcasting; "
                f"got {sizes}."
            )

        expanded = [
            image.expand(batch_size, -1, -1, -1)
            if image.shape[0] == 1 and batch_size > 1
            else image
            for image in normalised
        ]
        results = self._pad_batches(
            expanded,
            pad_px,
            float(blend_pct),
            float(pad_sigma),
            float(blend_sigma),
            float(chamfer_pct),
        )

        first = normalised[0]
        empty = torch.zeros(
            (1, 1, 1, first.shape[-1]),
            device=first.device,
            dtype=first.dtype,
        )
        return tuple(
            results[index] if index < len(results) else empty
            for index in range(self.MAX_INPUTS)
        )


__all__ = ["WuddEdgePad"]
