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
                # 新增色度采样选项
                "chroma_subsampling": (["444", "440", "422", "420"],),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True  
    CATEGORY = "Wudd Nodes"

    def save_images(self, image_1, filename_prefix="Wudd_Img", extension="png", quality=90, progressive=True, enable_xyb=False, chroma_subsampling="444", **kwargs):
        full_output_folder, filename, counter, subfolder, filename_prefix = folder_paths.get_save_image_path(filename_prefix, self.output_dir, 100, 100)
        results = list()
        all_images = {"image_1": image_1, **kwargs}
        
        for key, images in all_images.items():
            if not key.startswith("image_") or images is None: continue
            seq_num = key.split("_")[1]
            for batch_num, image in enumerate(images):
                i_data = (255. * image.cpu().numpy()).clip(0, 255).astype(np.uint8)
                img_pil = Image.fromarray(i_data)
                
                ext = "jpg" if extension == "jpegli" else "png"
                file_name = f"{filename}_{counter:05}_seq{seq_num}_b{batch_num}.{ext}"
                file_path = os.path.join(full_output_folder, file_name)

                if extension == "png":
                    img_pil.save(file_path, compress_level=4)
                else:
                    temp_png = os.path.join(full_output_folder, f".tmp_{uuid.uuid4()}.png")
                    img_pil.save(temp_png)
                    
                    cmd = [self.cjpegli_exe, temp_png, file_path, "--quality", str(quality)]
                    
                    # 修复 1：正确的渐进式参数
                    if progressive:
                        cmd.extend(["-p", "2"])
                    else:
                        cmd.extend(["-p", "0"])
                        
                    # 修复 2：只有 --xyb，不要传 --no-xyb
                    if enable_xyb: 
                        cmd.append("--xyb")
                        
                    # 修复 3：正确传入色度采样
                    cmd.append(f"--chroma_subsampling={chroma_subsampling}")

                    try:
                        # 增加 capture_output=True 和 text=True 方便获取真实的报错信息
                        subprocess.run(cmd, check=True, capture_output=True, text=True, shell=False)
                    except subprocess.CalledProcessError as e:
                        # 把 cjpegli 的真实报错打在终端，不再悄悄失败！
                        print(f"[Wudd Node Error] cjpegli fail: {e.stderr}")
                        img_pil.save(file_path, quality=quality)
                    finally:
                        if os.path.exists(temp_png): os.remove(temp_png)

                results.append({"filename": file_name, "subfolder": subfolder, "type": self.type})
                counter += 1
        return { "ui": { "images": results } }