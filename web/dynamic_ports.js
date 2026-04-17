import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Wudd.DynamicPorts",
    async beforeRegisterNodeDef(nodeType, nodeData) {

        // ==========================================
        // WuddMultiSaveImage — 动态输入端口
        // ==========================================
        if (nodeData.name === "WuddMultiSaveImage") {

            // 1. 动态输入端口逻辑
            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
                if (onConnectionsChange) onConnectionsChange.apply(this, arguments);

                if (this.__isUpdatingPorts) return;
                this.__isUpdatingPorts = true;

                // type 1 = INPUT
                if (type === 1 && this.inputs && this.inputs.length > 0) {
                    try {
                        // 清理尾部多余空闲端口，始终保留最后 1 个空端口
                        while (this.inputs.length > 1 &&
                               !this.inputs[this.inputs.length - 1].link &&
                               !this.inputs[this.inputs.length - 2].link) {
                            this.removeInput(this.inputs.length - 1);
                        }
                        // 最后一个端口被连上时自动新增一个空端口
                        const lastInput = this.inputs[this.inputs.length - 1];
                        if (lastInput && lastInput.link) {
                            this.addInput("image_" + (this.inputs.length + 1), "IMAGE");
                        }
                    } catch (e) {
                        console.error("Wudd Ports Error:", e);
                    }
                }

                this.__isUpdatingPorts = false;
            };

            // 2. 加载旧工作流时修复因 widget 版本迭代导致的值错位
            const COMBO_DEFAULTS = {
                save_mode:          { valid: ["append", "overwrite"],          def: "append" },
                extension:          { valid: ["png", "jpegli"],                def: "png"    },
                chroma_subsampling: { valid: ["444", "440", "422", "420"],     def: "444"    },
            };
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                if (!this.widgets) return;
                this.widgets.forEach(w => {
                    const spec = COMBO_DEFAULTS[w.name];
                    if (spec && !spec.valid.includes(w.value)) {
                        console.warn(`[Wudd] widget "${w.name}" had invalid value "${w.value}", reset to "${spec.def}"`);
                        w.value = spec.def;
                    }
                });
            };

            // 3. Jpegli 相关 widget 显隐逻辑
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    const extWidget = this.widgets?.find(w => w.name === "extension");
                    const targetNames = ["quality", "progressive", "enable_xyb", "chroma_subsampling"];

                    const refresh = () => {
                        if (!this.widgets) return;
                        const isJpegli = extWidget?.value === "jpegli";
                        let visibilityChanged = false;

                        this.widgets.forEach(w => {
                            if (targetNames.includes(w.name)) {
                                if (w.origType === undefined) {
                                    w.origType = w.type;
                                    w.origComputeSize = w.computeSize;
                                }
                                if (isJpegli) {
                                    if (w.type !== w.origType) {
                                        w.type = w.origType;
                                        w.computeSize = w.origComputeSize;
                                        visibilityChanged = true;
                                    }
                                } else {
                                    if (w.type !== "hidden") {
                                        w.type = "hidden";
                                        w.computeSize = () => [0, -4];
                                        visibilityChanged = true;
                                    }
                                }
                            }
                        });

                        if (visibilityChanged && this.setSize && this.computeSize) {
                            setTimeout(() => {
                                try {
                                    this.setSize(this.computeSize());
                                    if (this.setDirtyCanvas) this.setDirtyCanvas(true, true);
                                } catch (e) {}
                            }, 10);
                        }
                    };

                    if (extWidget) {
                        const origCallback = extWidget.callback;
                        extWidget.callback = function () {
                            refresh();
                            if (origCallback) return origCallback.apply(this, arguments);
                        };
                        setTimeout(refresh, 50);
                    }
                } catch (e) {
                    console.error("Wudd Widget Error:", e);
                }
            };
        }

        // ==========================================
        // WuddMultiTextSplitter — 动态输出端口
        // ==========================================
        if (nodeData.name === "WuddMultiTextSplitter") {

            // 独立辅助函数，避免 this 绑定问题，onNodeCreated / onConfigure 均可调用
            function applyOutputCount(node, count) {
                while (node.outputs && node.outputs.length > count) {
                    node.removeOutput(node.outputs.length - 1);
                }
                while (!node.outputs || node.outputs.length < count) {
                    const idx = node.outputs ? node.outputs.length : 0;
                    node.addOutput(`line_${idx}`, "STRING");
                }
                if (node.setSize && node.computeSize) {
                    try { node.setSize(node.computeSize()); } catch (e) {}
                }
                if (node.setDirtyCanvas) node.setDirtyCanvas(true, true);
            }

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    const countWidget = this.widgets?.find(w => w.name === "count");
                    if (!countWidget) return;

                    const node = this;

                    // 监听 count widget 变化
                    const origCallback = countWidget.callback;
                    countWidget.callback = function () {
                        applyOutputCount(node, countWidget.value);
                        if (origCallback) return origCallback.apply(this, arguments);
                    };

                    // 新建节点时初始化输出槽数量
                    // 延迟执行以等待 ComfyUI 完成默认输出槽的注册
                    setTimeout(() => applyOutputCount(node, countWidget.value), 50);
                } catch (e) {
                    console.error("Wudd MultiTextSplitter Error:", e);
                }
            };

            // 加载旧工作流时，onConfigure 在 widget 值恢复后同步调用，
            // 此时 countWidget.value 已是保存的值，直接对齐输出槽数量，
            // 消除 setTimeout 与配置恢复之间的竞态条件。
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try {
                    const countWidget = this.widgets?.find(w => w.name === "count");
                    if (countWidget) applyOutputCount(this, countWidget.value);
                } catch (e) {}
            };
        }

        // ==========================================
        // WuddImageListImporter — 动态输入与输出
        // ==========================================
        if (nodeData.name === "WuddImageListImporter") {
            function applyImageCount(node, count) {
                // 1. Show/hide upload widgets and their corresponding buttons
                if (node.widgets) {
                    for (let i = 0; i < node.widgets.length; i++) {
                        const w = node.widgets[i];
                        if (w.name && w.name.startsWith("image_")) {
                            const match = w.name.match(/^image_(\d+)$/);
                            if (match) {
                                const idx = parseInt(match[1]);
                                const shouldHide = idx > count;
                                
                                // Hide/show combo widget
                                if (shouldHide) {
                                    if (w.type !== "hidden") {
                                        w.origType = w.type;
                                        w.origComputeSize = w.computeSize;
                                        w.type = "hidden";
                                        w.computeSize = () => [0, -4];
                                    }
                                } else {
                                    if (w.type === "hidden" && w.origType) {
                                        w.type = w.origType;
                                        w.computeSize = w.origComputeSize;
                                    }
                                }

                                // ComfyUI injects the upload button immediately after the combo widget
                                const nextW = node.widgets[i + 1];
                                if (nextW && nextW.type === "button") {
                                    if (shouldHide) {
                                        if (nextW.type !== "hidden") {
                                            nextW.origType = nextW.type;
                                            nextW.origComputeSize = nextW.computeSize;
                                            nextW.type = "hidden";
                                            nextW.computeSize = () => [0, -4];
                                        }
                                    } else {
                                        if (nextW.type === "hidden" && nextW.origType) {
                                            nextW.type = nextW.origType;
                                            nextW.computeSize = nextW.origComputeSize;
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
                
                // 2. Add/remove output ports
                while (node.outputs && node.outputs.length > count) {
                    node.removeOutput(node.outputs.length - 1);
                }
                while (!node.outputs || node.outputs.length < count) {
                    const idx = node.outputs ? node.outputs.length + 1 : 1;
                    node.addOutput(`image_${idx}`, "IMAGE");
                }
                
                if (node.setSize && node.computeSize) {
                    try { node.setSize(node.computeSize()); } catch (e) {}
                }
                if (node.setDirtyCanvas) node.setDirtyCanvas(true, true);
            }

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                try {
                    const countWidget = this.widgets?.find(w => w.name === "image_count");
                    if (!countWidget) return;
                    const node = this;
                    
                    const origCallback = countWidget.callback;
                    countWidget.callback = function () {
                        applyImageCount(node, countWidget.value);
                        if (origCallback) return origCallback.apply(this, arguments);
                    };
                    
                    setTimeout(() => applyImageCount(node, countWidget.value), 50);
                } catch (e) {
                    console.error("Wudd ImageListImporter Error:", e);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try {
                    const countWidget = this.widgets?.find(w => w.name === "image_count");
                    if (countWidget) applyImageCount(this, countWidget.value);
                } catch (e) {}
            };
        }
    }
});
