# ComfyUI-Wudd-V3

Standalone V3 build of ComfyUI-Wudd. Install this folder as
`ComfyUI/custom_nodes/ComfyUI-Wudd-V3`.

The node classes use `comfy_api.latest.IO.ComfyNode` schemas and are exported
through `NODE_CLASS_MAPPINGS` for current ComfyUI compatibility. All Python
nodes are registered under `Wudd Nodes V3` or a subcategory.

## Installation

Place this folder in `ComfyUI/custom_nodes/`, install dependencies with the
same Python environment used by ComfyUI, then restart ComfyUI.

```powershell
C:\path\to\ComfyUI\python_embeded\python.exe -m pip install -r C:\path\to\ComfyUI\ComfyUI\custom_nodes\ComfyUI-Wudd-V3\requirements.txt
```

Dependencies:

- `numpy`
- `Pillow`
- `av`
- `imageio-ffmpeg`
- `playwright`

`imageio-ffmpeg` provides a fallback ffmpeg executable. `playwright` is used by
the ChatGPT browser automation node.

## Optional Local Binaries

For a local ffmpeg override, place all three platform executables in `bin/`:

- Windows: `bin/ffmpeg.exe`, `bin/ffprobe.exe`, `bin/ffplay.exe`
- Linux: `bin/ffmpeg`, `bin/ffprobe`, `bin/ffplay`

The node uses the local set only when all three are present. Otherwise it falls
back to `imageio-ffmpeg`, then `ffmpeg` on `PATH`.

Refresh local ffmpeg:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update_ffmpeg.ps1
```

```bash
bash scripts/update_ffmpeg_linux.sh
```

For Linux Jpegli support:

```bash
bash scripts/update_jpegli_linux.sh
```

On Windows, Jpegli mode uses the bundled
`bin/jxl-x64-windows-static/bin/cjpegli.exe` when available and falls back to
PIL JPEG if it cannot run.

## Help And Localization

Node descriptions and tooltips are defined in `nodes/_base.py` through
`WUDD_V3_HELP`. Chinese labels, descriptions, and tooltips are defined in
`locales/zh/nodeDefs.json`.

When changing node inputs or outputs, update both files.

## Nodes

### Wudd V3 Multi Save Image

Saves one or more `IMAGE` inputs to the ComfyUI output folder.

Inputs:

- `images`: dynamic image inputs
- `filename_prefix`
- `save_mode`: `append`, `overwrite`
- `extension`: `png`, `jpegli`
- Jpegli-only options: `quality`, `progressive`, `enable_xyb`, `chroma_subsampling`

### Wudd V3 Save Video

Saves one or more `VIDEO` inputs through ffmpeg.

Inputs:

- `videos`: dynamic video inputs
- `filename_prefix`
- `save_mode`: `append`, `overwrite`
- `codec`: `av1`, `h265`
- `encoder`: `cpu`, `nvidia`, `intel`, `amd`
- `container`: `mp4`, `mkv`
- `crf`
- `preset`: `fast`, `medium`, `slow`
- `audio_mode`: `copy`, `aac`, `none`

### Wudd V3 Fast Forward Video

Speeds up a `VIDEO` by multiplier or by target duration.

Inputs:

- `video`
- `mode`: `speed_multiplier`, `target_seconds`
- `speed_multiplier`
- `target_seconds`
- `audio_mode`: `keep`, `none`

Output:

- `video`

### Wudd V3 Concat Videos

Concatenates multiple `VIDEO` inputs in slot order.

Inputs:

- `videos`: dynamic video inputs
- `resize_mode`: `fit_to_first`, `stretch_to_first`
- `audio_mode`: `keep`, `none`

Output:

- `video`

### Wudd V3 Text Splitter

Returns one line from multiline text.

Inputs:

- `text`
- `index`
- `skip_empty`

Output:

- `text`

### Wudd V3 Multi Text Splitter

Splits multiline text into up to 16 string outputs.

Inputs:

- `text`
- `count`
- `skip_empty`

Outputs:

- `line_0` through `line_15`

### Wudd V3 Prompt List From Text

Parses text into a prompt list.

Inputs:

- `text`
- `skip_empty`
- `strip_numbering`

Outputs:

- `prompts`
- `count`

### Wudd V3 Save Text

Writes `STRING` text to UTF-8 under ComfyUI `output`, `input`, or `temp`.

Inputs:

- `text`
- `root_dir`: `output`, `input`, `temp`
- `file`
- `append`: `overwrite`, `append`, `new_only`
- `insert`

Output:

- `path`

### Wudd V3 Drop Alpha

Composites transparent image areas over checkerboard or solid fill.

Inputs:

- `image`
- `mode`: `checkerboard`, `fill_color`
- `tile_size`
- `fill_color`
- `auto_crop`
- `padding`
- optional `mask`

Output:

- `image`

### Wudd V3 Image Expand

Expands an image by whole-image blocks in one direction.

Inputs:

- `image`
- `direction`: `right`, `down`, `left`, `up`
- `count`
- `mode`: `checkerboard`, `fill_color`
- `tile_size`
- `fill_color`

Outputs:

- `image`
- `width`
- `height`

### Wudd V3 Edge Pad

Adds vertical edge padding and blends neighboring image edges.

Inputs:

- `images`: dynamic image inputs
- `pad_px`
- `blend_pct`
- `pad_sigma`
- `blend_sigma`
- `chamfer_pct`

Outputs:

- `image_1` through `image_16`

### Wudd V3 Image List Importer

Imports images from ComfyUI input files or from a folder.

Inputs:

- `mode`: `files`, `folder`
- `image_count`
- file mode: `image_1` through `image_50`
- folder mode: `folder_path`

Outputs:

- `image_1` through `image_50`

### Wudd V3 Image Stitch

Stitches multiple images linearly.

Inputs:

- `images`: dynamic image inputs
- `direction`: `right`, `down`, `left`, `up`
- `gap`

Output:

- `image`

### Wudd V3 Path Joiner

Joins up to five path segments with `/`.

Inputs:

- `count`
- `segment_1` through `segment_5`

Output:

- `path`

### Wudd V3 Extract Audio From Video

Extracts audio from a `VIDEO` input.

Inputs:

- `video`
- `audio_stream_index`

Outputs:

- `audio`
- `sample_rate`
- `duration_seconds`

### Wudd V3 Replace Video Audio

Replaces a `VIDEO` input's audio track with an `AUDIO` input.

Inputs:

- `video`
- `audio`
- `output_format`: `mp4`, `mkv`, `mov`
- `audio_bitrate`: `128k`, `192k`, `256k`, `320k`
- `end_mode`: `keep_video_length`, `shortest`

Output:

- `video`

### Wudd V3 OpenRouter Text Nodes

Text nodes call OpenRouter-compatible GPT, Claude, or Gemini models.

Nodes:

- `WuddV3OpenRouterGPTText`
- `WuddV3OpenRouterClaudeText`
- `WuddV3OpenRouterGeminiText`

Common inputs:

- `prompt`
- `api_key`
- `model`
- `max_tokens`
- reasoning controls where supported
- runtime controls: `base_url`, `timeout_seconds`, `verify_ssl`
- optional `system_prompt`
- optional `extra_body_json`

GPT and Gemini text nodes also support optional dynamic reference `images`.

Outputs:

- `text`
- `reasoning`
- `response_id`

### Wudd V3 OpenRouter Image Nodes

Image nodes call OpenRouter-compatible GPT or Gemini image models.

Nodes:

- `WuddV3OpenRouterGPTImage`
- `WuddV3OpenRouterGeminiImage`

Common inputs:

- `prompt`
- `api_key`
- `model`
- `response_modalities`
- `aspect_ratio`
- `image_size`
- `max_tokens`
- `seed`
- runtime controls: `base_url`, `timeout_seconds`, `verify_ssl`
- optional `system_prompt`
- optional `extra_body_json`
- optional dynamic reference `images`

Outputs:

- `image`
- `text`
- `response_id`

### Wudd V3 Group Switch

Controls ComfyUI canvas groups from one node.

Inputs:

- `enabled`
- `group_name`: blank for all groups, exact group title, or `self`/`current`/`auto`
- `off_mode`: `mute`, `bypass`

Outputs:

- `enabled`
- `group_name`

### Wudd V3 ChatGPT Browser

Submits a prompt and optional images to `chatgpt.com` through a local Chrome or
Edge browser, then returns the latest assistant text and response images.

Inputs:

- `prompt`
- `connection_mode`: `connect_or_launch_edge`, `connect_or_launch_chrome`, `connect_cdp`, `launch_chrome`, `launch_edge`
- `cdp_url`
- `wait_timeout_seconds`
- `stable_seconds`
- `upload_wait_seconds`
- `new_chat`
- `submit_action`: `press_enter`, `click_send_button`
- `keep_browser_open`
- `background_browser`
- `parallel_pages`
- `run_id`
- optional dynamic `images`
- `browser_executable`
- `close_page_after_run`
- `image_error_retries`

Outputs:

- `text`
- `conversation_url`
- `images`
- `image_count`

To connect to an already-running browser:

```powershell
msedge.exe --remote-debugging-port=9222 --user-data-dir="$env:USERPROFILE\.wudd-chatgpt-browser"
```

Then set `connection_mode` to `connect_cdp`.

### Wudd V3 Wireless Input / Output

Frontend-only virtual LiteGraph nodes for hiding long links while preserving the
execution graph connection.

Nodes:

- `WuddV3WirelessInput`
- `WuddV3WirelessOutput`

Channels are matched by `namespace + channel name`. Use the right-click menu to
add channels, create a matching output, or refresh output channels from inputs.

## Validation

Run the functional check with ComfyUI's Python:

```powershell
C:\Users\V\Documents\ComfyUI\python_embeded\python.exe scripts\functional_check_nodes.py
```

The check skips live OpenRouter calls. The ChatGPT browser case reports
`ENV_FAIL` unless a browser CDP endpoint is already available at
`http://127.0.0.1:9222`.
