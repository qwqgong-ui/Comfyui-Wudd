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

`imageio-ffmpeg` provides an internal ffmpeg executable for the video and audio-video nodes. The nodes resolve ffmpeg automatically and do not require a path widget.

If you need an offline/local override, place the Windows ffmpeg executables in this repository's `bin/` folder:

- `bin/ffmpeg.exe`
- `bin/ffprobe.exe`
- `bin/ffplay.exe`

The node uses `bin/ffmpeg.exe` only when all three files exist. The `bin/` folder is kept in Git with `.gitkeep`, while copied executables are ignored by `.gitignore` and should not be committed. If the local `bin/` set is missing or incomplete, the node falls back to `imageio-ffmpeg`, then to `ffmpeg` on `PATH`.

## Nodes

All nodes are registered under `Wudd Nodes`.

### Wudd Multi Save

Batch save one or more `IMAGE` inputs.

- Dynamic image input ports.
- Save as PNG or Jpegli JPEG.
- Supports append and overwrite naming modes.
- Preserves ComfyUI workflow metadata in PNG output.
- Jpegli uses the bundled `jxl-x64-windows-static/bin/cjpegli.exe` on Windows and falls back to PIL JPEG if unavailable.
- Saved images are backed up in `temp/image/wudd_save_cache` before copying to the final output path.

Inputs:

- `image_1`, dynamic extra image inputs
- `filename_prefix`
- `save_mode`: `append`, `overwrite`
- `extension`: `png`, `jpegli`
- `quality`
- `progressive`
- `enable_xyb`
- `chroma_subsampling`

### Wudd Save Video

Save one or more `VIDEO` inputs to the ComfyUI output directory.

- Dynamic video input ports.
- Encodes video as AV1 or H.265/HEVC through ffmpeg.
- Supports CPU encoding plus NVIDIA NVENC, Intel Quick Sync, and AMD AMF when the resolved ffmpeg build and local hardware support the selected encoder.
- Supports append and overwrite naming modes matching `Wudd Multi Save`.
- Audio can be copied, re-encoded to AAC with the source sample rate/channels, or removed.
- ffmpeg is resolved internally from a complete local `bin/` set, `imageio-ffmpeg`, or system `PATH`.

Inputs:

- `video_1`, dynamic extra video inputs
- `filename_prefix`
- `save_mode`: `append`, `overwrite`
- `codec`: `av1`, `h265`
- `encoder`: `cpu`, `nvidia`, `intel`, `amd`
- `container`: `mp4`, `mkv`
- `crf`
- `preset`: `fast`, `medium`, `slow`
- `audio_mode`: `copy`, `aac`, `none`

### Wudd Video Fast Forward

Speed up a `VIDEO` input and output a new `VIDEO`.

- `speed_multiplier` mode uses a direct playback multiplier such as `2.0` for 2x speed.
- `target_seconds` mode derives the speed from the source duration so the result lasts the requested number of seconds.
- Video is written as MP4 for downstream video nodes.
- Audio can be tempo-adjusted with the video and re-encoded as AAC, or removed.

Inputs:

- `video`
- `mode`: `speed_multiplier`, `target_seconds`
- `speed_multiplier`
- `target_seconds`
- `audio_mode`: `keep`, `none`

### Wudd Concat Videos

Concatenate `VIDEO` inputs in port order and output a new `VIDEO`.

- Dynamic video input ports.
- Concatenates as `video_1`, `video_2`, `video_3`, and so on.
- Normalizes every segment to the first video's dimensions and frame rate before concatenating.
- Uses FFV1 video and PCM float audio in MKV for lossless internal processing.
- Returns an MP4 video encoded for downstream nodes that require an MP4 container.
- `fit_to_first` keeps aspect ratio with padding; `stretch_to_first` fills the first video's size.
- Audio can be kept with PCM normalization and silence for mute clips, or removed.
- Normalized segments and MP4 outputs are backed up in `temp/video/wudd_concat_cache`.
- The output stays in ComfyUI temp storage and can be connected to `Wudd Save Video`.

Inputs:

- `video_1`, `video_2`, dynamic extra video inputs
- `resize_mode`: `fit_to_first`, `stretch_to_first`
- `audio_mode`: `keep`, `none`

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
- Output duration follows the video duration: long audio is trimmed, short audio is padded with silence.
- ffmpeg is resolved internally from a complete local `bin/` set, `imageio-ffmpeg`, or system `PATH`.
- Outputs a new `VIDEO` object that can be passed to ComfyUI's built-in `Save Video`.

Inputs:

- `video`
- `audio`
- `output_format`: `mp4`, `mkv`, `mov`
- `audio_bitrate`: `128k`, `192k`, `256k`, `320k`
- `end_mode`: `keep_video_length` (`shortest` is accepted for legacy workflows and behaves the same)

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
- AV1/H.265 video preview support depends on the browser and operating system codec support.
- Video concatenation normalizes intermediate segments as FFV1/PCM in MKV for lossless internal processing, then downstream save nodes can encode final AV1/H.265 outputs.
- Video audio replacement keeps the output video in ComfyUI's temp directory until it is consumed by downstream nodes.
- ComfyUI itself provides `torch`, `folder_paths`, and the `VIDEO` object model used by these nodes.
