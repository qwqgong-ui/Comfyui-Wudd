# ComfyUI-Wudd 节点逻辑手册

> 本文档清晰记录 ComfyUI-Wudd 套件中每个自定义节点的内部逻辑，便于后续维护、代码审阅与 AI 协作。
> 代码按功能域拆分到 `nodes_image.py` / `nodes_text.py` / `nodes_api.py` 三个文件，共享工具在 `nodes_common.py`，由 `__init__.py` 汇总注册。

---

## 节点总览

| # | 类名 | 显示名 | 类别 | 动态端口 |
|---|------|--------|------|----------|
| 1 | `WuddMultiSaveImage`     | Wudd Multi Save          | Wudd Nodes | ✅ 输入自增 |
| 2 | `WuddDropAlpha`          | Wudd Drop Alpha          | Wudd Nodes | — |
| 3 | `WuddEdgePad`            | Wudd Edge Pad            | Wudd Nodes | — |
| 4 | `WuddPathJoiner`         | Wudd Path Joiner         | Wudd Nodes | — |
| 5 | `WuddTextSplitter`       | Wudd Text Splitter       | Wudd Nodes | — |
| 6 | `WuddMultiTextSplitter`  | Wudd Multi Text Splitter | Wudd Nodes | ✅ 输出按 count |
| 7 | `WuddImageListImporter`  | Wudd Image List Importer | Wudd Nodes | ✅ 输入/输出按 image_count |
| 8 | `WuddImageStitch`        | Wudd Image Stitch        | Wudd Nodes | ✅ 输入按 input_count |
| 9 | `WuddOpenAIGPT54`        | Wudd OpenAI GPT-5.4      | Wudd Nodes | — |

动态端口逻辑统一由 `web/dynamic_ports.js` 前端扩展驱动，ComfyUI 启动时通过 `WEB_DIRECTORY = "./web"` 自动加载。

---

## 文件布局

节点代码按功能域拆到四个 Python 文件，由 `__init__.py` 汇总成 `NODE_CLASS_MAPPINGS`：

| 文件 | 职责 | 包含节点 |
|------|------|----------|
| `nodes_common.py` | 共享常量与工具 | —（无节点） |
| `nodes_image.py`  | 图像类节点     | `WuddMultiSaveImage` / `WuddDropAlpha` / `WuddEdgePad` / `WuddImageListImporter` / `WuddImageStitch` |
| `nodes_text.py`   | 文本类节点     | `WuddTextSplitter` / `WuddMultiTextSplitter` / `WuddPathJoiner` |
| `nodes_api.py`    | 外部 API 节点  | `WuddOpenAIGPT54` |
| `__init__.py`     | 节点注册入口   | —（只做 import + mapping + WEB_DIRECTORY） |
| `web/dynamic_ports.js` | 前端动态端口逻辑 | 4 个节点挂钩（见下文） |

图像、文本、API 三个文件之间互不依赖，仅都 `from .nodes_common import …`。

---

## 0. 模块级规范层（`nodes_common.py`）

所有节点共用一层"规范层"集中声明于文件顶部，保证一致性、可维护性与性能：

| 符号 | 类型 | 作用 |
|------|------|------|
| `WUDD_CATEGORY` | 常量 | `"Wudd Nodes"`。9 个类 `CATEGORY` 均引用此常量，重命名只改一处。 |
| `CREATE_NO_WINDOW` | 常量 | Windows 下为 `0x08000000`，其他平台为 `0`；用于抑制 `cjpegli.exe` 黑框。 |
| `_IMAGE_INDEX_SENTINEL` | 常量 | `10**9`。`image_N` 解析失败时的"排到最后"哨兵。 |
| `_image_index(name)` | 函数 | 从 `image_N` 键取整型索引；非法/缺失时返回哨兵。 |
| `collect_image_inputs(primary, extras, max_n=None)` | 函数 | 合并 `image_1` 与 `kwargs`，按数字索引排序，过滤 `None`，可选用 `max_n` 截断；返回 tensor 列表。`MultiSave / EdgePad / Stitch` 三处复用。 |
| `tensor_to_pil(image_tensor)` | 函数 | 接受 `[H,W,C]` 或 `[1,H,W,C]`；C=3→RGB，C=4→RGBA。`MultiSave / Stitch / OpenAIGPT54` 复用。 |
| `pil_to_tensor(pil_img)` | 函数 | PIL → `[1,H,W,C]` float32 ∈ `[0,1]`；`Stitch / ImageListImporter` 复用。 |
| `tensor_to_base64_png(image_tensor)` | 函数 | 单帧 → base64 PNG 字符串；`OpenAIGPT54` 的 data URL 编码专用。 |

**设计原则**：
- "规范层"只做跨节点共享的纯函数 / 常量；节点私有的数值算法（`_chamfer / _cross_blend_pad / _blend_junctions`）仍保留在各自类里，避免变成全局杂物桶。
- 对外可导出的 helpers 不带下划线前缀（`tensor_to_pil` 等），带下划线的是本模块内部使用（`_image_index`）。
- 懒加载 import（`scipy / torch`）仍在函数体内，不改为模块级，避免依赖缺失导致节点注册失败。

---

## 1. WuddMultiSaveImage

**源文件**：`nodes_image.py` · `FUNCTION = "save_images"` · `OUTPUT_NODE = True`
**作用**：把任意多张图批量落盘为 PNG 或 Jpegli（JPEG XL 团队的高质量 JPEG 编码器），并支持"追加 / 覆盖"两种命名策略。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_1` (required) | IMAGE | — | 第一张图；后续 `image_2…N` 由前端动态追加 |
| `save_mode` | combo | `append` | `append`=每次追加新批次；`overwrite`=固定文件名 |
| `extension` | combo | `png`   | `png` 或 `jpegli` |
| `quality` | INT 1–100 | `90` | Jpegli 专用 |
| `progressive` | BOOL | `True` | Jpegli 渐进模式（`-p 2`） |
| `enable_xyb` | BOOL | `False` | Jpegli `--xyb` 色彩空间 |
| `chroma_subsampling` | combo | `444` | `444 / 440 / 422 / 420` |
| `filename_prefix` (optional) | STRING | `Wudd_Img` | 置于 optional 使其既能做 widget 也能接 STRING 节点 |
| `prompt` / `extra_pnginfo` (hidden) | — | — | PNG 元数据，保证拖回 PNG 还原工作流 |

### 输出
`RETURN_TYPES = ()`；作为 OUTPUT_NODE 通过 `{"ui": {"images": [...]}}` 把结果列表回传前端供预览。

### 核心算法
1. **聚合输入**：调用模块级 `collect_image_inputs(image_1, kwargs)`，按 `image_N` 的数字索引排序并过滤 `None`，保证 `image_10` 排在 `image_2` 之后。
2. **解析输出路径**：调用 `folder_paths.get_save_image_path` 解析 `%width%`、`%year%` 等占位符和子目录。
3. **决定文件名策略**：
   - `overwrite`：单图 `{prefix}.{ext}`；多图 `{prefix}.{序号:02}.{ext}`。
   - `append`：扫描目录内已有 `{prefix}.NNNNN.NN.{ext}` 取最大批次号 +1。写入时若文件已存在（边缘竞态）则批次号再 +1 兜底。
4. **编码写盘**：
   - 每帧经模块级 `tensor_to_pil(image)` 转 PIL。
   - PNG：`Image.save(pnginfo=…, compress_level=4)`，把 workflow 嵌入元数据。
   - Jpegli：先保存临时 PNG → 调用内置 `cjpegli.exe`（Windows 下 `CREATE_NO_WINDOW` 隐藏黑框）→ 成功后删临时 PNG。
5. **降级兜底**：`cjpegli` 不可用 / 执行失败 / OSError → 自动回退到 PIL 的 JPEG（映射 subsampling 到 PIL 的 0/1/2）。

### 边界情况
- 非 Windows 平台未随仓库提供 `cjpegli`，直接走 PIL 回退，节点仍然可用。
- `kwargs` 中值为 `None` 的动态端口会被跳过。
- PNG 元数据仅在 `extension == "png"` 时构建，避免白写。

### 前端动态行为（`dynamic_ports.js`）
- **输入端口自增**：`onConnectionsChange` 时，只要末端口已连上就再添加一个新的 `image_N`；若末端与次末端均未连，则回收多余空端口，保持始终有且仅有 1 个空端口。
- **旧工作流兼容**：`onConfigure` 时校验 `save_mode / extension / chroma_subsampling` 的旧值是否属于合法枚举，不合法则重置为默认并打印 warning。
- **Jpegli 专用 widget 显隐**：`extension` 切换至非 jpegli 时，把 `quality / progressive / enable_xyb / chroma_subsampling` 的 `type` 改为 `hidden` 并令 `computeSize` 返回 `[0, -4]`，实现无痕隐藏；切回 jpegli 时恢复原始 `type / computeSize`。

---

## 2. WuddDropAlpha

**源文件**：`nodes_image.py` · `FUNCTION = "drop_alpha"`
**作用**：用背景（棋盘格或纯色）填充 mask 指示的透明区域，输出无 alpha 的 RGB 图；可选按内容自动裁剪。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image` | IMAGE | — | `[B, H, W, C]` |
| `mode` | combo | `checkerboard` | `checkerboard` / `fill_color` |
| `fill_color` | STRING | `#808080` | `#RRGGBB` / `#RGB` 皆可 |
| `tile_size` | INT 4–128 step 4 | `16` | 棋盘格尺寸 |
| `auto_crop` | BOOL | `False` | 是否按内容裁剪 |
| `padding` | INT 0–2048 | `0` | 裁剪外扩像素 |
| `mask` (optional) | MASK | — | `[B, H, W]`，约定 **1 = 透明，0 = 不透明** |

### 输出
`(IMAGE,)` —— 形状 `[B, H', W', C]`（auto_crop 开启时 H'/W' 可能缩小）。

### 核心算法
1. **直通条件**：`mask` 未连接 **或** `mask.max() ≤ 1e-5`（全不透明）直接返回原图。
2. **构造背景**：
   - `checkerboard`：按 `tile_size` 分块的浅/深灰 `np.where`，转为 `[B,H,W,3]` torch tensor。
   - `fill_color`：`_parse_hex_color` 解析 hex（`#RGB` 自动补 `#RRGGBB`；解析失败回退中灰）。
3. **合成**：`result = image * (1 - mask) + bg * mask`，再 `clamp(0,1)`。
4. **可选裁剪** (`auto_crop`)：
   - `_crop_bounds` 对 batch 维取内容并集 → 找到 `row_any / col_any` 的首尾位置 → 外扩 `padding` 像素。
   - 全透明情形返回整张尺寸，避免 `argmax` 退化为 0。

### 边界情况
- `mask.max()` 阈值用 `1e-5` 而非 `0`，兼容浮点噪声。
- hex 颜色 3/6 位都支持；解析失败不报错。

---

## 3. WuddEdgePad

**源文件**：`nodes_image.py` · `FUNCTION = "pad_edges"` · `MAX_INPUTS = 16`
**作用**：为竖向全景拼图做"顶 / 底扩充 pad"预处理，让相邻图的色带自然融合，彻底消除硬色带。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_1` (required) | IMAGE | — | 第 1 张（至少一张必须） |
| `pad_px` | INT 10–500 | `100` | 每张图扩充 pad 的高度（像素） |
| `blend_pct` | FLOAT 0.5–20 | `3.0` | pad/图衔接带占图高百分比 |
| `pad_sigma` | FLOAT 1–200 | `30.0` | 跨图混合高斯模糊强度 |
| `blend_sigma` | FLOAT 1–80 | `12.0` | 衔接带额外模糊强度 |
| `chamfer_pct` | FLOAT 0–80 | `20.0` | 原图上下倒角深度百分比 (0=关) |
| `image_2…image_16` (optional) | IMAGE | — | 顺序相邻图 |

### 输出
固定 `(IMAGE,) * 16`，名为 `image_1…image_16`；未使用的槽位输出 1×1×1×3 黑色占位，前端不连接即可。

### 核心算法
1. **收集并按编号排序**所有 `image_N`：调用模块级 `collect_image_inputs(image_1, kwargs)` 返回 tensor 列表，再逐个 `.cpu().numpy().copy().astype(np.float32)`。
2. **计算每张图的 top_pad / bot_pad**（`pad_px × W × C`）：
   - 首图的 top：`_edge_pad` 自身顶部的镜像 + 高斯（向外延伸）。
   - 末图的 bot：同理。
   - 中间的 i↔i+1 跨图衔接：`_cross_blend_pad` 把 a 的底部 `pad_px` 行与 b 的顶部 `pad_px` 行 concat → 整体高斯（**水平方向 σ×0.3**）→ 上半分给 a 的 bot、下半分给 b 的 top。由于两块来自同一张模糊图，边界无跳变。
3. **倒角** (`_chamfer`)：顶/底各 `H*chamfer_pct%` 行与该侧平均色按 smoothstep `t²(3-2t)` 渐变混合；`ch=0` 时只取平均色不修改像素。
4. **拼接 + 衔接模糊**：把 `top_pad + arr + bot_pad` 沿 H 方向 concat，然后在 `pad_px` 和 `pad_px+H` 这两个交界处用**余弦钟形权重**对原图与高斯模糊图做加权混合，宽度 `br = H*blend_pct%`（最小 2 像素）。
5. **clamp 到 [0,1]**，补齐 16 路输出。

### 边界情况
- `arrs[i].shape[0] < pad_px` 时 `grab = min(pad_px, H)`，不会索引越界。
- 只有 1 张图时无跨图 pad，仅首图/末图各走 `_edge_pad` 镜像模糊。
- 输出槽固定 16 个，未用输出为 `np.zeros((1,1,3))`，前端不连则不生效。

### 依赖
`scipy.ndimage.gaussian_filter` —— 运行时局部导入，避免无 scipy 的环境启动失败（只有真正执行 Edge Pad 才会导入）。

---

## 4. WuddPathJoiner

**源文件**：`nodes_text.py` · `FUNCTION = "join_path"`
**作用**：用 `/` 串联最多 5 段路径片段，跳过空段。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `count` | INT 1–5 | `2` | 参与拼接的段数 |
| `segment_1…segment_5` | STRING | `""` | 超过 `count` 的段被忽略 |

### 输出
`(STRING,)` 名为 `path`。

### 核心算法
1. 取前 `count` 个 `segment_*`；
2. 过滤 `.strip() == ""` 的空段；
3. `"/".join(parts)` 返回。

### 边界情况
- 所有段为空 → 返回空字符串。
- 段里若含 `/`（如 `foo/bar`）不做转义，按原样拼接。

---

## 5. WuddTextSplitter

**源文件**：`nodes_text.py` · `FUNCTION = "split_text"`
**作用**：按行切分多行文本，取第 `index` 行。

### 输入
| 字段 | 类型 | 默认 |
|------|------|------|
| `text` | STRING multiline | `""` |
| `index` | INT 0–99999 | `0` |
| `skip_empty` | BOOL | `False` |

### 输出
`(STRING,)` —— 第 `index` 行；越界时安全返回 `""`。

### 核心算法
1. `text.splitlines()` → 行数组；
2. `skip_empty=True` 先过滤掉 `line.strip() == ""` 的空行；
3. 若 `0 ≤ index < len(lines)` 返回该行，否则 `""`。

### 边界情况
- 超界不抛异常，返回空串（方便下游节点容错）。

---

## 6. WuddMultiTextSplitter

**源文件**：`nodes_text.py` · `FUNCTION = "split_text"` · `MAX_OUTPUTS = 16`
**作用**：把多行文本一次分出最多 16 个输出端口，每端口一行。

### 输入
| 字段 | 类型 | 默认 |
|------|------|------|
| `text` | STRING multiline | `""` |
| `count` | INT 1–16 | `2` |
| `skip_empty` | BOOL | `False` |

### 输出
`RETURN_TYPES = ("STRING",)*16`，名 `line_0 … line_15`；超出 `count` 的槽 Python 端仍会返回空串（具体是否显示由前端控制）。

### 核心算法
1. `text.splitlines()`；
2. `skip_empty` 过滤空行；
3. 生成长度恰好 16 的元组：`lines[i]` 存在则填充，否则空串。

### 前端动态行为（`dynamic_ports.js`）
- `onNodeCreated`：找到 `count` widget，hook 其 `callback` → 每次变化调 `applyOutputCount(node, count)`（删除尾端多余输出 / 补齐缺少的输出）。初始化用 `setTimeout(…, 50)` 等待 ComfyUI 默认输出槽注册完成。
- `onConfigure`：加载旧工作流时，在 widget 值已恢复的时机同步再对齐一次输出槽数量，消除 setTimeout 与配置恢复之间的竞态。

---

## 7. WuddImageListImporter

**源文件**：`nodes_image.py` · `FUNCTION = "import_images"` · `MAX_IMAGES = 50`
**作用**：作为"图像列表源"节点，一次从 `input/` 目录选择多张图分别输出。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_count` | INT 1–50 | `1` | 实际启用的图数 |
| `image_1 … image_50` | combo(files) | — | 每项都是 `files` 下拉 + 上传按钮（`image_upload: True`） |

> `files` 由 `os.listdir(input_dir)` 运行时枚举；空目录降级为 `["none"]` 避免 combo 无选项。

### 输出
`RETURN_TYPES = ("IMAGE",)*50`，名 `image_1 … image_50`。

### 核心算法
1. **列文件**（`INPUT_TYPES` 内）：`_list_input_files` 封装 `os.listdir`，`OSError` / 空目录都回退到 `["none"]`，保证节点注册永不失败。
2. **缓存键**：`IS_CHANGED(image_count, **kwargs)` 用"文件名 + mtime"拼出字符串作为缓存键，磁盘文件更新时下游会被正确失效。
3. **运行时导入** (`import_images`)：遍历 `i ∈ [1, 50]`：
   - `i > image_count`：`images.append(None)`，对应输出槽被前端隐藏。
   - 否则根据 `kwargs["image_i"]`：
     - `"none"` 或缺省 → 填 `torch.zeros((1,64,64,3))` 黑图。
     - 其他 → `folder_paths.get_annotated_filepath` → `Image.open → ImageOps.exif_transpose → convert("RGB")` → `pil_to_tensor(...)`（模块级统一归一化路径）。
     - 异常时打印日志并回退到 64×64 黑图，避免整条工作流崩溃。
4. 返回元组。

### 前端动态行为（`dynamic_ports.js`）
- `applyImageCount(node, count)`：
  1. 隐藏 `image_{idx > count}` 的 combo widget：保存 `origType / origComputeSize` 再切 `type="hidden"` / `computeSize=()=>[0,-4]`；显示时复原。
  2. ComfyUI 会在 combo 之后紧跟注入 upload 按钮（`type === "button"`），所以顺带把 `widgets[i+1]` 同步隐藏/显示。
  3. 删/补输出槽到正好 `count` 个。
- `onNodeCreated` + `onConfigure` 两处都调用，覆盖新建与加载旧工作流两种时机。

### 边界情况
- 若 `input/` 目录为空，combo 列表是 `["none"]`，节点仍可创建，选项固定为 `none`（即黑图）。
- EXIF 方向自动校正（`exif_transpose`），避免竖拍图横着输入。

---

## 8. WuddImageStitch

**源文件**：`nodes_image.py` · `FUNCTION = "stitch"` · `MAX_INPUTS = 16`
**作用**：线性拼接多张图，`image_1` 为基准；支持四方向与间距 gap，其余图按基准轴尺寸等比缩放。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `image_1` (required) | IMAGE | — | 基准图 |
| `direction` | combo | `right` | `right / down / left / up` |
| `gap` | INT 0–256 | `0` | 图间填充像素（黑） |
| `input_count` | INT 1–16 | `2` | 实际启用输入数 |
| `image_2 … image_16` (optional) | IMAGE | — | 后续图 |

### 输出
`(IMAGE,)` 名 `image`。

### 核心算法
1. **收集图**：`max_inputs = clamp(input_count, 1, MAX_INPUTS)`；调用模块级 `collect_image_inputs(image_1, kwargs, max_n=max_inputs)` 直接拿到按编号排序、过滤 `None`、受 `max_inputs` 上界约束的 tensor 列表。
2. **单图直通**：只有 `image_1` 时原样返回。
3. **尺寸对齐**：
   - `direction ∈ {right, left}` → 水平拼接 → 全部图 `_fit_height(img, ref_h)`（`ref_h` 来自 `image_1`）。
   - `direction ∈ {down, up}` → 垂直拼接 → 全部图 `_fit_width(img, ref_w)`。
   - `_fit_height / _fit_width` 内部使用模块级 `tensor_to_pil / pil_to_tensor`，缩放走 PIL `LANCZOS`，宽/高按比例推导并 `max(1, …)` 防止 0 维。
4. **顺序调整**：`left / up` 时把 `scaled[1:]` 逆序后再拼到 `scaled[0]` 前，形成"从后往前排到基准左/上"的效果。
5. **逐步 concat**：
   - 水平：`torch.cat([result, bar, nxt], dim=2)`，`bar` 是 `[1, h_now, gap, C]` 黑条；`gap=0` 时省略 bar。
   - 垂直：沿 `dim=1` 同理。

### 前端动态行为（`dynamic_ports.js`）
- `applyStitchInputCount`：
  1. `maxInputs = clamp(input_count, 1, 16)`；
  2. 按 `desiredNames = {image_1 … image_maxInputs}` 倒序删除多余 `image_*` 输入（倒序避免索引漂移）；
  3. 补齐缺失的 `image_i`（`addInput(name, "IMAGE")`）；
  4. 按编号重排，避免按钮刷新后顺序错乱；
  5. `setSize(computeSize())` 并 `setDirtyCanvas(true, true)`。
- `onNodeCreated` 勾住 `input_count` widget 的 `callback`；`onConfigure` 在旧工作流 widget 恢复后再对齐一次。

### 边界情况
- `input_count` 之外的输入端口即便存在也不会被 Python 端读取（`kwargs.get` 取 None 会跳过）。
- 所有图均缩放到基准的"轴尺寸"，非基准轴尺寸按比例变化，不强制等宽或等高。

---

## 9. WuddOpenAIGPT54

**源文件**：`nodes_api.py` · `FUNCTION = "generate"`
**作用**：调用 OpenAI 兼容 API（GPT-5.4 系列），支持 Responses API 与 Chat Completions 两种模式、可选图像输入、轮询等待异步响应。

### 输入
| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `prompt` | STRING multiline | `""` | 必填 |
| `api_key` | STRING | `""` | Bearer token（必填） |
| `base_url` | STRING | `https://api.openai.com/v1` | 兼容 proxy / 自建 gateway |
| `model` | combo | `gpt-5.4` | `gpt-5.4 / gpt-5.4-mini / gpt-5.4-nano` |
| `api_mode` | combo | `responses` | `responses` 或 `chat_completions` |
| `reasoning_effort` | combo | `medium` | `none / low / medium / high / xhigh` |
| `verbosity` | combo | `medium` | `low / medium / high`（Responses 专用） |
| `verify_ssl` | BOOL | `True` | 关闭后 `ssl.CERT_NONE` |
| `max_output_tokens` | INT 16–131072 | `4096` | |
| `poll_interval` | FLOAT 0.2–10 | `1.0` | 轮询 Responses 状态的间隔秒 |
| `max_wait_seconds` | INT 5–3600 | `120` | 等待 Responses 完成的超时 |
| `instructions` (optional) | STRING multiline | `""` | 系统指令 |
| `images` (optional) | IMAGE | — | 多张图 batch |

### 输出
`(STRING, STRING)` 名 `text, response_id`。

### 核心算法
1. **入参预处理**：`_prepare_request(prompt, api_key, base_url)` 一处集中完成 —— `api_key` 必填；`prompt.strip()` 必须非空；`base_url` 缺省/无 scheme 自动补 `https://`，去尾斜杠。返回规整后的三元组。
2. **构造 payload**：
   - `chat_completions`：`messages=[{role:"user", content:[text + image_url(dataURL)]}]`，有 `instructions` 则 `insert(0, system)`；`max_completion_tokens`、可选 `reasoning_effort`。
   - `responses`：`input = [{role:"user", content:[input_text + input_image(dataURL)]}]`；`max_output_tokens`、`store:True`、`text.verbosity`、`reasoning.effort`；可选 `instructions` 顶级字段。
3. **图像编码**：调用模块级 `tensor_to_base64_png(images[i])`，把 `[H,W,C]` 映射到 `RGB`/`RGBA`，PNG bytes → base64，嵌为 `data:image/png;base64,…`。
4. **发送 HTTP**：`_http_json` 使用 `http.client`（不引入 requests 依赖）：
   - 依 scheme 选 HTTPS/HTTP connection；
   - `verify_ssl=False` 时构造 `ssl.CERT_NONE` context；
   - 读全量 body；`>=400` 抛 `ValueError` 带状态码 + 原始 body。
5. **Responses 异步轮询**：`responses` 模式下若 `status ∉ {completed, incomplete}`，用 `response_id` 按 `poll_interval` 轮询 `GET /responses/{id}` 直到完成 / 失败 / 超时（`TimeoutError`）。
6. **提取文本** (`_extract_text`)：
   - `chat_completions`：`choices[0].message.content`，兼容纯字符串与 `[{type:"text"}]` 两种结构；
   - `responses`：优先 `output_text` 顶级字段；否则扫描 `output[*].content[*].output_text`。
7. **返回** `(text, response_id)`；若 `text` 为空抛错（避免静默失败）。

### 边界情况
- SSL 失败 / OSError / 非 JSON body → 统一转成 `ValueError`，错误消息保留原始 body 便于排查。
- `reasoning_effort == "none"` 在 chat_completions 模式下不下发该字段。
- `response_id` 可能来自首次响应或轮询后的最终响应，代码兜底两者。

---

## 前端扩展文件：`web/dynamic_ports.js`

**入口**：`app.registerExtension({ name: "Wudd.DynamicPorts", beforeRegisterNodeDef(nodeType, nodeData) { … } })`

**分派**：以 `nodeData.name` 分四支注入不同 prototype 钩子。

**通用技巧**：
- 保留原 `nodeType.prototype.onNodeCreated / onConfigure / onConnectionsChange`，在自定义版本里先 `if (orig) orig.apply(this, arguments)` 再加自己逻辑，避免破坏其他扩展。
- 隐藏 widget 的标准手法：
  ```
  w.origType = w.type; w.origComputeSize = w.computeSize;
  w.type = "hidden"; w.computeSize = () => [0, -4];
  ```
  显示时复原即可；这套约定与 ComfyUI 其他社区节点兼容。
- `onConfigure` 阶段对齐动态输出/输入槽，以消除 `setTimeout` 与工作流恢复的竞态。
- 所有回调体用 `try/catch` 包裹 + `console.error("Wudd … Error:", e)`，不让前端异常抛到 ComfyUI 顶层。

---

## 与 ComfyUI 的集成约定

- `__init__.py` 暴露 `NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS / WEB_DIRECTORY`；
- 所有节点统一 `CATEGORY = "Wudd Nodes"`，便于在 ComfyUI 菜单栏聚合；
- `WuddMultiSaveImage` 是唯一 `OUTPUT_NODE`（需要向 UI 回推预览）；
- 其余节点均为纯函数式（给定输入得到输出），便于缓存与并行。
