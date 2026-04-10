# ComfyUI-Wudd

A powerful and robust custom node suite for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) featuring advanced image saving and utility nodes.

## ✨ Features

### 🖼️ Wudd Multi Save
* **Dynamic Input Ports**: No need for multiple save nodes or complicated batching. The node automatically generates a new input port every time you connect an image.
* **Advanced Jpegli Support**: Integrates Google's highly efficient `cjpegli` encoder for superior JPEG quality at smaller file sizes.
* **Fine-Grained Compression Control**: Full control over quality, progressive encoding, XYB color space, and chroma subsampling.
* **Smart & Clean UI**: Advanced settings dynamically hide when saving as standard PNG.

### 📝 Wudd Text Splitter
* **Line-based Splitting**: Easily manage multi-line text blocks.
* **Index Selection**: Extract specific lines by their index (0-based).
* **Robust & Safe**: Returns an empty string instead of an error if the index is out of bounds.

## 🚀 Installation

1. Navigate to your ComfyUI `custom_nodes` directory:
   ```bash
   cd ComfyUI/custom_nodes/
   ```
2. Clone this repository:
   ```bash
   git clone https://github.com/qwqgong-ui/Comfyui-Wudd.git
   ```
3. Restart ComfyUI.

## ⚙️ Parameters

### Wudd Multi Save
- **image_1, image_2, ...**: Connect images here. Ports spawn dynamically.
- **filename_prefix**: Prefix for saved files (default: `Wudd_Img`).
- **extension**: Output format (`png` or `jpegli`).
- **Jpegli Settings** (Visible when `jpegli` is selected):
    - `quality`: 1-100.
    - `progressive`: Toggle progressive JPEG.
    - `enable_xyb`: Toggle XYB color space.
    - `chroma_subsampling`: `444`, `440`, `422`, `420`.

### Wudd Text Splitter
- **text**: Multi-line string input.
- **index**: The line number to extract (starts at 0).

## ⚠️ Notes
**OS Compatibility**: Jpegli compression relies on a bundled pre-compiled 64-bit Windows executable (`cjpegli.exe`). It will seamlessly fallback to standard PIL JPEG saving on non-Windows environments. PNG saving works universally.
