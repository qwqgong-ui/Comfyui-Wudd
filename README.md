Markdown
# ComfyUI-Wudd

A powerful and robust custom node for [ComfyUI](https://github.com/comfyanonymous/ComfyUI) that provides advanced multi-image saving capabilities, featuring state-of-the-art **Jpegli** compression.

## ✨ Features

* **Dynamic Input Ports**: No need for multiple save nodes or complicated batching. The "Wudd Multi Save" node automatically generates a new input port every time you connect an image, allowing you to save as many images as you want simultaneously. Safe for node duplication (Ctrl+C/V) and highly stable!
* **Advanced Jpegli Support**: Integrates Google's highly efficient `cjpegli` encoder, offering superior JPEG image quality at smaller file sizes compared to standard encoders.
* **Fine-Grained Compression Control**: When saving as `jpegli`, you have full control over:
    * Quality (1-100)
    * Progressive Encoding
    * XYB Color Space toggling
    * Chroma Subsampling (444, 440, 422, 420)
* **Smart & Clean UI**: The node features a dynamic interface. Advanced Jpegli settings will automatically hide when you select the standard `png` format, keeping your workspace clean and clutter-free.

## 🚀 Installation

1. Navigate to your ComfyUI `custom_nodes` directory:
   ```bash
   cd ComfyUI/custom_nodes/
Clone this repository:

Bash
git clone [https://github.com/qwqgong-ui/Comfyui-Wudd.git](https://github.com/qwqgong-ui/Comfyui-Wudd.git)
Restart ComfyUI.

(Note: Ensure the folder is named exactly Comfyui-Wudd or ComfyUI-Wudd directly inside custom_nodes without extra nested folders.)

⚙️ Parameters
image_1, image_2, ...: Connect the images you want to save here. Ports will spawn dynamically.

filename_prefix: The prefix for your saved files (default: Wudd_Img).

extension: Choose the output format. Options are png or jpegli.

Jpegli Exclusive Settings (Visible only when extension is set to jpegli):

quality: Sets the image quality from 1 to 100 (default: 90).

progressive: Enables progressive JPEG rendering for smoother web loading.

enable_xyb: Enables the XYB color space for perceptual quality improvements.

chroma_subsampling: Adjusts color data compression. Options include 444 (highest quality/no subsampling), 440, 422, and 420 (highest compression).

⚠️ Notes
OS Compatibility: The current Jpegli compression relies on a bundled pre-compiled 64-bit Windows executable (jxl-x64-windows-static/bin/cjpegli.exe). Jpegli encoding will seamlessly fallback to standard PIL JPEG saving if the executable fails to run on non-Windows environments. PNG saving works univers