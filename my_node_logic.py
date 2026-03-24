# my_node_logic.py
import os
import subprocess
import numpy as np
from PIL import Image
import folder_paths
import uuid

class WuddMultiSaveImage:
    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        # 指向官方静态包 cjpegli.exe 的路径
        self.cjpegli_exe = os.path.join(os.path.dirname(__file__), "jxl-x64-windows-static", "bin", "cjpegli.exe")

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image_1": ("IMAGE", ),
                "filename_prefix": ("STRING", {"default": "Wudd_Img"}),
                "extension": (["png", "jpegli"],),
                "quality": ("INT", {"default": 90, "min": 1, "max": 100}),
                "progressive": ("BOOLEAN", {"default": True}),
                "enable_xyb": ("BOOLEAN", {"default": False}),
                "chroma_subsampling": (["444", "420"], {"default": "444"}), # 新增: 色度子采样
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True  
    CATEGORY = "Wudd Nodes"

    def save_images(self, filename_prefix="Wudd_Img", extension="png", quality=90, progressive=True, enable_xyb=False, chroma_subsampling="444", **kwargs):
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(filename_prefix, self.output_dir, 100, 100)
        results = list()
        
        # 将明确的 image_1 放入字典，并合并动态传入的 kwargs (image_2, image_3...)
        all_images = {"image_1": kwargs.pop("image_1", None), **kwargs}
        
        for key, images in all_images.items():
            if not key.startswith("image_") or images is None: 
                continue
            
            # 解析序列号，例如 "image_2" -> "2"
            parts = key.split("_")
            seq_num = parts[1] if len(parts) > 1 else "1"
            
            for batch_num, image in enumerate(images):
                i_data = (255. * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
                img_pil = Image.fromarray(i_data)
                
                ext = "jpg" if extension == "jpegli" else "png"
                file_name = f"{filename}_{counter:05}_seq{seq_num}_b{batch_num}.{ext}"
                file_path = os.path.join(full_output_folder, file_name)

                if extension == "png":
                    img_pil.save(file_path, compress_level=4)
                else:
                    # JPEGli 编码逻辑
                    temp_png = os.path.join(full_output_folder, f".tmp_{uuid.uuid4()}.png")
                    img_pil.save(temp_png)
                    
                    cmd = [self.cjpegli_exe, temp_png, file_path, "-q", str(quality)]
                    if progressive: cmd.append("-p")
                    if enable_xyb: cmd.append("--xyb")
                    
                    # 添加色度子采样参数
                    cmd.append(f"--chroma_subsampling={chroma_subsampling}")

                    try:
                        subprocess.run(cmd, check=True, capture_output=True, shell=False)
                    except Exception as e:
                        print(f"[WuddMultiSave] cjpegli 压缩失败，回退至原生 PIL 保存。错误信息: {e}")
                        img_pil.save(file_path, quality=quality)
                    finally:
                        if os.path.exists(temp_png): 
                            os.remove(temp_png)

                results.append({"filename": file_name, "subfolder": subfolder, "type": self.type})
                counter += 1
                
        return { "ui": { "images": results } }