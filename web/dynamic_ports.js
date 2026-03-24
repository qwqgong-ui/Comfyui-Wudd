
// 将 import { app } from "../../scripts/app.js"; 改为：
import { app } from "/scripts/app.js";

app.registerExtension({
    name: "Wudd.MultiSaveSafe",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "WuddMultiSaveImage") {

            // 1. 安全且动态的连线逻辑
            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected) {
                if (onConnectionsChange) onConnectionsChange.apply(this, arguments);
                // type === 1 代表输入端 (LiteGraph.INPUT)
                if (type === 1 && this.inputs) {
                    try {
                        // 当最后一个节点被连接时，自动增加一个新的 image 输入
                        if (connected && index === this.inputs.length - 1) {
                            this.addInput("image_" + (this.inputs.length + 1), "IMAGE");
                        }
                        // 当节点断开，且尾部有多个未连接的空闲输入时，自动清理
                        if (!connected && this.inputs.length > 1) {
                            while (this.inputs.length > 1 && !this.inputs[this.inputs.length - 1].link && !this.inputs[this.inputs.length - 2].link) {
                                this.removeInput(this.inputs.length - 1);
                            }
                        }
                    } catch (e) { console.error("Wudd Ports Error:", e); }
                }
            };

            // 2. 安全的显隐逻辑 (包含隐藏 png 时不需要的 jpg 参数)
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    const extWidget = this.widgets?.find(w => w.name === "extension");

                    // 预定义 JPEGli 专属组件的原始类型，防止被永久设为 hidden
                    const jpegliWidgets = {
                        "quality": "number",
                        "progressive": "toggle",
                        "enable_xyb": "toggle",
                        "chroma_subsampling": "combo"
                    };

                    const refresh = () => {
                        if (!this.widgets) return;
                        const isJpegli = extWidget?.value === "jpegli";

                        this.widgets.forEach(w => {
                            if (jpegliWidgets[w.name] !== undefined) {
                                // 如果是 jpegli 就恢复原本类型，否则隐藏
                                w.type = isJpegli ? jpegliWidgets[w.name] : "hidden";
                            }
                        });

                        // 强制刷新节点高度以适配隐藏的组件
                        if (this.computeSize) {
                            const newSize = this.computeSize();
                            this.size[0] = newSize[0];
                            this.size[1] = newSize[1];
                        }
                        this.setDirtyCanvas(true, true);
                    };

                    if (extWidget) {
                        // 缓存 ComfyUI 原始的 callback
                        const origCallback = extWidget.callback;

                        extWidget.callback = function () {
                            // 先执行你的刷新逻辑
                            refresh();
                            // 再执行 ComfyUI 官方的同步逻辑
                            if (origCallback) {
                                return origCallback.apply(this, arguments);
                            }
                        };
                        setTimeout(refresh, 100);
                    }
                    
                } catch (e) { console.error("Wudd Widget Error:", e); }
            };
        }
    }
});