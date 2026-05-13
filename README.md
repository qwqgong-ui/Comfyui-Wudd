# ComfyUI-Wudd

Custom nodes for [ComfyUI](https://github.com/comfyanonymous/ComfyUI), focused on practical image, text, audio/video, path, and API utility workflows.

## Installation

Clone this repository into `ComfyUI/custom_nodes/`:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/qwqgong-ui/Comfyui-Wudd.git
```

Install dependencies with the Python environment used by ComfyUI:

```bash
python -m pip install -r Comfyui-Wudd/requirements.txt
```

For the ComfyUI Windows portable build, use its embedded Python:

```powershell
C:\path\to\ComfyUI\python_embeded\python.exe -m pip install -r C:\path\to\ComfyUI\ComfyUI\custom_nodes\Comfyui-Wudd\requirements.txt
```

Restart ComfyUI after installation.

## Dependencies

`requirements.txt` explicitly lists:

- `numpy`
- `Pillow`
- `scipy`
- `av`
- `imageio-ffmpeg`

`imageio-ffmpeg` provides an internal ffmpeg executable for the video-audio replacement node. The node resolves ffmpeg automatically and does not require a path widget. If you need an offline/local override, place `ffmpeg.exe` at one of these paths inside this repository:

- `ffmpeg/bin/ffmpeg.exe`
- `ffmpeg/ffmpeg.exe`
- `bin/ffmpeg.exe`
- `ffmpeg.exe`

If none of those exist, the node falls back to `ffmpeg` on `PATH`.

## Nodes

All nodes are registered under `Wudd Nodes`.

### Wudd Multi Save

Batch save one or more `IMAGE` inputs.

- Dynamic image input ports.
- Save as PNG or Jpegli JPEG.
- Supports append and overwrite naming modes.
- Preserves ComfyUI workflow metadata in PNG output.
- Jpegli uses the bundled `jxl-x64-windows-static/bin/cjpegli.exe` on Windows and falls back to PIL JPEG if unavailable.

Inputs:

- `image_1`, dynamic extra image inputs
- `filename_prefix`
- `save_mode`: `append`, `overwrite`
- `extension`: `png`, `jpegli`
- `quality`
- `progressive`
- `enable_xyb`
- `chroma_subsampling`

### Wudd Drop Alpha

Composite transparent image areas over a generated background and return RGB `IMAGE`.

- Optional `MASK` input where ComfyUI mask value `1` means transparent.
- Background modes: checkerboard or fill color.
- Optional auto crop around non-transparent content.

Inputs:

- `image`
- optional `mask`
- `mode`: `checkerboard`, `fill_color`
- `fill_color`
- `tile_size`
- `auto_crop`
- `padding`

### Wudd Image Expand

Expand an image by whole-image blocks in one direction.

- Directions: right, down, left, up.
- Fill modes match `Wudd Drop Alpha`: checkerboard or solid color.
- Outputs expanded image, width, and height.

### Wudd Edge Pad

Create natural vertical edge padding for panorama or long-image preprocessing.

- Supports up to 16 image inputs.
- Cross-blends neighboring image edges.
- Adds controllable blur and chamfering at pad junctions.
- Returns up to 16 padded image outputs.

### Wudd Image List Importer

Load multiple images from ComfyUI `input/`.

- File mode: choose individual uploaded/input images.
- Folder mode: load images from a folder path.
- Supports up to 50 outputs.
- Folder paths may be absolute or relative to ComfyUI `input/`.

### Wudd Image Stitch

Stitch multiple images linearly.

- Directions: right, down, left, up.
- Supports up to 16 image inputs.
- Fits images to the first image's height or width depending on stitch direction.
- Optional gap between images.

### Wudd Text Splitter

Extract one line from a multiline string.

- Zero-based `index`.
- Optional `skip_empty` filtering.
- Returns empty string when out of range.

### Wudd Multi Text Splitter

Split multiline text into up to 16 string outputs.

- `count` controls how many output slots are intended for use.
- Optional `skip_empty`.
- Unused or missing lines return empty strings.

### Wudd Path Joiner

Join up to 5 path segments with `/`.

- Ignores blank segments.
- Useful for building portable path-like prompt strings or API inputs.

### Wudd Extract Audio From Video

Extract audio directly from a `VIDEO` input.

- Connect the output of ComfyUI's built-in `Load Video` node.
- No file picker or path input is required.
- Supports `audio_stream_index` for videos with multiple audio streams.
- Outputs:
  - `AUDIO`
  - `sample_rate`
  - `duration_seconds`

### Wudd Replace Video Audio

Replace a `VIDEO` input's audio track with a supplied `AUDIO` input.

- Video stream is copied with ffmpeg where possible.
- New audio is encoded as AAC.
- ffmpeg is resolved internally from `imageio-ffmpeg`, a local node copy, or system `PATH`.
- Outputs a new `VIDEO` object that can be passed to ComfyUI's built-in `Save Video`.

Inputs:

- `video`
- `audio`
- `output_format`: `mp4`, `mkv`, `mov`
- `audio_bitrate`: `128k`, `192k`, `256k`, `320k`
- `end_mode`: `shortest`, `keep_video_length`

### Wudd OpenAI GPT-5.4

Call an OpenAI-compatible API endpoint using only Python standard HTTP libraries.

- Supports Responses API and Chat Completions API modes.
- Optional image input.
- Supports custom `base_url`.
- Supports SSL verification toggle.
- Responses mode supports polling by response id.

Inputs include:

- `prompt`
- `instructions`
- `api_key`
- `base_url`
- `model`
- `api_mode`
- `reasoning_effort`
- `verbosity`
- `max_output_tokens`
- `poll_interval`
- `max_wait_seconds`
- optional `images`

Outputs:

- `text`
- `response_id`

## Notes

- PNG image saves include metadata for workflow restoration.
- Jpegli is Windows-bundled in this repository; other platforms fall back to PIL JPEG.
- Video audio replacement keeps the output video in ComfyUI's temp directory until it is consumed by downstream nodes.
- ComfyUI itself provides `torch`, `folder_paths`, and the `VIDEO` object model used by these nodes.
